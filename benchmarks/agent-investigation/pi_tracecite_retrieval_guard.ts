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
let consecutiveNoGrowth = 0;

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

async function record(payload: Record<string, unknown>) {
  if (!ACTIVITY_PATH) return;
  await mkdir(dirname(ACTIVITY_PATH), { recursive: true });
  await appendFile(ACTIVITY_PATH, JSON.stringify(payload) + "\n", "utf8");
}

type Progress = {
  status?: string;
  consecutive_no_growth?: number;
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
      consecutive_no_growth: Number.isFinite(Number(progress?.consecutive_no_growth))
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

function observeProgress(progress: Progress | undefined, isError: boolean) {
  if (progress?.consecutive_no_growth !== undefined) {
    consecutiveNoGrowth = progress.consecutive_no_growth;
    return;
  }

  const delta = progress?.delta;
  const grew = delta?.grew === true || Number(delta?.new_evidence || 0) > 0 || Number(delta?.new_lines || 0) > 0;
  if (grew) {
    consecutiveNoGrowth = 0;
    return;
  }

  const explicitNoGrowth = delta?.grew === false ||
    (delta?.new_evidence === 0 && delta?.new_lines === 0);
  if (explicitNoGrowth || isError || progress?.status === "error") {
    consecutiveNoGrowth += 1;
  }
}

export default function traceciteRetrievalGuard(pi: ExtensionAPI) {
  if (!enabled()) return;

  pi.on("agent_start", async () => {
    retrievals = 0;
    consecutiveNoGrowth = 0;
    await record({
      event: "agent_start",
      no_growth_patience: NO_GROWTH_PATIENCE,
      max_retrievals: MAX_RETRIEVALS,
    });
  });

  pi.on("tool_call", async (event) => {
    if (!isAcquisition(event)) return undefined;

    if (MAX_RETRIEVALS > 0 && retrievals >= MAX_RETRIEVALS) {
      await record({
        event: "tool_call",
        tool: event.toolName,
        decision: "block",
        reason: "max_retrievals",
        retrievals,
        consecutive_no_growth: consecutiveNoGrowth,
      });
      return {
        block: true,
        reason: `TraceCite retrieval guard: the ${MAX_RETRIEVALS}-call evidence-acquisition limit has been reached. Do not retry TraceCite. Use the evidence already acquired and produce the final answer.`,
      } as any;
    }

    if (NO_GROWTH_PATIENCE > 0 && consecutiveNoGrowth >= NO_GROWTH_PATIENCE) {
      await record({
        event: "tool_call",
        tool: event.toolName,
        decision: "block",
        reason: "consecutive_no_growth",
        retrievals,
        consecutive_no_growth: consecutiveNoGrowth,
      });
      return {
        block: true,
        reason: `TraceCite retrieval guard: ${consecutiveNoGrowth} consecutive evidence acquisitions added no new evidence. Do not retry TraceCite with a reformulated query. Use the evidence already acquired and produce the final answer.`,
      } as any;
    }

    retrievals += 1;
    await record({
      event: "tool_call",
      tool: event.toolName,
      decision: "allow",
      retrievals,
      consecutive_no_growth: consecutiveNoGrowth,
    });
    return undefined;
  });

  pi.on("tool_result", async (event) => {
    if (!isAcquisition(event)) return undefined;
    const progress = progressFromContent(event.content);
    observeProgress(progress, Boolean(event.isError));
    await record({
      event: "tool_result",
      tool: event.toolName,
      retrievals,
      consecutive_no_growth: consecutiveNoGrowth,
      progress,
      is_error: Boolean(event.isError),
    });
    return undefined;
  });

  pi.on("agent_end", async () => {
    await record({
      event: "agent_end",
      retrievals,
      consecutive_no_growth: consecutiveNoGrowth,
    });
  });
}
