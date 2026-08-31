import { execFile } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const execFileAsync = promisify(execFile);
const BRIDGE = fileURLToPath(new URL("./pi_tracecite_bridge.py", import.meta.url));
const SESSION = process.env.TRACECITE_PI_SESSION ||
  process.env.TRACECITE_PI_INVESTIGATION ||
  join(tmpdir(), `tracecite-pi-${process.pid}`, "retrieval-session.json");
const ACTIVITY_PATH = process.env.TRACECITE_PI_ACTIVITY ||
  join(dirname(SESSION), "host-tool-activity.json");
const TRACE_TOOLS = new Set([
  "tracecite_retrieve", "tracecite_materialize", "tracecite_replay",
  "tracecite_aggregate", "tracecite_traverse", "tracecite_verify",
  "tracecite_search", "tracecite_expand",
]);

type Category = "tracecite_evidence" | "native_search" | "native_read" | "opaque_shell" | "native_other" | "other";
type Activity = { tool: string; category: Category; duration_ms: number; status: string; metadata?: Record<string, unknown> };
type EvidenceProgressEvent = {
  operation: "retrieve" | "materialize";
  status: string;
  new_evidence: number | null;
  repeated_evidence: number | null;
  unseen_range_count: number;
  added_evidence: boolean;
  low_novelty: boolean;
};

const starts = new Map<string, number>();
const events: Activity[] = [];
const recentEvidenceProgress: EvidenceProgressEvent[] = [];
let activityWrite: Promise<void> = Promise.resolve();

function category(tool: string): Category {
  if (TRACE_TOOLS.has(tool)) return "tracecite_evidence";
  if (tool === "grep" || tool === "find") return "native_search";
  if (tool === "read") return "native_read";
  if (tool === "bash") return "opaque_shell";
  if (tool === "ls") return "native_other";
  return "other";
}

function activitySummary() {
  const categories: Record<string, number> = {};
  const tools: Record<string, number> = {};
  let observed_duration_ms = 0;
  for (const event of events) {
    categories[event.category] = (categories[event.category] || 0) + 1;
    tools[event.tool] = (tools[event.tool] || 0) + 1;
    observed_duration_ms += event.duration_ms;
  }
  return { total_tool_calls: events.length, categories, tools, observed_duration_ms };
}

async function persistActivity() {
  await mkdir(dirname(ACTIVITY_PATH), { recursive: true });
  await writeFile(ACTIVITY_PATH, JSON.stringify({ schema_version: 1, summary: activitySummary(), events }, null, 2) + "\n", "utf8");
}

async function bridge(args: string[], cwd: string, signal?: AbortSignal): Promise<string> {
  try {
    const { stdout, stderr } = await execFileAsync("python", [BRIDGE, "--session", SESSION, ...args], {
      cwd, encoding: "utf8", maxBuffer: 256 * 1024, signal,
    });
    const out = String(stdout || "").trim();
    const err = String(stderr || "").trim();
    if (out && err) return `${out}\n@STDERR ${err}`;
    return out || err || "{}";
  } catch (error: any) {
    return `@TRACECITE_ERROR ${String(error?.message || error || "bridge failed")}`;
  }
}

function compact(text: string): string {
  let p: any;
  try { p = JSON.parse(text); } catch { return text; }
  if (!p || typeof p !== "object") return text;
  const data = p.data && typeof p.data === "object" ? p.data : {};
  const coverage = p.coverage && typeof p.coverage === "object" ? p.coverage : {};
  const operation = String(p.operation || "");
  const evidence = Array.isArray(p.evidence) ? p.evidence.map((row: any) => {
    const start = Number(row?.start_line || 0);
    const end = Number(row?.end_line || start || 0);
    const source = String(row?.source_path || "").split(/[\\/]/).pop() || "evidence";
    return {
      ref: start > 0 ? `${source}:L${start}${end > start ? `-L${end}` : ""}` : undefined,
      uri: start > 0 ? undefined : row?.uri,
      preview: String(row?.label || "").slice(0, 420) || undefined,
    };
  }) : [];
  const sha256 = (() => {
    const values = Array.from(new Set((Array.isArray(p.evidence) ? p.evidence : [])
      .map((row: any) => String(row?.sha256 || "").toLowerCase())
      .filter((v: string) => /^[0-9a-f]{64}$/.test(v))));
    return values.length === 1 ? values[0] : p.sha256;
  })();

  if (["search", "retrieve", "probe"].includes(operation)) {
    return JSON.stringify({
      operation: "retrieve", status: p.status, evidence, source_sha256: sha256,
      matched_existing_evidence: data.matched_existing_evidence,
      coverage, progress: data.progress, correlation_constraints: data.correlation_constraints,
      missing_evidence: p.missing_evidence, acquisition_end_reason: data.acquisition_end_reason,
    });
  }
  if (["expand", "materialize", "replay"].includes(operation)) {
    return JSON.stringify({
      operation: operation === "replay" ? "replay" : "materialize",
      status: p.status, evidence, source_sha256: sha256, coverage, progress: data.progress,
      text: data.new_text !== undefined ? data.new_text : data.text,
      replayed: Boolean(data.replayed || operation === "replay") || undefined,
      unseen_ranges: data.unseen_ranges, observed_references: data.observed_references,
      observed_relations: data.observed_relations, acquisition_end_reason: data.acquisition_end_reason,
    });
  }
  if (operation === "aggregate") {
    return JSON.stringify({ operation, status: p.status, source: p.source, source_sha256: sha256, query: p.query, regex: p.regex, aggregate: p.aggregate, data, coverage });
  }
  if (operation === "traverse") {
    return JSON.stringify({ operation, status: p.status, stop_reason: p.stop_reason, coverage: p.coverage, progress: p.progress, trace: p.trace, diagnostics: p.diagnostics, graph: p.graph, grouping: p.grouping, reduction: p.reduction, acquisition_end_reason: p.acquisition_end_reason });
  }
  if (operation === "verify") {
    return JSON.stringify({ operation, status: p.status, coverage: p.coverage, verification: p.verification, data, error: p.error });
  }
  return text;
}

function addAgentFeedback(text: string): string {
  let payload: any;
  try { payload = JSON.parse(text); } catch { return text; }
  if (!payload || typeof payload !== "object") return text;

  const operation = String(payload.operation || "");
  if (operation === "retrieve" || operation === "materialize") {
    const coverage = payload.coverage && typeof payload.coverage === "object" ? payload.coverage : {};
    const newEvidence = Number.isInteger(coverage.new_evidence) ? Number(coverage.new_evidence) : null;
    const repeatedEvidence = Number.isInteger(coverage.repeated_evidence) ? Number(coverage.repeated_evidence) : null;
    const unseenRangeCount = Array.isArray(payload.unseen_ranges) ? payload.unseen_ranges.length : 0;
    const hasEvidence = Array.isArray(payload.evidence) && payload.evidence.length > 0;
    const hasText = typeof payload.text === "string" && payload.text.trim().length > 0;
    const addedEvidence = hasEvidence || hasText || unseenRangeCount > 0 || (newEvidence !== null && newEvidence > 0);
    const status = String(payload.status || "");
    const lowNovelty = status === "no_match" || status === "no_new_evidence" || (
      !addedEvidence && newEvidence === 0 && (repeatedEvidence ?? 0) > 0
    );
    recentEvidenceProgress.push({
      operation,
      status,
      new_evidence: newEvidence,
      repeated_evidence: repeatedEvidence,
      unseen_range_count: unseenRangeCount,
      added_evidence: addedEvidence,
      low_novelty: lowNovelty,
    });
    if (recentEvidenceProgress.length > 12) recentEvidenceProgress.splice(0, recentEvidenceProgress.length - 12);
  }

  const recent = recentEvidenceProgress.slice(-4);
  let lowNoveltyStreak = 0;
  for (let index = recentEvidenceProgress.length - 1; index >= 0; index -= 1) {
    if (!recentEvidenceProgress[index].low_novelty) break;
    lowNoveltyStreak += 1;
  }
  const lowNoveltyInRecentWindow = recent.filter((item) => item.low_novelty).length;
  const checkpointTriggered = lowNoveltyStreak >= 3 || (recent.length === 4 && lowNoveltyInRecentWindow >= 3);

  payload.agent_feedback = {
    evidence_progress: {
      recent_frontier_operations: recent.length,
      low_novelty_streak: lowNoveltyStreak,
      low_novelty_in_recent_window: lowNoveltyInRecentWindow,
      recent,
    },
    convergence_checkpoint: checkpointTriggered ? {
      triggered: true,
      reason: "Recent retrieve/materialize operations are mostly repeating covered evidence or returning no new evidence.",
      reassess_before_next_evidence_call: [
        "What exact unresolved question still matters to the task?",
        "What materially different evidence should the next call add?",
        "Does the supplied evidence actually contain the source/component/time range needed to resolve that question?",
        "If not, state the evidence boundary instead of paraphrasing the same search again.",
      ],
    } : { triggered: false },
  };
  return JSON.stringify(payload);
}

function output(text: string, details: Record<string, unknown>) {
  return { content: [{ type: "text" as const, text: addAgentFeedback(text) }], details: { ...details, persistent_retrieval_session: true, evidence_only: true } };
}

function rangeArgs(command: string, params: any): string[] {
  const args = [command, params.file, String(params.line), "--radius", String(params.radius ?? 8), "--max-chars", "12000"];
  if (params.sha256) args.push("--sha256", params.sha256);
  return args;
}

export default function traceciteTools(pi: ExtensionAPI) {
  pi.on("tool_call", async (event) => { starts.set(event.toolCallId, Date.now()); });
  pi.on("tool_result", async (event) => {
    const started = starts.get(event.toolCallId) ?? Date.now();
    starts.delete(event.toolCallId);
    const row: Activity = {
      tool: event.toolName, category: category(event.toolName),
      duration_ms: Math.max(0, Date.now() - started), status: event.isError ? "error" : "ok",
      metadata: event.toolName === "bash" ? { opaque: true } : undefined,
    };
    events.push(row);
    if (events.length > 512) events.splice(0, events.length - 512);
    activityWrite = activityWrite.then(persistActivity, persistActivity);
    await activityWrite;
    const base = event.details && typeof event.details === "object" && !Array.isArray(event.details) ? event.details as Record<string, unknown> : {};
    return { details: { ...base, tracecite_host_activity: row, tracecite_host_activity_summary: activitySummary() } } as any;
  });

  pi.registerTool({
    name: "tracecite_retrieve", label: "TraceCite Retrieve",
    description: "Canonical retrieve for caller-selected local evidence. Preserves provenance, coverage, identity safety and RetrievalSession novelty; returns Agent-facing mechanical convergence feedback but never chooses hypotheses or stopping.",
    parameters: Type.Object({
      file: Type.String(), query: Type.Optional(Type.String()), regex: Type.Optional(Type.Boolean()),
      max_evidence: Type.Optional(Type.Integer({ minimum: 1, maximum: 50 })),
      glob: Type.Optional(Type.String()), recursive: Type.Optional(Type.Boolean()),
    }),
    async execute(_id, p, signal, _update, ctx) {
      const args = ["retrieve", p.file, "--max-evidence", String(p.max_evidence ?? 20)];
      if (p.query) args.push("--query", p.query);
      if (p.regex) args.push("--regex");
      if (p.glob) args.push("--glob", p.glob);
      if (p.recursive) args.push("--recursive");
      return output(compact(await bridge(args, ctx.cwd, signal)), { operation: "retrieve", canonical_operation: true });
    },
  });

  pi.registerTool({
    name: "tracecite_materialize", label: "TraceCite Materialize",
    description: "Canonical materialize of exact bounded caller-selected source context with immutable identity and session coverage. Radius is 0..30; use deliberate adjacent ranges instead of invalid larger radii.",
    parameters: Type.Object({
      file: Type.String(), line: Type.Integer({ minimum: 1 }),
      radius: Type.Optional(Type.Integer({ minimum: 0, maximum: 30 })), sha256: Type.Optional(Type.String()),
    }),
    async execute(_id, p, signal, _update, ctx) {
      return output(compact(await bridge(rangeArgs("materialize", p), ctx.cwd, signal)), { operation: "materialize", canonical_operation: true });
    },
  });

  pi.registerTool({
    name: "tracecite_replay", label: "TraceCite Replay",
    description: "Canonical replay of previously materialized immutable context without counting it as new evidence. Radius is 0..30.",
    parameters: Type.Object({
      file: Type.String(), line: Type.Integer({ minimum: 1 }),
      radius: Type.Optional(Type.Integer({ minimum: 0, maximum: 30 })), sha256: Type.String(),
    }),
    async execute(_id, p, signal, _update, ctx) {
      return output(compact(await bridge(rangeArgs("replay", p), ctx.cwd, signal)), { operation: "replay", canonical_operation: true });
    },
  });

  pi.registerTool({
    name: "tracecite_aggregate", label: "TraceCite Aggregate",
    description: "Canonical deterministic count/distinct/group over caller-selected local text matches with source provenance; no causal ranking.",
    parameters: Type.Object({
      file: Type.String(), query: Type.String(), regex: Type.Optional(Type.Boolean()),
      operation: Type.Optional(Type.Union([Type.Literal("count"), Type.Literal("distinct"), Type.Literal("group")])),
      group_regex: Type.Optional(Type.String()), max_groups: Type.Optional(Type.Integer({ minimum: 1, maximum: 500 })),
    }),
    async execute(_id, p, signal, _update, ctx) {
      const args = ["aggregate", p.file, p.query, "--operation", p.operation ?? "count", "--max-groups", String(p.max_groups ?? 100)];
      if (p.regex) args.push("--regex");
      if (p.group_regex) args.push("--group-regex", p.group_regex);
      return output(compact(await bridge(args, ctx.cwd, signal)), { operation: "aggregate", canonical_operation: true });
    },
  });

  pi.registerTool({
    name: "tracecite_traverse", label: "TraceCite Traverse",
    description: "Canonical bounded provider traversal over caller-selected evidence IDs/entities. The Agent owns seeds, limits, hypotheses and interpretation.",
    parameters: Type.Object({
      provider_file: Type.String(), seed_evidence_ids: Type.Optional(Type.Array(Type.String(), { maxItems: 50 })),
      seed_entities: Type.Optional(Type.Array(Type.Object({ kind: Type.String(), value: Type.String(), namespace: Type.Optional(Type.String()) }), { maxItems: 50 })),
      max_depth: Type.Optional(Type.Integer({ minimum: 0, maximum: 8 })),
      max_retrievals: Type.Optional(Type.Integer({ minimum: 1, maximum: 100 })),
      max_evidence: Type.Optional(Type.Integer({ minimum: 1, maximum: 2000 })),
      max_wall_seconds: Type.Optional(Type.Number({ minimum: 0.1, maximum: 30 })),
      per_request_limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 500 })),
    }),
    async execute(_id, p, signal, _update, ctx) {
      const args = ["traverse", p.provider_file, "--max-depth", String(p.max_depth ?? 3), "--max-retrievals", String(p.max_retrievals ?? 12), "--max-evidence", String(p.max_evidence ?? 500), "--max-wall-seconds", String(p.max_wall_seconds ?? 5), "--per-request-limit", String(p.per_request_limit ?? 100)];
      for (const id of p.seed_evidence_ids ?? []) args.push("--seed-evidence-id", id);
      for (const entity of p.seed_entities ?? []) args.push("--seed-entity", JSON.stringify(entity));
      return output(compact(await bridge(args, ctx.cwd, signal)), { operation: "traverse", canonical_operation: true });
    },
  });

  pi.registerTool({
    name: "tracecite_verify", label: "TraceCite Verify",
    description: "Canonical mechanical evidence-manifest integrity verification; does not validate the Agent's causal conclusion.",
    parameters: Type.Object({ manifest: Type.String() }),
    async execute(_id, p, signal, _update, ctx) {
      return output(compact(await bridge(["verify", p.manifest], ctx.cwd, signal)), { operation: "verify", canonical_operation: true });
    },
  });

  // Compatibility aliases. The canonical A/B workflow does not expose them.
  pi.registerTool({
    name: "tracecite_search", label: "TraceCite Search (compat)", description: "Compatibility alias for tracecite_retrieve.",
    parameters: Type.Object({ file: Type.String(), query: Type.String(), regex: Type.Optional(Type.Boolean()), max_evidence: Type.Optional(Type.Integer({ minimum: 1, maximum: 50 })) }),
    async execute(_id, p, signal, _update, ctx) {
      const args = ["retrieve", p.file, "--query", p.query, "--max-evidence", String(p.max_evidence ?? 20)];
      if (p.regex) args.push("--regex");
      return output(compact(await bridge(args, ctx.cwd, signal)), { operation: "retrieve", compatibility_alias: "tracecite_search" });
    },
  });
  pi.registerTool({
    name: "tracecite_expand", label: "TraceCite Expand (compat)", description: "Compatibility alias for tracecite_materialize/replay.",
    parameters: Type.Object({ file: Type.String(), line: Type.Integer({ minimum: 1 }), radius: Type.Optional(Type.Integer({ minimum: 0, maximum: 30 })), sha256: Type.Optional(Type.String()), replay: Type.Optional(Type.Boolean()) }),
    async execute(_id, p, signal, _update, ctx) {
      const op = p.replay ? "replay" : "materialize";
      return output(compact(await bridge(rangeArgs(op, p), ctx.cwd, signal)), { operation: op, compatibility_alias: "tracecite_expand" });
    },
  });
}
