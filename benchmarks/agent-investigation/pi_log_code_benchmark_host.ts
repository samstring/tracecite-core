import { appendFile, mkdir, writeFile } from "node:fs/promises";
import { basename, delimiter, dirname, isAbsolute, relative, resolve } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const CODE_ROOT = resolve(process.env.TRACECITE_CODE_ROOT || process.cwd());
const RUNTIME_LOG = resolve(process.env.TRACECITE_RUNTIME_LOG || "");
const AGENT_RESOURCE_ROOTS = String(process.env.TRACECITE_AGENT_RESOURCE_ROOTS || "")
  .split(delimiter)
  .map((value) => value.trim())
  .filter(Boolean)
  .map((value) => resolve(value));
const GUARD_PATH = process.env.TRACECITE_LOG_GUARD_ACTIVITY || "";
const ACCESS_PATH = process.env.TRACECITE_LOG_ACCESS_ACTIVITY || "";
const ACTIVITY_PATH = process.env.TRACECITE_HOST_ACTIVITY || "";

const TRACE_TOOLS = new Set([
  "tracecite_retrieve",
  "tracecite_materialize",
  "tracecite_replay",
  "tracecite_aggregate",
  "tracecite_traverse",
  "tracecite_verify",
]);

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
    JSON.stringify({ schema_version: 1, summary: activitySummary(), events }, null, 2) + "\n",
    "utf8",
  );
}

function within(root: string, candidate: string): boolean {
  const rel = relative(root, candidate);
  return rel === "" || (!rel.startsWith("..") && !isAbsolute(rel));
}

function withinNativeResource(candidate: string): boolean {
  if (within(CODE_ROOT, candidate)) return true;
  return AGENT_RESOURCE_ROOTS.some((root) => within(root, candidate));
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

async function recordBlocked(tool: string, reason: string, input: unknown) {
  await appendJsonl(GUARD_PATH, { tool, reason, input });
}

function traceSourceCandidates(event: any): unknown[] {
  const input = event?.input && typeof event.input === "object" ? event.input : {};
  switch (String(event?.toolName || "")) {
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

async function recordRuntimeLogAccess(event: any, cwd: string) {
  if (!ACCESS_PATH || !TRACE_TOOLS.has(String(event?.toolName || ""))) return;
  const resolved = traceSourceCandidates(event)
    .map((value) => resolveInputPath(value, cwd))
    .filter((value): value is string => Boolean(value));
  if (!resolved.includes(RUNTIME_LOG)) return;
  await appendJsonl(ACCESS_PATH, {
    tool: event.toolName,
    source: RUNTIME_LOG,
    input: event.input,
  });
}

function bashTouchesRuntimeLog(command: string): boolean {
  if (!command.trim()) return false;
  const normalized = command.replaceAll("\\", "/");
  const logPath = RUNTIME_LOG.replaceAll("\\", "/");
  const logDir = dirname(RUNTIME_LOG).replaceAll("\\", "/");
  const logName = basename(RUNTIME_LOG);
  if (logPath && normalized.includes(logPath)) return true;
  if (logDir && normalized.includes(logDir)) return true;
  if (logName && normalized.includes(logName)) return true;
  if (/\bTRACECITE_RUNTIME_LOG\b/.test(command)) return true;
  if (/(^|[\s"'=;])\.\.(?:\/|$)/.test(command)) return true;
  return false;
}

function guardReason(event: any, cwd: string): string | null {
  const input = event?.input && typeof event.input === "object" ? event.input : {};
  if (event?.toolName === "read") {
    const path = resolveInputPath((input as any).path, cwd);
    if (path && !withinNativeResource(path)) {
      return "Native read is restricted to the pre-fix source tree and explicitly declared Agent resource roots in the TraceCite arm; inspect runtime evidence through TraceCite MCP.";
    }
  }
  if (event?.toolName === "grep") {
    const path = resolveInputPath((input as any).path || ".", cwd);
    if (path && !withinNativeResource(path)) {
      return "Native grep is restricted to the pre-fix source tree and explicitly declared Agent resource roots in the TraceCite arm; search runtime evidence through TraceCite MCP.";
    }
  }
  if (event?.toolName === "bash") {
    const command = String((input as any).command || "");
    if (bashTouchesRuntimeLog(command)) {
      return "Native shell access to the runtime-log area is blocked in the TraceCite arm. Shell exploration of the checked-out source tree and declared Agent resources remains available.";
    }
  }
  return null;
}

export default function benchmarkHost(pi: ExtensionAPI) {
  pi.on("tool_call", async (event, ctx) => {
    starts.set(event.toolCallId, Date.now());
    await recordRuntimeLogAccess(event, ctx.cwd);
    const reason = guardReason(event, ctx.cwd);
    if (!reason) return undefined;
    starts.delete(event.toolCallId);
    await recordBlocked(event.toolName, reason, event.input);
    return { block: true, reason };
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
