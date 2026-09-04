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
const AUTHORIZED_EVIDENCE_FILES = (process.env.TRACECITE_EVIDENCE_FILES || "")
  .split(",")
  .map((value) => value.trim())
  .filter(Boolean);
const AUTHORIZED_EVIDENCE_HINT = AUTHORIZED_EVIDENCE_FILES.length > 0
  ? ` Host-authorized evidence files: ${AUTHORIZED_EVIDENCE_FILES.join(", ")}.`
  : "";
const TRACE_TOOLS = new Set([
  "tracecite_run",
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
  await writeFile(ACTIVITY_PATH, JSON.stringify({ schema_version: 1, summary: activitySummary(), events }, null, 2) + "\n", "utf8");
}

async function bridge(args: string[], cwd: string, signal?: AbortSignal): Promise<string> {
  try {
    const { stdout, stderr } = await execFileAsync("python", [BRIDGE, "--session", SESSION, ...args], {
      cwd, encoding: "utf8", maxBuffer: 64 * 1024 * 1024, signal,
    });
    const out = String(stdout || "").trim();
    const err = String(stderr || "").trim();
    if (out && err) return `${out}\n@STDERR ${err}`;
    return out || err || "{}";
  } catch (error: any) {
    return `@TRACECITE_ERROR ${String(error?.message || error || "bridge failed")}`;
  }
}

// Pi is a transport adapter only. TraceCite owns the evidence response schema.
// Do not compact, normalize, sample, rename, or inject fields into the payload.
function output(text: string, details: Record<string, unknown>) {
  return {
    content: [{ type: "text" as const, text }],
    details: { ...details, persistent_retrieval_session: true, evidence_only: true },
  };
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
    return { details: { ...base, tracecite_host_activity: row, tracecite_host_activity_summary: activitySummary() } } as any;
  });

  pi.registerTool({
    name: "tracecite_run",
    label: "TraceCite Evidence Shell",
    description: "Run a complete mechanical evidence-search pipeline inside TraceCite. Intermediate matches stay outside model context. The evidence token/byte budget is user/host policy and is not an Agent parameter. If status is too_broad, refine the query or scope; do not ask to increase the budget." + AUTHORIZED_EVIDENCE_HINT,
    parameters: Type.Object({
      file: Type.String({ description: "Evidence source path." + AUTHORIZED_EVIDENCE_HINT }),
      program: Type.String({ description: "Evidence Shell pipeline, e.g. search 'ERROR' | search 'route-service' or search 'status' | where statusCode == 500 | count." }),
      segmenter: Type.Optional(Type.String()),
      last: Type.Optional(Type.String()),
      since: Type.Optional(Type.String()),
      until: Type.Optional(Type.String()),
      fold: Type.Optional(Type.Boolean()),
    }),
    async execute(_id, p, signal, _update, ctx) {
      const args = ["run", p.file, p.program];
      if (p.segmenter) args.push("--segmenter", p.segmenter);
      if (p.last) args.push("--last", p.last);
      if (p.since) args.push("--since", p.since);
      if (p.until) args.push("--until", p.until);
      if (p.fold) args.push("--fold");
      return output(await bridge(args, ctx.cwd, signal), { operation: "evidence_shell", canonical_operation: true });
    },
  });

  pi.registerTool({
    name: "tracecite_retrieve",
    label: "TraceCite Retrieve",
    description: "Canonical TraceCite retrieve for caller-selected local evidence." + AUTHORIZED_EVIDENCE_HINT,
    parameters: Type.Object({
      file: Type.String({ description: "Evidence source path." + AUTHORIZED_EVIDENCE_HINT }),
      query: Type.Optional(Type.String()),
      regex: Type.Optional(Type.Boolean()),
      glob: Type.Optional(Type.String()),
      recursive: Type.Optional(Type.Boolean()),
    }),
    async execute(_id, p, signal, _update, ctx) {
      const args = ["retrieve", p.file];
      if (p.query) args.push("--query", p.query);
      if (p.regex) args.push("--regex");
      if (p.glob) args.push("--glob", p.glob);
      if (p.recursive) args.push("--recursive");
      return output(await bridge(args, ctx.cwd, signal), { operation: "retrieve", canonical_operation: true });
    },
  });

  pi.registerTool({
    name: "tracecite_materialize",
    label: "TraceCite Materialize",
    description: "Canonical TraceCite materialize of exact bounded caller-selected source context. Radius is 0..30.",
    parameters: Type.Object({
      file: Type.String({ description: "Evidence source path." + AUTHORIZED_EVIDENCE_HINT }),
      line: Type.Integer({ minimum: 1 }),
      radius: Type.Optional(Type.Integer({ minimum: 0, maximum: 30 })),
      sha256: Type.Optional(Type.String()),
    }),
    async execute(_id, p, signal, _update, ctx) {
      return output(await bridge(rangeArgs("materialize", p), ctx.cwd, signal), { operation: "materialize", canonical_operation: true });
    },
  });

  pi.registerTool({
    name: "tracecite_replay",
    label: "TraceCite Replay",
    description: "Canonical TraceCite replay of previously materialized immutable context. Radius is 0..30.",
    parameters: Type.Object({
      file: Type.String({ description: "Evidence source path." + AUTHORIZED_EVIDENCE_HINT }),
      line: Type.Integer({ minimum: 1 }),
      radius: Type.Optional(Type.Integer({ minimum: 0, maximum: 30 })),
      sha256: Type.String(),
    }),
    async execute(_id, p, signal, _update, ctx) {
      return output(await bridge(rangeArgs("replay", p), ctx.cwd, signal), { operation: "replay", canonical_operation: true });
    },
  });

  pi.registerTool({
    name: "tracecite_aggregate",
    label: "TraceCite Aggregate",
    description: "Canonical TraceCite deterministic count/distinct/group over caller-selected local text matches.",
    parameters: Type.Object({
      file: Type.String(),
      query: Type.String(),
      regex: Type.Optional(Type.Boolean()),
      operation: Type.Optional(Type.Union([Type.Literal("count"), Type.Literal("distinct"), Type.Literal("group")])),
      group_regex: Type.Optional(Type.String()),
      max_groups: Type.Optional(Type.Integer({ minimum: 1, maximum: 500 })),
    }),
    async execute(_id, p, signal, _update, ctx) {
      const args = ["aggregate", p.file, p.query, "--operation", p.operation ?? "count", "--max-groups", String(p.max_groups ?? 100)];
      if (p.regex) args.push("--regex");
      if (p.group_regex) args.push("--group-regex", p.group_regex);
      return output(await bridge(args, ctx.cwd, signal), { operation: "aggregate", canonical_operation: true });
    },
  });

  pi.registerTool({
    name: "tracecite_traverse",
    label: "TraceCite Traverse",
    description: "Canonical TraceCite bounded provider traversal over caller-selected evidence IDs/entities.",
    parameters: Type.Object({
      provider_file: Type.String(),
      seed_evidence_ids: Type.Optional(Type.Array(Type.String(), { maxItems: 50 })),
      seed_entities: Type.Optional(Type.Array(Type.Object({
        kind: Type.String(),
        value: Type.String(),
        namespace: Type.Optional(Type.String()),
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
      return output(await bridge(args, ctx.cwd, signal), { operation: "traverse", canonical_operation: true });
    },
  });

  pi.registerTool({
    name: "tracecite_verify",
    label: "TraceCite Verify",
    description: "Canonical TraceCite mechanical evidence-manifest integrity verification.",
    parameters: Type.Object({ manifest: Type.String() }),
    async execute(_id, p, signal, _update, ctx) {
      return output(await bridge(["verify", p.manifest], ctx.cwd, signal), { operation: "verify", canonical_operation: true });
    },
  });

  // Compatibility aliases. They use the same transparent TraceCite transport.
  pi.registerTool({
    name: "tracecite_search",
    label: "TraceCite Search (compat)",
    description: "Compatibility alias for tracecite_retrieve.",
    parameters: Type.Object({
      file: Type.String(),
      query: Type.String(),
      regex: Type.Optional(Type.Boolean()),
    }),
    async execute(_id, p, signal, _update, ctx) {
      const args = ["retrieve", p.file, "--query", p.query];
      if (p.regex) args.push("--regex");
      return output(await bridge(args, ctx.cwd, signal), { operation: "retrieve", compatibility_alias: "tracecite_search" });
    },
  });

  pi.registerTool({
    name: "tracecite_expand",
    label: "TraceCite Expand (compat)",
    description: "Compatibility alias for tracecite_materialize/replay.",
    parameters: Type.Object({
      file: Type.String({ description: "Evidence source path." + AUTHORIZED_EVIDENCE_HINT }),
      line: Type.Integer({ minimum: 1 }),
      radius: Type.Optional(Type.Integer({ minimum: 0, maximum: 30 })),
      sha256: Type.Optional(Type.String()),
      replay: Type.Optional(Type.Boolean()),
    }),
    async execute(_id, p, signal, _update, ctx) {
      const op = p.replay ? "replay" : "materialize";
      return output(await bridge(rangeArgs(op, p), ctx.cwd, signal), { operation: op, compatibility_alias: "tracecite_expand" });
    },
  });
}
