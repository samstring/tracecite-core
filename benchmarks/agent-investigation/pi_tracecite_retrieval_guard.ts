import { appendFile, mkdir } from "node:fs/promises";
import { dirname } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

// Optional host-side safety valve for runaway evidence acquisition.
// It is disabled unless one of the env limits is set. The guard is deliberately
// mechanical: it only observes retrieval count and TraceCite's own novelty/progress
// metadata. It does not know hypotheses, causal sufficiency, or investigation claims.
const NO_GROWTH_PATIENCE = positiveInt(process.env.TRACECITE_NO_GROWTH_PATIENCE);
const MAX_RETRIEVALS = positiveInt(process.env.TRACECITE_MAX_RETRIEVALS);
const ACTIVITY_PATH = String(process.env.TRACECITE_RETRIEVAL_GUARD_ACTIVITY || "").trim();

const ACQUISITION_TOOLS = new Set([
  "tracecite_retrieve",
  "tracecite_materialize",
  "tracecite_search",
  "tracecite_expand",
]);

let retrievals = 0;
const noGrowthBySignature = new Map<string, number>();

function positiveInt(value: unknown): number {
  const parsed = Number.parseInt(String(value || "0"), 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
}

function enabled(): boolean {
  return NO_GROWTH_PATIENCE > 0 || MAX_RETRIEVALS > 0;
}

function isAcquisition(event: any): boolean {
  const tool = String(event?.toolName || "");
  if (!ACQUISITION_TOOLS.has(tool)) return false;
  if (tool === "tracecite_expand" && Boolean(event?.input?.replay)) return false;
  return true;
}

function signature(event: any): string {
  const tool = String(event?.toolName || "");
  const input = event?.input && typeof event.input === "object" ? event.input : {};
  if (tool === "tracecite_search" || tool === "tracecite_retrieve") {
    return JSON.stringify([
      "retrieve",
      String((input as any).file || ""),
      String((input as any).query || ""),
      Boolean((input as any).regex),
    ]);
  }
  return JSON.stringify([
    "materialize",
    String((input as any).file || ""),
    Number((input as any).line || 0),
    Number((input as any).radius ?? 8),
  ]);
}

async function record(payload: Record<string, unknown>) {
  if (!ACTIVITY_PATH) return;
  await mkdir(dirname(ACTIVITY_PATH), { recursive: true });
  await appendFile(ACTIVITY_PATH, JSON.stringify(payload) + "\n", "utf8");
}

type Progress = {
  status?: string;
  session_consecutive_no_growth?: number;
  delta?: {
    new_evidence?: number;
    new_lines?: number;
    grew?: boolean;
  };
};

function progressFromContent(content: any): Progress | undefined {
  if (!Array.isArray(content)) return undefined;
  for (const item of content) {
    if (String(item?.type || "") !== "text") continue;
    let parsed: any;
    try {
      parsed = JSON.parse(String(item?.text || ""));
    } catch {
      continue;
    }
    if (!parsed || typeof parsed !== "object") continue;
    const progress = parsed.progress && typeof parsed.progress === "object"
      ? parsed.progress
      : undefined;
    return {
      status: parsed.status === undefined ? undefined : String(parsed.status),
      session_consecutive_no_growth: Number.isFinite(Number(progress?.consecutive_no_growth))
        ? Math.max(0, Number(progress.consecutive_no_growth))
        : undefined,
      delta: progress?.delta && typeof progress.delta === "object"
        ? {
            new_evidence: Number.isFinite(Number(progress.delta.new_evidence))
              ? Number(progress.delta.new_evidence)
              : undefined,
            new_lines: Number.isFinite(Number(progress.delta.new_lines))
              ? Number(progress.delta.new_lines)
              : undefined,
            grew: typeof progress.delta.grew === "boolean" ? progress.delta.grew : undefined,
          }
        : undefined,
    };
  }
  return undefined;
}

function observeProgress(key: string, progress: Progress | undefined, isError: boolean): number {
  const previous = noGrowthBySignature.get(key) || 0;
  const delta = progress?.delta;
  const grew = delta?.grew === true || Number(delta?.new_evidence || 0) > 0 || Number(delta?.new_lines || 0) > 0;
  if (grew) {
    noGrowthBySignature.set(key, 0);
    return 0;
  }

  const explicitNoGrowth = delta?.grew === false ||
    (delta?.new_evidence === 0 && delta?.new_lines === 0);
  if (explicitNoGrowth || isError || progress?.status === "error" || progress?.status === "no_match" || progress?.status === "no_new_evidence") {
    const next = previous + 1;
    noGrowthBySignature.set(key, next);
    return next;
  }
  return previous;
}

export default function traceciteRetrievalGuard(pi: ExtensionAPI) {
  if (!enabled()) return;

  pi.on("agent_start", async () => {
    retrievals = 0;
    noGrowthBySignature.clear();
    await record({
      event: "agent_start",
      no_growth_patience: NO_GROWTH_PATIENCE,
      max_retrievals: MAX_RETRIEVALS,
    });
  });

  pi.on("tool_call", async (event) => {
    if (!isAcquisition(event)) return undefined;
    const key = signature(event);
    const noGrowth = noGrowthBySignature.get(key) || 0;

    if (MAX_RETRIEVALS > 0 && retrievals >= MAX_RETRIEVALS) {
      await record({
        event: "tool_call",
        tool: event.toolName,
        decision: "block",
        reason: "max_retrievals",
        retrievals,
        signature_no_growth: noGrowth,
      });
      return {
        block: true,
        reason: `TraceCite retrieval guard: the ${MAX_RETRIEVALS}-call evidence-acquisition limit has been reached. Do not retry TraceCite. Use the evidence already acquired and produce the final answer.`,
      } as any;
    }

    if (NO_GROWTH_PATIENCE > 0 && noGrowth >= NO_GROWTH_PATIENCE) {
      await record({
        event: "tool_call",
        tool: event.toolName,
        decision: "block",
        reason: "repeated_signature_no_growth",
        retrievals,
        signature_no_growth: noGrowth,
      });
      return {
        block: true,
        reason: `TraceCite retrieval guard: this same evidence request has already produced no new evidence ${noGrowth} times. Do not retry it. Use existing evidence, choose a materially different unresolved evidence need, or produce the final answer.`,
      } as any;
    }

    retrievals += 1;
    await record({
      event: "tool_call",
      tool: event.toolName,
      decision: "allow",
      retrievals,
      signature_no_growth: noGrowth,
    });
    return undefined;
  });

  pi.on("tool_result", async (event) => {
    if (!isAcquisition(event)) return undefined;
    const key = signature(event);
    const progress = progressFromContent(event.content);
    const noGrowth = observeProgress(key, progress, Boolean(event.isError));
    await record({
      event: "tool_result",
      tool: event.toolName,
      retrievals,
      signature_no_growth: noGrowth,
      progress,
      is_error: Boolean(event.isError),
    });
    return undefined;
  });

  pi.on("agent_end", async () => {
    await record({
      event: "agent_end",
      retrievals,
      tracked_signatures: noGrowthBySignature.size,
    });
  });
}
