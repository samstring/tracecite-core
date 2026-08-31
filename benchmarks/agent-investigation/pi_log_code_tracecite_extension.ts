import { appendFile, mkdir } from "node:fs/promises";
import { basename, dirname, isAbsolute, relative, resolve } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import traceciteTools from "./pi_tracecite_extension_impl.ts";

const CODE_ROOT = resolve(process.env.TRACECITE_CODE_ROOT || process.cwd());
const RUNTIME_LOG = resolve(process.env.TRACECITE_RUNTIME_LOG || "");
const GUARD_PATH = process.env.TRACECITE_LOG_GUARD_ACTIVITY || "";
const ACCESS_PATH = process.env.TRACECITE_LOG_ACCESS_ACTIVITY || "";
const TRACE_LOG_TOOLS = new Set([
  "tracecite_retrieve",
  "tracecite_materialize",
  "tracecite_replay",
  "tracecite_aggregate",
  "tracecite_traverse",
  "tracecite_verify",
  "tracecite_search",
  "tracecite_expand",
]);

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

async function recordBlocked(tool: string, reason: string, input: unknown) {
  await appendJsonl(GUARD_PATH, { tool, reason, input });
}

async function recordRuntimeLogAccess(event: any, cwd: string) {
  if (!ACCESS_PATH || !TRACE_LOG_TOOLS.has(String(event?.toolName || ""))) return;
  const input = event?.input && typeof event.input === "object" ? event.input : {};
  const file = resolveInputPath((input as any).file, cwd);
  if (file !== RUNTIME_LOG) return;
  await appendJsonl(ACCESS_PATH, {
    tool: event.toolName,
    file,
    input,
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
  // The TraceCite arm runs with cwd fixed to CODE_ROOT. Prevent shell escapes to
  // sibling evidence directories while leaving arbitrary in-repository shell
  // exploration available (git grep, rg, go test, sed, awk, etc.).
  if (/(^|[\s"'=;])\.\.(?:\/|$)/.test(command)) return true;
  return false;
}

function guardReason(event: any, cwd: string): string | null {
  const input = event?.input && typeof event.input === "object" ? event.input : {};
  if (event?.toolName === "read") {
    const path = resolveInputPath((input as any).path, cwd);
    if (path && !within(CODE_ROOT, path)) {
      return "Native read is restricted to the pre-fix source tree in the TraceCite log arm; inspect the runtime log with TraceCite tools.";
    }
  }
  if (event?.toolName === "grep") {
    const path = resolveInputPath((input as any).path || ".", cwd);
    if (path && !within(CODE_ROOT, path)) {
      return "Native grep is restricted to the pre-fix source tree in the TraceCite log arm; search the runtime log with tracecite_retrieve.";
    }
  }
  if (event?.toolName === "bash") {
    const command = String((input as any).command || "");
    if (bashTouchesRuntimeLog(command)) {
      return "Native shell access to the runtime-log area is blocked in the TraceCite log arm. Shell exploration of the checked-out source tree remains unrestricted.";
    }
  }
  return null;
}

export default function logCodeTraceCite(pi: ExtensionAPI) {
  traceciteTools(pi);
  pi.on("tool_call", async (event, ctx) => {
    await recordRuntimeLogAccess(event, ctx.cwd);
    const reason = guardReason(event, ctx.cwd);
    if (!reason) return undefined;
    await recordBlocked(event.toolName, reason, event.input);
    return { block: true, reason };
  });
}
