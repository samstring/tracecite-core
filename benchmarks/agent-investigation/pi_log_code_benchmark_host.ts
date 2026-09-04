import { appendFile, mkdir, writeFile } from "node:fs/promises";
import { basename, dirname, isAbsolute, relative, resolve } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const RUNTIME_LOG = resolve(process.env.TRACECITE_RUNTIME_LOG || "");
const EVIDENCE_ROOT = resolve(process.env.TRACECITE_RUNTIME_EVIDENCE_ROOT || dirname(RUNTIME_LOG || "."));
const ACCESS_PATH = process.env.TRACECITE_LOG_ACCESS_ACTIVITY || "";
const NATIVE_EVIDENCE_PATH = process.env.TRACECITE_NATIVE_EVIDENCE_ACTIVITY || "";
const BLOCKED_NATIVE_EVIDENCE_PATH = process.env.TRACECITE_BLOCKED_NATIVE_EVIDENCE_ACTIVITY || "";
const ACTIVITY_PATH = process.env.TRACECITE_HOST_ACTIVITY || "";
// Benchmark-only enforcement. TraceCite MCP/Skill product behavior is unchanged.
const BENCHMARK_MODE = String(process.env.TRACECITE_BENCHMARK_MODE || "").trim();

const TRACE_TOOLS = new Set([
  "tracecite_run",
  "tracecite_retrieve",
  "tracecite_materialize",
  "tracecite_replay",
  "tracecite_aggregate",
  "tracecite_traverse",
  "tracecite_verify",
]);

const NATIVE_PATH_TOOLS = new Set(["read", "grep", "find", "ls"]);

type Category =
  | "tracecite_evidence"
  | "native_search"
  | "native_read"
  | "opaque_shell"
  | "native_other"
  | "other";

type Activity = {
  tool: string;
  category: Category;
  duration_ms: number;
  status: string;
  metadata?: Record<string, unknown>;
};

type NativeEvidenceAccess = {
  channel: "native";
  tool: string;
  runtime_log: string;
  input: unknown;
  path?: string;
  match?: string;
  heuristic?: boolean;
};

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
  return {
    total_tool_calls: events.length,
    categories,
    tools,
    observed_duration_ms,
  };
}

async function persistActivity() {
  if (!ACTIVITY_PATH) return;
  await mkdir(dirname(ACTIVITY_PATH), { recursive: true });
  await writeFile(
    ACTIVITY_PATH,
    JSON.stringify({ schema_version: 2, summary: activitySummary(), events }, null, 2) + "\n",
    "utf8",
  );
}

function within(root: string, candidate: string): boolean {
  const rel = relative(root, candidate);
  return rel === "" || (!rel.startsWith("..") && !isAbsolute(rel));
}

function resolveInputPath(raw: unknown, cwd: string): string | null {
  const value = String(raw || "").trim();
  if (!value) return null;
  return resolve(cwd, value);
}

async function appendJsonl(path: string, payload: unknown) {
  if (!path) return;
  await mkdir(dirname(path), { recursive: true });
  await appendFile(path, JSON.stringify(payload) + "\n", "utf8");
}

function traceSourceCandidates(event: any): unknown[] {
  const input = event?.input && typeof event.input === "object" ? event.input : {};
  switch (String(event?.toolName || "")) {
    case "tracecite_run":
      return [(input as any)?.source];
    case "tracecite_retrieve":
      return [(input as any)?.target?.source];
    case "tracecite_materialize":
    case "tracecite_replay":
    case "tracecite_aggregate":
      return [(input as any)?.source];
    case "tracecite_verify":
      return [(input as any)?.manifest_path];
    default:
      return [];
  }
}

async function recordTraceCiteRuntimeAccess(event: any, cwd: string) {
  if (!ACCESS_PATH || !TRACE_TOOLS.has(String(event?.toolName || ""))) return;
  const resolved = traceSourceCandidates(event)
    .map((value) => resolveInputPath(value, cwd))
    .filter((value): value is string => Boolean(value));
  if (!resolved.some((value) => value === RUNTIME_LOG || within(EVIDENCE_ROOT, value))) return;
  await appendJsonl(ACCESS_PATH, {
    channel: "tracecite_mcp",
    tool: event.toolName,
    source: RUNTIME_LOG,
    input: event.input,
  });
}

function bashEvidenceReference(command: string): string | null {
  if (!command.trim()) return null;
  const normalized = command.replaceAll("\\", "/");
  const logPath = RUNTIME_LOG.replaceAll("\\", "/");
  const evidenceRoot = EVIDENCE_ROOT.replaceAll("\\", "/");
  const logName = basename(RUNTIME_LOG);
  if (logPath && normalized.includes(logPath)) return "runtime_log_path";
  if (evidenceRoot && normalized.includes(evidenceRoot)) return "evidence_root_path";
  if (logName && normalized.includes(logName)) return "runtime_log_name";
  if (/\bTRACECITE_RUNTIME_LOG\b/.test(command)) return "runtime_log_env";
  return null;
}

function detectNativeRuntimeAccess(event: any, cwd: string): NativeEvidenceAccess | null {
  const tool = String(event?.toolName || "");
  const input = event?.input && typeof event.input === "object" ? event.input : {};

  if (NATIVE_PATH_TOOLS.has(tool)) {
    const raw = (input as any).path || (tool === "read" ? undefined : ".");
    const path = resolveInputPath(raw, cwd);
    if (path && (path === RUNTIME_LOG || within(EVIDENCE_ROOT, path))) {
      return {
        channel: "native",
        tool,
        path,
        runtime_log: RUNTIME_LOG,
        input: event.input,
      };
    }
    return null;
  }

  if (tool === "bash") {
    const command = String((input as any).command || "");
    const match = bashEvidenceReference(command);
    if (match) {
      return {
        channel: "native",
        tool,
        match,
        runtime_log: RUNTIME_LOG,
        input: event.input,
        heuristic: true,
      };
    }
  }
  return null;
}

export default function benchmarkHost(pi: ExtensionAPI) {
  pi.on("tool_call", async (event, ctx) => {
    starts.set(event.toolCallId, Date.now());
    await recordTraceCiteRuntimeAccess(event, ctx.cwd);

    const nativeAccess = detectNativeRuntimeAccess(event, ctx.cwd);
    if (!nativeAccess) return undefined;

    if (BENCHMARK_MODE === "tracecite") {
      await appendJsonl(BLOCKED_NATIVE_EVIDENCE_PATH, {
        ...nativeAccess,
        status: "blocked_before_execution",
      });
      return {
        block: true,
        reason:
          "TraceCite benchmark rule: direct native access to runtime evidence is blocked. " +
          "Use TraceCite MCP tools for runtime-log evidence. Native tools remain available for source-code exploration.",
      } as any;
    }

    await appendJsonl(NATIVE_EVIDENCE_PATH, nativeAccess);
    return undefined;
  });

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
    const base =
      event.details && typeof event.details === "object" && !Array.isArray(event.details)
        ? (event.details as Record<string, unknown>)
        : {};
    return {
      details: {
        ...base,
        tracecite_host_activity: row,
        tracecite_host_activity_summary: activitySummary(),
      },
    } as any;
  });
}