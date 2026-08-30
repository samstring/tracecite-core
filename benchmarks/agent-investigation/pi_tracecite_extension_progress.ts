import { execFile } from "node:child_process";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const execFileAsync = promisify(execFile);
const MAX_BUFFER = 256 * 1024;
const BRIDGE = fileURLToPath(new URL("./pi_tracecite_bridge_progress.py", import.meta.url));
const SESSION =
  process.env.TRACECITE_PI_SESSION ||
  process.env.TRACECITE_PI_INVESTIGATION ||
  join(tmpdir(), `tracecite-pi-${process.pid}`, "retrieval-session.json");

async function runBridge(args: string[], cwd: string, signal?: AbortSignal): Promise<string> {
  try {
    const { stdout, stderr } = await execFileAsync("python", [BRIDGE, "--session", SESSION, ...args], {
      cwd,
      encoding: "utf8",
      maxBuffer: MAX_BUFFER,
      signal,
    });
    const out = String(stdout || "").trim();
    const err = String(stderr || "").trim();
    if (out && err) return `${out}\n@STDERR ${err}`;
    return out || err || "{}";
  } catch (error: any) {
    const stdout = String(error?.stdout || "").trim();
    const stderr = String(error?.stderr || "").trim();
    const message = String(error?.message || error || "TraceCite bridge failed");
    return [
      `@TRACECITE_ERROR ${message}`,
      stdout ? `@STDOUT ${stdout}` : "",
      stderr ? `@STDERR ${stderr}` : "",
    ].filter(Boolean).join("\n");
  }
}

function shorten(value: any, max = 420): string | undefined {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text) return undefined;
  return text.length <= max ? text : `${text.slice(0, Math.max(1, max - 1))}…`;
}

function compactEvidence(value: any) {
  if (!value || typeof value !== "object") return value;
  const start = Number(value.start_line || 0);
  const end = Number(value.end_line || start || 0);
  const source = String(value.source_path || "").split(/[\\/]/).pop() || "evidence";
  const ref = start > 0 ? `${source}:L${start}${end > start ? `-L${end}` : ""}` : undefined;
  return { ref, preview: shorten(value.label) };
}

function compactEvidenceRef(value: any) {
  if (!value || typeof value !== "object") return undefined;
  const start = Number(value.start_line || 0);
  const end = Number(value.end_line || start || 0);
  const source = String(value.source_path || "").split(/[\\/]/).pop() || "evidence";
  const ref = start > 0 ? `${source}:L${start}${end > start ? `-L${end}` : ""}` : undefined;
  const uri = shorten(value.uri, 220);
  if (!ref && !uri) return undefined;
  return ref ? { ref } : { uri };
}

function sourceSha256(rows: any[]): string | undefined {
  const values = Array.from(new Set(
    rows
      .map((value) => String(value?.sha256 || "").trim().toLowerCase())
      .filter((value) => /^[0-9a-f]{64}$/.test(value)),
  ));
  return values.length === 1 ? values[0] : undefined;
}

function compactCoverage(value: any) {
  if (!value || typeof value !== "object") return undefined;
  const out: any = {};
  for (const key of [
    "context_start_line", "context_end_line", "match_lines", "evidence_returned",
    "evidence_truncated", "truncated", "new_evidence", "repeated_evidence", "replayed_evidence",
  ]) {
    if (value[key] !== undefined && value[key] !== null) out[key] = value[key];
  }
  return Object.keys(out).length ? out : undefined;
}

function compactProgress(value: any) {
  if (!value || typeof value !== "object") return undefined;
  const delta = value.delta && typeof value.delta === "object" ? value.delta : undefined;
  return {
    delta: delta ? {
      new_evidence: delta.new_evidence,
      new_relations: delta.new_relations,
      new_lines: delta.new_lines,
    } : undefined,
    seen_evidence: value.seen_evidence,
    seen_lines: value.seen_lines,
  };
}

function compactSessionProgress(value: any) {
  if (!value || typeof value !== "object") return undefined;
  return {
    search_calls: Number(value.search_calls || 0),
    expand_calls: Number(value.expand_calls || 0),
    unique_evidence_seen: Number(value.unique_evidence_seen || 0),
    exact_duplicate_queries: Number(value.exact_duplicate_queries || 0),
    recent_window: Number(value.recent_window || 0),
    recent_new: Number(value.recent_searches_with_new_evidence || 0),
    recent_repeated_only: Number(value.recent_repeated_only_searches || 0),
    recent_no_match: Number(value.recent_no_match_searches || 0),
  };
}

function compactConstraint(value: any) {
  if (!value || typeof value !== "object") return value;
  const siblings = Array.isArray(value.observed_sibling_entities)
    ? value.observed_sibling_entities.slice(0, 8).map((item: any) => ({
        entity: item?.entity,
        scope: item?.scope,
        occurrence_count: item?.occurrence_count,
        references: Array.isArray(item?.references) ? item.references.slice(0, 3) : undefined,
      }))
    : [];
  return {
    kind: value.kind,
    identifier_key: value.identifier_key,
    identifier_value: value.identifier_value,
    identifier_only_correlation_safe: value.identifier_only_correlation_safe,
    minimum_safe_correlation_key: value.minimum_safe_correlation_key,
    sibling_entity_count_observed: value.sibling_entity_count_observed,
    scope_fanout_observed: value.scope_fanout_observed,
    source_uniqueness: value.source_uniqueness,
    scoped_entities: Array.isArray(value.scoped_entities) ? value.scoped_entities.slice(0, 12) : undefined,
    observed_sibling_entities: siblings.length ? siblings : undefined,
    observed_sibling_entities_truncated: value.observed_sibling_entities_truncated,
    sibling_entity_note: shorten(value.sibling_entity_note, 220),
  };
}

function compactGap(value: any) {
  if (!value || typeof value !== "object") return value;
  return {
    kind: value.kind,
    detail: shorten(value.detail, 260),
    identifier_key: value.identifier_key,
    identifier_value: value.identifier_value,
  };
}

function compactRelation(value: any) {
  if (!value || typeof value !== "object") return value;
  return {
    relation: value.relation,
    subject: value.subject,
    object: value.object,
    visible_lines: value.visible_lines,
  };
}

function retrievalGuidance(status: string, coverage: any): string | undefined {
  const added = Number(coverage?.new_evidence || 0);
  const repeated = Number(coverage?.repeated_evidence || 0);
  if (status === "no_new_evidence" || (added === 0 && repeated > 0)) {
    return "This call exposed no new evidence; repeated bodies were suppressed. matched_existing_evidence identifies which previously delivered refs matched this call; expand or replay only when you need that old text again.";
  }
  if (status === "no_match") {
    return "No evidence matched this query. This is a retrieval fact, not a conclusion about the investigation.";
  }
  const matchLines = Number(coverage?.match_lines || 0);
  const returned = Number(coverage?.evidence_returned || 0);
  if (coverage?.evidence_truncated && returned > 0 && matchLines >= returned * 4) {
    return "High-fanout search: only a bounded projection is visible. Prefer a narrower identity-scoped query over increasing output or dumping the source with native grep.";
  }
  return undefined;
}

function projectForPi(text: string): string {
  let payload: any;
  try { payload = JSON.parse(text); } catch { return text; }
  if (!payload || typeof payload !== "object") return text;

  const operation = String(payload.operation || "");
  const data = payload.data && typeof payload.data === "object" ? payload.data : {};
  const status = String(payload.status || "");
  const coverage = compactCoverage(payload.coverage);
  const progress = compactProgress(data.progress);
  const session_progress = compactSessionProgress(data.session_progress);
  const rawEvidence = Array.isArray(payload.evidence) ? payload.evidence : [];
  const source_sha256 = sourceSha256(rawEvidence);

  if (operation === "search") {
    const constraints = Array.isArray(data.correlation_constraints)
      ? data.correlation_constraints.map(compactConstraint)
      : [];
    const gaps = Array.isArray(payload.missing_evidence)
      ? payload.missing_evidence.map(compactGap)
      : [];
    const matchedExistingEvidence = Array.isArray(data.matched_existing_evidence)
      ? data.matched_existing_evidence.slice(0, 50).map(compactEvidenceRef).filter(Boolean)
      : [];
    return JSON.stringify({
      status,
      evidence: rawEvidence.map(compactEvidence),
      matched_existing_evidence: matchedExistingEvidence.length ? matchedExistingEvidence : undefined,
      source_sha256,
      coverage,
      progress,
      session_progress,
      guidance: retrievalGuidance(status, coverage),
      correlation_constraints: constraints.length ? constraints : undefined,
      missing_evidence: gaps.length ? gaps : undefined,
      retrieval_reason: status !== "ok" ? data.stop_reason : undefined,
    });
  }

  if (operation === "expand") {
    const observedReferences = Array.isArray(data.observed_references) ? data.observed_references.slice(0, 6) : [];
    const observedRelations = Array.isArray(data.observed_relations)
      ? data.observed_relations.slice(0, 8).map(compactRelation)
      : [];
    const projectedText = data.replayed ? data.text : (data.new_text !== undefined ? data.new_text : data.text);
    return JSON.stringify({
      status,
      evidence: rawEvidence.map(compactEvidence),
      source_sha256,
      coverage,
      progress,
      session_progress,
      guidance: retrievalGuidance(status, coverage),
      text: projectedText || undefined,
      replayed: data.replayed || undefined,
      unseen_ranges: Array.isArray(data.unseen_ranges) ? data.unseen_ranges : undefined,
      repeated_text_suppressed: data.repeated_text_suppressed || undefined,
      observed_references: observedReferences.length ? observedReferences : undefined,
      observed_relations: observedRelations.length ? observedRelations : undefined,
      evidence_semantics: observedRelations.length
        ? "observed_relations describe literal textual structure only; Agent owns identity and causal interpretation"
        : undefined,
      retrieval_reason: status !== "ok" ? data.stop_reason : undefined,
    });
  }

  return text;
}

export default function traceciteTools(pi: ExtensionAPI) {
  pi.registerTool({
    name: "tracecite_search",
    label: "TraceCite Search",
    description:
      "Search a large local text/log file through TraceCite. Returns new evidence, compact refs for repeated evidence, identity-safety facts, and mechanical session_progress. session_progress reports retrieval history only; it never decides sufficiency, root cause, or stopping.",
    promptSnippet:
      "tracecite_search returns evidence plus mechanical session_progress. session_progress only reports how much recent retrieval produced new, repeated-only, or no-match results; use it as observability, not as a stop recommendation. You own hypotheses, conclusions, and when to stop.",
    promptGuidelines: [
      "Treat search hits as observations, not causal conclusions.",
      "Treat session_progress as mechanical retrieval history only. It does not mean evidence is sufficient or that investigation should stop.",
      "If recent retrieval repeatedly covers old evidence or returns no match, decide yourself whether a materially different evidence target is still needed.",
      "matched_existing_evidence means the current query matched previously delivered evidence; it does not mean that evidence is understood, important, causal, or sufficient.",
      "If identifier_only_correlation_safe=false, use minimum_safe_correlation_key for correlation; this is identity safety, not root cause.",
      "Use tracecite_expand or a narrow native read before exact claims from a compact preview.",
      "Use regex=true for regex operators; otherwise matching is literal.",
    ],
    parameters: Type.Object({
      file: Type.String({ description: "Path to the local source file." }),
      query: Type.String({ description: "Literal query by default." }),
      regex: Type.Optional(Type.Boolean({ description: "Interpret query as regex; default false." })),
      max_evidence: Type.Optional(Type.Integer({ minimum: 1, maximum: 50, description: "Maximum evidence rows; default 20." })),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const args = ["search", params.file, params.query, "--max-evidence", String(params.max_evidence ?? 20)];
      if (params.regex) args.push("--regex");
      const text = projectForPi(await runBridge(args, ctx.cwd, signal));
      return { content: [{ type: "text", text }], details: { operation: "search", compact_agent_view: true, session_progress: true } };
    },
  });

  pi.registerTool({
    name: "tracecite_expand",
    label: "TraceCite Expand",
    description:
      "Materialize bounded exact source context. Returns only unseen context by default and includes mechanical session_progress; replay=true deliberately re-reads old context without making it new evidence.",
    promptSnippet:
      "tracecite_expand materializes exact context and reports mechanical session_progress. Replay is a reread, not new evidence; the Agent owns all stopping and causal decisions.",
    promptGuidelines: [
      "Treat session_progress as mechanical retrieval history only, never as evidence sufficiency or a stop signal.",
      "Observed relations are textual/structural observations only, not causal conclusions.",
      "Use replay=true only when you intentionally need old text again.",
    ],
    parameters: Type.Object({
      file: Type.String({ description: "Path to the same local source file." }),
      line: Type.Integer({ minimum: 1, description: "1-based anchor line." }),
      radius: Type.Optional(Type.Integer({ minimum: 0, maximum: 30, description: "Context lines before/after; default 8." })),
      sha256: Type.Optional(Type.String({ description: "Expected source SHA-256 when available." })),
      replay: Type.Optional(Type.Boolean({ description: "Explicitly re-read previously exposed context." })),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const args = ["expand", params.file, String(params.line), "--radius", String(params.radius ?? 8), "--max-chars", "12000"];
      if (params.sha256) args.push("--sha256", params.sha256);
      if (params.replay) args.push("--replay");
      const text = projectForPi(await runBridge(args, ctx.cwd, signal));
      return { content: [{ type: "text", text }], details: { operation: "expand", compact_agent_view: true, session_progress: true } };
    },
  });
}
