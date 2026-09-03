import { appendFile, mkdir } from "node:fs/promises";
import { dirname } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

// Optional host-side safety valve for runaway evidence acquisition.
// It is disabled unless one of the env limits is set. The guard is deliberately
// mechanical: it observes retrieval count, immutable coverage, and TraceCite's own
// novelty/progress metadata. It does not know hypotheses, causal sufficiency, or
// investigation claims.
const NO_GROWTH_PATIENCE = positiveInt(process.env.TRACECITE_NO_GROWTH_PATIENCE);
const MAX_RETRIEVALS = positiveInt(process.env.TRACECITE_MAX_RETRIEVALS);
const ACTIVITY_PATH = String(process.env.TRACECITE_RETRIEVAL_GUARD_ACTIVITY || "").trim();

const ACQUISITION_TOOLS = new Set([
  "tracecite_retrieve",
  "tracecite_materialize",
  "tracecite_search",
  "tracecite_expand",
]);

type LineRange = { start: number; end: number };
type CallMeta = {
  key: string;
  tool: string;
  file?: string;
  requested_range?: LineRange;
};

type Progress = {
  status?: string;
  session_consecutive_no_growth?: number;
  matched_existing_evidence?: number;
  coverage?: {
    context_start_line?: number;
    context_end_line?: number;
  };
  delta?: {
    new_evidence?: number;
    new_lines?: number;
    grew?: boolean;
  };
};

// Module lifetime is the investigation lifetime for the Pi CLI integration. Pi may emit
// multiple agent_start/agent_end pairs while automatically retrying one investigation
// (for example after a provider 429). These counters therefore MUST NOT reset on
// agent_start; a provider retry must not mint a fresh evidence-acquisition budget.
let retrievals = 0;
const noGrowthBySignature = new Map<string, number>();
const coveredRangesByFile = new Map<string, LineRange[]>();
const pendingCalls = new Map<string, CallMeta>();

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

function callMeta(event: any): CallMeta {
  const tool = String(event?.toolName || "");
  const input = event?.input && typeof event.input === "object" ? event.input : {};
  const file = String((input as any).file || "").trim() || undefined;
  let requested_range: LineRange | undefined;
  if ((tool === "tracecite_materialize" || tool === "tracecite_expand") && file) {
    const line = Number((input as any).line || 0);
    const radius = Math.max(0, Number((input as any).radius ?? 8));
    if (Number.isFinite(line) && line > 0 && Number.isFinite(radius)) {
      requested_range = {
        start: Math.max(1, Math.floor(line - radius)),
        end: Math.max(1, Math.floor(line + radius)),
      };
    }
  }
  return { key: signature(event), tool, file, requested_range };
}

function rangeCovered(file: string, range: LineRange): boolean {
  return (coveredRangesByFile.get(file) || []).some(
    (known) => known.start <= range.start && known.end >= range.end,
  );
}

function rememberRange(file: string, range: LineRange) {
  const rows = [...(coveredRangesByFile.get(file) || []), range]
    .sort((a, b) => a.start - b.start || a.end - b.end);
  const merged: LineRange[] = [];
  for (const row of rows) {
    const last = merged[merged.length - 1];
    if (!last || row.start > last.end + 1) {
      merged.push({ ...row });
    } else {
      last.end = Math.max(last.end, row.end);
    }
  }
  coveredRangesByFile.set(file, merged);
}

async function record(payload: Record<string, unknown>) {
  if (!ACTIVITY_PATH) return;
  await mkdir(dirname(ACTIVITY_PATH), { recursive: true });
  await appendFile(ACTIVITY_PATH, JSON.stringify(payload) + "\n", "utf8");
}

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
    const coverage = parsed.coverage && typeof parsed.coverage === "object"
      ? parsed.coverage
      : undefined;
    return {
      status: parsed.status === undefined ? undefined : String(parsed.status),
      session_consecutive_no_growth: Number.isFinite(Number(progress?.consecutive_no_growth))
        ? Math.max(0, Number(progress.consecutive_no_growth))
        : undefined,
      matched_existing_evidence: Array.isArray(parsed.matched_existing_evidence)
        ? parsed.matched_existing_evidence.length
        : undefined,
      coverage: coverage
        ? {
            context_start_line: Number.isFinite(Number(coverage.context_start_line))
              ? Number(coverage.context_start_line)
              : undefined,
            context_end_line: Number.isFinite(Number(coverage.context_end_line))
              ? Number(coverage.context_end_line)
              : undefined,
          }
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

function grew(progress: Progress | undefined): boolean {
  const delta = progress?.delta;
  return delta?.grew === true ||
    Number(delta?.new_evidence || 0) > 0 ||
    Number(delta?.new_lines || 0) > 0;
}

function explicitMechanicalNoGrowth(progress: Progress | undefined): boolean {
  const delta = progress?.delta;
  return progress?.status === "no_new_evidence" ||
    delta?.grew === false ||
    (delta?.new_evidence === 0 && delta?.new_lines === 0) ||
    (Number(progress?.matched_existing_evidence || 0) > 0 && !grew(progress));
}

function observeProgress(key: string, progress: Progress | undefined): number {
  const previous = noGrowthBySignature.get(key) || 0;
  if (grew(progress)) {
    noGrowthBySignature.set(key, 0);
    return 0;
  }

  // A first no_match can be useful negative evidence for the Agent. We only remember it
  // per exact immutable request so repeated identical misses can be stopped; it never
  // contributes to any cross-query/global no-growth decision here.
  const exactRequestNoGrowth = explicitMechanicalNoGrowth(progress) || progress?.status === "no_match";
  if (exactRequestNoGrowth) {
    const next = previous + 1;
    noGrowthBySignature.set(key, next);
    return next;
  }
  return previous;
}

function outcome(progress: Progress | undefined, isError: boolean): string {
  if (isError || progress?.status === "error") return "error";
  if (grew(progress)) return "positive";
  if (progress?.status === "no_match") return "neutral_no_match";
  if (explicitMechanicalNoGrowth(progress)) return "redundant";
  return "neutral";
}

export default function traceciteRetrievalGuard(pi: ExtensionAPI) {
  if (!enabled()) return;

  pi.on("agent_start", async () => {
    await record({
      event: "agent_start",
      no_growth_patience: NO_GROWTH_PATIENCE,
      max_retrievals: MAX_RETRIEVALS,
      retrievals,
      continued_investigation: retrievals > 0,
    });
  });

  pi.on("tool_call", async (event) => {
    if (!isAcquisition(event)) return undefined;
    const meta = callMeta(event);
    const noGrowth = noGrowthBySignature.get(meta.key) || 0;

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
        reason: `TraceCite retrieval guard: the ${MAX_RETRIEVALS}-call investigation evidence-acquisition limit has been reached. Provider retries do not reset this budget. Do not retry TraceCite; use the evidence already acquired and produce the final answer.`,
      } as any;
    }

    if (meta.file && meta.requested_range && rangeCovered(meta.file, meta.requested_range)) {
      await record({
        event: "tool_call",
        tool: event.toolName,
        decision: "block",
        reason: "range_already_covered",
        retrievals,
        requested_range: meta.requested_range,
        signature_no_growth: noGrowth,
      });
      return {
        block: true,
        reason: "TraceCite retrieval guard: this requested materialization range is already fully covered by immutable evidence retrieved in this investigation. Do not reread it for confidence; use the existing evidence refs or choose a genuinely uncovered range.",
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
        reason: `TraceCite retrieval guard: this exact immutable evidence request has already produced no new evidence ${noGrowth} times. Do not retry it. A prior no_match is request-local but repeating the identical request cannot add evidence; use existing evidence, choose a materially different unresolved evidence need, or produce the final answer.`,
      } as any;
    }

    retrievals += 1;
    pendingCalls.set(String(event.toolCallId || ""), meta);
    await record({
      event: "tool_call",
      tool: event.toolName,
      decision: "allow",
      retrievals,
      requested_range: meta.requested_range,
      signature_no_growth: noGrowth,
    });
    return undefined;
  });

  pi.on("tool_result", async (event) => {
    if (!ACQUISITION_TOOLS.has(String(event?.toolName || ""))) return undefined;
    const id = String(event.toolCallId || "");
    const meta = pendingCalls.get(id) || callMeta(event);
    pendingCalls.delete(id);
    const progress = progressFromContent(event.content);
    const noGrowth = Boolean(event.isError)
      ? (noGrowthBySignature.get(meta.key) || 0)
      : observeProgress(meta.key, progress);

    if (!event.isError && meta.file && meta.requested_range) {
      const start = Number(progress?.coverage?.context_start_line || 0);
      const end = Number(progress?.coverage?.context_end_line || 0);
      if (start > 0 && end >= start) {
        rememberRange(meta.file, { start, end });
      }
    }

    await record({
      event: "tool_result",
      tool: event.toolName,
      retrievals,
      signature_no_growth: noGrowth,
      mechanical_outcome: outcome(progress, Boolean(event.isError)),
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
      covered_sources: coveredRangesByFile.size,
    });
  });
}
