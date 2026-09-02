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

const starts = new Map<string, number>();
const events: Activity[] = [];
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
  await writeFile(
    ACTIVITY_PATH,
    JSON.stringify({ schema_version: 1, summary: activitySummary(), events }, null, 2) + "\n",
    "utf8",
  );
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

function availableSources(): string[] | undefined {
  const configured = String(process.env.TRACECITE_EVIDENCE_FILES || "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
  const unique = Array.from(new Set(configured)).slice(0, 50);
  return unique.length ? unique : undefined;
}

function neutralPreview(value: unknown): string | undefined {
  let text = String(value || "").trim();
  if (!text) return undefined;
  for (const phrase of [
    "use access_file for later TraceCite calls",
    "snapshot refs are citations, not file paths",
    "reuse follow_up_file for later TraceCite calls",
    "materialize this range with TraceCite before citing",
  ]) {
    text = text.replace(phrase, "").replace(/\s+/g, " ").trim();
  }
  return text.slice(0, 300) || undefined;
}

function compactCoverage(value: any): Record<string, unknown> | undefined {
  if (!value || typeof value !== "object") return undefined;
  const keys = [
    "files", "scoped_lines", "match_records", "match_lines",
    "evidence_returned", "evidence_truncated", "signal_hints_returned",
    "context_start_line", "context_end_line", "truncated",
    "new_evidence", "repeated_evidence",
  ];
  const result: Record<string, unknown> = {};
  for (const key of keys) {
    if (value[key] !== undefined && value[key] !== null) result[key] = value[key];
  }
  return Object.keys(result).length ? result : undefined;
}

function compactProgress(value: any): Record<string, unknown> | undefined {
  if (!value || typeof value !== "object") return undefined;
  const result: Record<string, unknown> = {};
  const delta = value.delta && typeof value.delta === "object" ? value.delta : undefined;
  if (delta) {
    const smallDelta: Record<string, unknown> = {};
    for (const key of ["new_evidence", "new_lines", "grew"]) {
      if (delta[key] !== undefined && delta[key] !== null) smallDelta[key] = delta[key];
    }
    if (Object.keys(smallDelta).length) result.delta = smallDelta;
  }
  for (const key of [
    "seen_evidence", "seen_lines", "coverage_status", "source_complete",
    "frontier_exhausted", "scope_exhausted", "consecutive_no_growth",
  ]) {
    if (value[key] !== undefined && value[key] !== null) result[key] = value[key];
  }
  return Object.keys(result).length ? result : undefined;
}

function compactMatchedExisting(value: any): Array<Record<string, number>> | undefined {
  if (!Array.isArray(value) || !value.length) return undefined;
  const rows = value.map((row: any) => {
    const start = Number(row?.start_line || 0);
    const end = Number(row?.end_line || start || 0);
    return end > start ? { start_line: start, end_line: end } : { start_line: start };
  }).filter((row: any) => row.start_line > 0);
  return rows.length ? rows : undefined;
}

function compact(text: string): string {
  let p: any;
  try { p = JSON.parse(text); } catch { return text; }
  if (!p || typeof p !== "object") return text;

  const data = p.data && typeof p.data === "object" ? p.data : {};
  const operation = String(p.operation || "");
  const evidence = Array.isArray(p.evidence) ? p.evidence.map((row: any) => {
    const start = Number(row?.start_line || 0);
    const end = Number(row?.end_line || start || 0);
    const source = String(row?.source_path || "").split(/[\\/]/).pop() || "evidence";
    return {
      ref: start > 0 ? `${source}:L${start}${end > start ? `-L${end}` : ""}` : undefined,
      uri: start > 0 ? undefined : row?.uri,
      preview: neutralPreview(row?.label),
    };
  }) : [];
  const sha256 = (() => {
    const values = Array.from(new Set((Array.isArray(p.evidence) ? p.evidence : [])
      .map((row: any) => String(row?.sha256 || "").toLowerCase())
      .filter((v: string) => /^[0-9a-f]{64}$/.test(v))));
    return values.length === 1 ? values[0] : p.sha256;
  })();
  const sources = p.status === "error" ? availableSources() : undefined;

  if (["search", "retrieve", "probe"].includes(operation)) {
    return JSON.stringify({
      operation: "retrieve",
      status: p.status,
      evidence,
      available_sources: sources,
      source_sha256: sha256,
      matched_existing_evidence: compactMatchedExisting(data.matched_existing_evidence),
      coverage: compactCoverage(p.coverage),
      progress: compactProgress(data.progress),
      correlation_constraints: data.correlation_constraints,
      missing_evidence: p.missing_evidence,
      acquisition_end_reason: data.acquisition_end_reason,
    });
  }
  if (["expand", "materialize", "replay"].includes(operation)) {
    return JSON.stringify({
      operation: operation === "replay" ? "replay" : "materialize",
      status: p.status,
      evidence,
      available_sources: sources,
      source_sha256: sha256,
      coverage: compactCoverage(p.coverage),
      progress: compactProgress(data.progress),
      text: data.new_text !== undefined ? data.new_text : data.text,
      replayed: Boolean(data.replayed || operation === "replay") || undefined,
      unseen_ranges: data.unseen_ranges,
      observed_references: data.observed_references,
      observed_relations: data.observed_relations,
      acquisition_end_reason: data.acquisition_end_reason,
    });
  }
  if (operation === "aggregate") {
    return JSON.stringify({
      operation, status: p.status, source: p.source, source_sha256: sha256,
      query: p.query, regex: p.regex, aggregate: p.aggregate, data,
      coverage: compactCoverage(p.coverage),
    });
  }
  if (operation === "traverse") {
    return JSON.stringify({
      operation, status: p.status, stop_reason: p.stop_reason,
      coverage: compactCoverage(p.coverage), progress: compactProgress(p.progress),
      trace: p.trace, diagnostics: p.diagnostics, graph: p.graph,
      grouping: p.grouping, reduction: p.reduction,
      acquisition_end_reason: p.acquisition_end_reason,
    });
  }
  if (operation === "verify") {
    return JSON.stringify({
      operation, status: p.status, coverage: compactCoverage(p.coverage),
      verification: p.verification, data, error: p.error,
    });
  }
  return text;
}

function output(text: string, details: Record<string, unknown>) {
  return {
    content: [{ type: "text" as const, text }],
    details: { ...details, persistent_retrieval_session: true, evidence_only: true },
  };
}

function rangeArgs(command: string, params: any): string[] {
  const args = [
    command,
    params.file,
    String(params.line),
    "--radius",
    String(params.radius ?? 8),
    "--max-chars",
    "12000",
  ];
  if (params.sha256) args.push("--sha256", params.sha256);
  return args;
}

export default function traceciteTools(pi: ExtensionAPI) {
  pi.on("tool_call", async (event) => { starts.set(event.toolCallId, Date.now()); });
  pi.on("tool_result", async (event) => {
    const started = starts.get(event.toolCallId) ?? Date.now();
    starts.delete(event.toolCallId);
    const row: Activity = {
      tool: event.toolName,
      category: category(event.toolName),
      duration_ms: Math.max(0, Date.now() - started),
      status: event.isError ? "error" : "ok",
      metadata: event.toolName === "bash" ? { opaque: true } : undefined,
    };
    events.push(row);
    if (events.length > 512) events.splice(0, events.length - 512);
    activityWrite = activityWrite.then(persistActivity, persistActivity);
    await activityWrite;
    const base = event.details && typeof event.details === "object" && !Array.isArray(event.details)
      ? event.details as Record<string, unknown>
      : {};
    return {
      details: {
        ...base,
        tracecite_host_activity: row,
        tracecite_host_activity_summary: activitySummary(),
      },
    } as any;
  });

  pi.registerTool({
    name: "tracecite_retrieve",
    label: "TraceCite Retrieve",
    description: "Retrieve caller-selected local evidence with provenance, coverage, identity safety and RetrievalSession novelty. Interpretation, hypotheses and stopping belong to the Agent.",
    parameters: Type.Object({
      file: Type.String(),
      query: Type.Optional(Type.String()),
      regex: Type.Optional(Type.Boolean()),
      max_evidence: Type.Optional(Type.Integer({ minimum: 1, maximum: 50 })),
      glob: Type.Optional(Type.String()),
      recursive: Type.Optional(Type.Boolean()),
    }),
    async execute(_id, p, signal, _update, ctx) {
      const args = ["retrieve", p.file, "--max-evidence", String(p.max_evidence ?? 20)];
      if (p.query) args.push("--query", p.query);
      if (p.regex) args.push("--regex");
      if (p.glob) args.push("--glob", p.glob);
      if (p.recursive) args.push("--recursive");
      return output(compact(await bridge(args, ctx.cwd, signal)), {
        operation: "retrieve", canonical_operation: true,
      });
    },
  });

  pi.registerTool({
    name: "tracecite_materialize",
    label: "TraceCite Materialize",
    description: "Materialize exact bounded caller-selected source context with immutable identity and session coverage. Radius is 0..30.",
    parameters: Type.Object({
      file: Type.String(),
      line: Type.Integer({ minimum: 1 }),
      radius: Type.Optional(Type.Integer({ minimum: 0, maximum: 30 })),
      sha256: Type.Optional(Type.String()),
    }),
    async execute(_id, p, signal, _update, ctx) {
      return output(compact(await bridge(rangeArgs("materialize", p), ctx.cwd, signal)), {
        operation: "materialize", canonical_operation: true,
      });
    },
  });

  pi.registerTool({
    name: "tracecite_replay",
    label: "TraceCite Replay",
    description: "Replay previously materialized immutable context without counting it as new evidence. Radius is 0..30.",
    parameters: Type.Object({
      file: Type.String(),
      line: Type.Integer({ minimum: 1 }),
      radius: Type.Optional(Type.Integer({ minimum: 0, maximum: 30 })),
      sha256: Type.String(),
    }),
    async execute(_id, p, signal, _update, ctx) {
      return output(compact(await bridge(rangeArgs("replay", p), ctx.cwd, signal)), {
        operation: "replay", canonical_operation: true,
      });
    },
  });

  pi.registerTool({
    name: "tracecite_aggregate",
    label: "TraceCite Aggregate",
    description: "Deterministic count/distinct/group over caller-selected local text matches with source provenance.",
    parameters: Type.Object({
      file: Type.String(),
      query: Type.String(),
      regex: Type.Optional(Type.Boolean()),
      operation: Type.Optional(Type.Union([
        Type.Literal("count"), Type.Literal("distinct"), Type.Literal("group"),
      ])),
      group_regex: Type.Optional(Type.String()),
      max_groups: Type.Optional(Type.Integer({ minimum: 1, maximum: 500 })),
    }),
    async execute(_id, p, signal, _update, ctx) {
      const args = [
        "aggregate", p.file, p.query,
        "--operation", p.operation ?? "count",
        "--max-groups", String(p.max_groups ?? 100),
      ];
      if (p.regex) args.push("--regex");
      if (p.group_regex) args.push("--group-regex", p.group_regex);
      return output(compact(await bridge(args, ctx.cwd, signal)), {
        operation: "aggregate", canonical_operation: true,
      });
    },
  });

  pi.registerTool({
    name: "tracecite_traverse",
    label: "TraceCite Traverse",
    description: "Bounded provider traversal over caller-selected evidence IDs/entities. Seeds, limits and interpretation belong to the Agent.",
    parameters: Type.Object({
      provider_file: Type.String(),
      seed_evidence_ids: Type.Optional(Type.Array(Type.String(), { maxItems: 50 })),
      seed_entities: Type.Optional(Type.Array(Type.Object({
        kind: Type.String(), value: Type.String(), namespace: Type.Optional(Type.String()),
      }), { maxItems: 50 })),
      max_depth: Type.Optional(Type.Integer({ minimum: 0, maximum: 8 })),
      max_retrievals: Type.Optional(Type.Integer({ minimum: 1, maximum: 100 })),
      max_evidence: Type.Optional(Type.Integer({ minimum: 1, maximum: 2000 })),
      max_wall_seconds: Type.Optional(Type.Number({ minimum: 0.1, maximum: 30 })),
      per_request_limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 500 })),
    }),
    async execute(_id, p, signal, _update, ctx) {
      const args = [
        "traverse", p.provider_file,
        "--max-depth", String(p.max_depth ?? 3),
        "--max-retrievals", String(p.max_retrievals ?? 12),
        "--max-evidence", String(p.max_evidence ?? 500),
        "--max-wall-seconds", String(p.max_wall_seconds ?? 5),
        "--per-request-limit", String(p.per_request_limit ?? 100),
      ];
      for (const id of p.seed_evidence_ids ?? []) args.push("--seed-evidence-id", id);
      for (const entity of p.seed_entities ?? []) args.push("--seed-entity", JSON.stringify(entity));
      return output(compact(await bridge(args, ctx.cwd, signal)), {
        operation: "traverse", canonical_operation: true,
      });
    },
  });

  pi.registerTool({
    name: "tracecite_verify",
    label: "TraceCite Verify",
    description: "Mechanical evidence-manifest integrity verification. It does not validate causal conclusions or expand raw evidence coverage.",
    parameters: Type.Object({ manifest: Type.String() }),
    async execute(_id, p, signal, _update, ctx) {
      return output(compact(await bridge(["verify", p.manifest], ctx.cwd, signal)), {
        operation: "verify", canonical_operation: true,
      });
    },
  });

  // Compatibility aliases. They preserve the same evidence-only runtime contract.
  pi.registerTool({
    name: "tracecite_search",
    label: "TraceCite Search (compat)",
    description: "Compatibility alias for tracecite_retrieve.",
    parameters: Type.Object({
      file: Type.String(),
      query: Type.String(),
      regex: Type.Optional(Type.Boolean()),
      max_evidence: Type.Optional(Type.Integer({ minimum: 1, maximum: 50 })),
    }),
    async execute(_id, p, signal, _update, ctx) {
      const args = [
        "retrieve", p.file, "--query", p.query,
        "--max-evidence", String(p.max_evidence ?? 20),
      ];
      if (p.regex) args.push("--regex");
      return output(compact(await bridge(args, ctx.cwd, signal)), {
        operation: "retrieve", compatibility_alias: "tracecite_search",
      });
    },
  });

  pi.registerTool({
    name: "tracecite_expand",
    label: "TraceCite Expand (compat)",
    description: "Compatibility alias for tracecite_materialize/replay.",
    parameters: Type.Object({
      file: Type.String(),
      line: Type.Integer({ minimum: 1 }),
      radius: Type.Optional(Type.Integer({ minimum: 0, maximum: 30 })),
      sha256: Type.Optional(Type.String()),
      replay: Type.Optional(Type.Boolean()),
    }),
    async execute(_id, p, signal, _update, ctx) {
      const op = p.replay ? "replay" : "materialize";
      return output(compact(await bridge(rangeArgs(op, p), ctx.cwd, signal)), {
        operation: op, compatibility_alias: "tracecite_expand",
      });
    },
  });
}
