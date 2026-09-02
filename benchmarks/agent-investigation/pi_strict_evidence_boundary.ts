import { appendFile, mkdir } from "node:fs/promises";
import { basename, dirname, isAbsolute, relative, resolve } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

// Shared TraceCite evidence guard.
//
// Benchmark mode forces the guard on for the whole benchmark arm.
// Product mode is normally off, and is activated for the current agent turn only
// when the user explicitly asks to use TraceCite/trace.
const BENCHMARK_MODE = String(process.env.TRACECITE_BENCHMARK_MODE || "").trim().toLowerCase();
const PRODUCT_MODE = String(process.env.TRACECITE_MODE || "").trim().toLowerCase();
const EVIDENCE_ROOT_RAW = String(
  process.env.TRACECITE_EVIDENCE_ROOT || process.env.TRACECITE_RUNTIME_EVIDENCE_ROOT || "",
).trim();
const EVIDENCE_ROOT = EVIDENCE_ROOT_RAW ? resolve(EVIDENCE_ROOT_RAW) : "";
const TRACE_ACCESS_PATH = String(process.env.TRACECITE_LOG_ACCESS_ACTIVITY || "").trim();
const BLOCKED_NATIVE_EVIDENCE_PATH = String(process.env.TRACECITE_BLOCKED_NATIVE_EVIDENCE_ACTIVITY || "").trim();
const EVIDENCE_BASENAMES = new Set(
  String(process.env.TRACECITE_EVIDENCE_FILES || process.env.TRACECITE_RUNTIME_EVIDENCE_FILES || "")
    .split(",")
    .map((value) => basename(value.trim()))
    .filter(Boolean),
);

const configuredEvidenceCallLimit = Number(
  String(process.env.TRACECITE_MAX_EVIDENCE_CALLS || "16").trim(),
);
const TRACE_EVIDENCE_CALL_LIMIT = Number.isFinite(configuredEvidenceCallLimit)
  ? Math.max(1, Math.min(1000, Math.floor(configuredEvidenceCallLimit)))
  : 16;

const TRACE_TOOLS = new Set([
  "tracecite_retrieve",
  "tracecite_materialize",
  "tracecite_replay",
  "tracecite_aggregate",
  "tracecite_traverse",
  "tracecite_verify",
  "tracecite_search",
  "tracecite_expand",
]);
const NATIVE_PATH_TOOLS = new Set(["read", "grep", "find", "ls"]);

type NativeEvidenceAccess = {
  channel: "native";
  tool: string;
  evidence_root: string;
  input: unknown;
  path?: string;
  match?: string;
  heuristic?: boolean;
};

function within(root: string, candidate: string): boolean {
  if (!root) return false;
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
  const tool = String(event?.toolName || "");
  if ([
    "tracecite_retrieve",
    "tracecite_materialize",
    "tracecite_replay",
    "tracecite_aggregate",
    "tracecite_search",
    "tracecite_expand",
  ].includes(tool)) {
    return [(input as any).file];
  }
  if (tool === "tracecite_traverse") return [(input as any).provider_file];
  if (tool === "tracecite_verify") return [(input as any).manifest];
  return [];
}

async function recordTraceCiteRuntimeAccess(event: any, cwd: string, modeActive: boolean) {
  if (!modeActive || !TRACE_ACCESS_PATH || !TRACE_TOOLS.has(String(event?.toolName || ""))) {
    return;
  }
  const resolved = traceSourceCandidates(event)
    .map((value) => resolveInputPath(value, cwd))
    .filter((value): value is string => Boolean(value));
  if (!resolved.some((value) => within(EVIDENCE_ROOT, value))) return;
  await appendJsonl(TRACE_ACCESS_PATH, {
    channel: "tracecite",
    tool: event.toolName,
    evidence_root: EVIDENCE_ROOT,
    input: event.input,
  });
}

function bashEvidenceReference(command: string, cwd: string): string | null {
  if (!EVIDENCE_ROOT || !command.trim()) return null;
  if (within(EVIDENCE_ROOT, resolve(cwd))) return "cwd_inside_evidence_root";

  const normalized = command.replaceAll("\\", "/");
  const evidenceRoot = EVIDENCE_ROOT.replaceAll("\\", "/");
  if (evidenceRoot && normalized.includes(evidenceRoot)) return "evidence_root_path";
  if (/\bTRACECITE_(?:RUNTIME_)?EVIDENCE_(ROOT|FILES)\b/.test(command)) return "evidence_env";
  for (const name of EVIDENCE_BASENAMES) {
    if (name && normalized.includes(name.replaceAll("\\", "/"))) return `evidence_file:${name}`;
  }
  return null;
}

function detectNativeRuntimeAccess(event: any, cwd: string): NativeEvidenceAccess | null {
  const tool = String(event?.toolName || "");
  const input = event?.input && typeof event.input === "object" ? event.input : {};

  if (NATIVE_PATH_TOOLS.has(tool)) {
    const raw = (input as any).path || (tool === "read" ? undefined : ".");
    const path = resolveInputPath(raw, cwd);
    if (path && within(EVIDENCE_ROOT, path)) {
      return {
        channel: "native",
        tool,
        path,
        evidence_root: EVIDENCE_ROOT,
        input: event.input,
      };
    }
    return null;
  }

  if (tool === "bash") {
    const command = String((input as any).command || "");
    const match = bashEvidenceReference(command, cwd);
    if (match) {
      return {
        channel: "native",
        tool,
        match,
        evidence_root: EVIDENCE_ROOT,
        input: event.input,
        heuristic: true,
      };
    }
  }
  return null;
}

function forcedTraceciteMode(): boolean {
  return BENCHMARK_MODE === "tracecite" || PRODUCT_MODE === "tracecite";
}

export function explicitlyRequestsTracecite(text: string): boolean {
  const normalized = String(text || "").normalize("NFKC").trim().toLowerCase();
  if (!normalized) return false;

  const explicitNegative =
    /(?:不要|别|不用|无需)\s*(?:使用|用)?\s*(?:tracecite|trace)(?=$|\s|[，。,:：；;]|[\u4e00-\u9fff])/i.test(normalized) ||
    /\b(?:do not|don't|dont|without)\s+(?:use\s+)?(?:tracecite|trace)\b/i.test(normalized);
  if (explicitNegative) return false;

  return (
    /^\/trace(?:cite)?(?:\s|$)/i.test(normalized) ||
    /^tracecite(?:\s|[:：,，-]|$)/i.test(normalized) ||
    /(?:用|使用)\s*(?:tracecite|trace)(?=$|\s|[，。,:：；;]|[\u4e00-\u9fff])/i.test(normalized) ||
    /\b(?:use|using)\s+(?:tracecite|trace)\b/i.test(normalized)
  );
}

export default function traceciteEvidenceGuard(pi: ExtensionAPI) {
  let promptTraceciteMode = false;
  let traceEvidenceCalls = 0;
  const modeActive = () => forcedTraceciteMode() || promptTraceciteMode;

  // Product activation: a user turn that explicitly requests TraceCite enables the
  // evidence guard for that agent run. A normal turn remains unrestricted.
  pi.on("input", async (event) => {
    if (!forcedTraceciteMode() && event.source !== "extension") {
      promptTraceciteMode = explicitlyRequestsTracecite(event.text);
      traceEvidenceCalls = 0;
    }
    return { action: "continue" } as any;
  });

  pi.on("tool_call", async (event, ctx) => {
    if (!modeActive() || !EVIDENCE_ROOT) return undefined;

    const tool = String(event?.toolName || "");
    if (TRACE_TOOLS.has(tool)) {
      // Mechanical transport guard only. This does not inspect claims, hypotheses,
      // evidence meaning, or diagnostic sufficiency. It simply bounds evidence I/O.
      if (traceEvidenceCalls >= TRACE_EVIDENCE_CALL_LIMIT) {
        return {
          block: true,
          reason: `TraceCite evidence transport limit reached (${TRACE_EVIDENCE_CALL_LIMIT}). Do not request more evidence; answer from the evidence already retrieved.`,
        } as any;
      }
      // Increment before the first await so concurrently emitted tool calls cannot
      // race past the transport ceiling in a single model turn.
      traceEvidenceCalls += 1;
      await recordTraceCiteRuntimeAccess(event, ctx.cwd, true);
      return undefined;
    }

    const nativeAccess = detectNativeRuntimeAccess(event, ctx.cwd);
    if (!nativeAccess) return undefined;

    await appendJsonl(BLOCKED_NATIVE_EVIDENCE_PATH, {
      ...nativeAccess,
      status: "blocked_before_execution",
      mode: BENCHMARK_MODE === "tracecite" ? "benchmark" : "tracecite",
    });

    const reason = BENCHMARK_MODE === "tracecite"
      ? "Strict TraceCite benchmark rule: direct native access to runtime evidence is blocked before execution. Use TraceCite tools for all supplied evidence content. Native tools may only be used outside the evidence root."
      : "TraceCite mode is active: direct native access to protected evidence is blocked before execution. Use TraceCite MCP/tools for evidence content. Native tools remain available outside the evidence root.";

    return {
      block: true,
      reason,
    } as any;
  });

  // A prompt-triggered product mode is scoped to one completed agent run. Forced
  // env modes remain active until the host process exits. The transport count is
  // per agent run in both modes.
  pi.on("agent_end", async () => {
    traceEvidenceCalls = 0;
    if (!forcedTraceciteMode()) promptTraceciteMode = false;
  });
}
