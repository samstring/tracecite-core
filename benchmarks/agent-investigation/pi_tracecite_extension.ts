import { execFile } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const execFileAsync = promisify(execFile);
const MAX_BUFFER = 256 * 1024;
const BRIDGE = fileURLToPath(new URL("./pi_tracecite_bridge.py", import.meta.url));
const SESSION =
  process.env.TRACECITE_PI_SESSION ||
  process.env.TRACECITE_PI_INVESTIGATION ||
  join(tmpdir(), `tracecite-pi-${process.pid}`, "retrieval-session.json");


type HostToolCategory = "tracecite_evidence" | "native_search" | "native_read" | "native_other" | "other";
type HostToolActivity = {
  tool: string;
  category: HostToolCategory;
  duration_ms: number;
  status: string;
  metadata?: Record<string, unknown>;
};

const ACTIVITY_PATH =
  process.env.TRACECITE_PI_ACTIVITY || join(dirname(SESSION), "host-tool-activity.json");
const activityStarted = new Map<string, number>();
const activityEvents: HostToolActivity[] = [];
let activityWrite: Promise<void> = Promise.resolve();

function classifyHostTool(tool: string): HostToolCategory {
  if (tool === "tracecite_search" || tool === "tracecite_expand") return "tracecite_evidence";
  if (tool === "grep" || tool === "find") return "native_search";
  if (tool === "read") return "native_read";
  if (tool === "bash" || tool === "ls") return "native_other";
  return "other";
}

function hostActivitySummary() {
  const categories: Record<string, number> = {};
  const tools: Record<string, number> = {};
  let observed_duration_ms = 0;
  for (const event of activityEvents) {
    categories[event.category] = (categories[event.category] || 0) + 1;
    tools[event.tool] = (tools[event.tool] || 0) + 1;
    observed_duration_ms += event.duration_ms;
  }
  return {
    total_tool_calls: activityEvents.length,
    categories: Object.fromEntries(Object.entries(categories).sort(([a], [b]) => a.localeCompare(b))),
    tools: Object.fromEntries(Object.entries(tools).sort(([a], [b]) => a.localeCompare(b))),
    observed_duration_ms,
  };
}

async function persistHostActivity(): Promise<void> {
  await mkdir(dirname(ACTIVITY_PATH), { recursive: true });
  await writeFile(
    ACTIVITY_PATH,
    JSON.stringify({ schema_version: 1, summary: hostActivitySummary(), events: activityEvents }, null, 2) + "\n",
    "utf8",
  );
}

function queueHostActivityWrite(): Promise<void> {
  activityWrite = activityWrite.then(persistHostActivity, persistHostActivity);
  return activityWrite;
}

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
  if (text.length <= max) return text;
  return `${text.slice(0, Math.max(1, max - 1))}…`;
}

function compactEvidence(value: any) {
  if (!value || typeof value !== "object") return value;
  const start = Number(value.start_line || 0);
  const end = Number(value.end_line || start || 0);
  const source = String(value.source_path || "").split(/[\\/]/).pop() || "evidence";
  const ref = start > 0
    ? `${source}:L${start}${end > start ? `-L${end}` : ""}`
    : undefined;
  return {
    ref,
    preview: shorten(value.label),
  };
}

function compactEvidenceRef(value: any) {
  if (!value || typeof value !== "object") return undefined;
  const start = Number(value.start_line || 0);
  const end = Number(value.end_line || start || 0);
  const source = String(value.source_path || "").split(/[\\/]/).pop() || "evidence";
  const ref = start > 0
    ? `${source}:L${start}${end > start ? `-L${end}` : ""}`
    : undefined;
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
    "context_start_line",
    "context_end_line",
    "match_lines",
    "evidence_returned",
    "evidence_truncated",
    "truncated",
    "new_evidence",
    "repeated_evidence",
    "replayed_evidence",
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

function compactSiblingEntity(value: any) {
  if (!value || typeof value !== "object") return undefined;
  const entity = String(value.entity || "").trim();
  if (!entity) return undefined;
  const refs = Array.isArray(value.references)
    ? value.references.map((item: any) => String(item || "").trim()).filter(Boolean).slice(0, 3)
    : [];
  return {
    entity,
    scope: String(value.scope || "").trim() || undefined,
    occurrence_count: value.occurrence_count,
    references: refs.length ? refs : undefined,
  };
}

function compactConstraint(value: any) {
  if (!value || typeof value !== "object") return value;
  const scopes = Array.isArray(value.scoped_entities)
    ? value.scoped_entities.slice(0, 12)
    : [];
  const siblings = Array.isArray(value.observed_sibling_entities)
    ? value.observed_sibling_entities
        .slice(0, 8)
        .map(compactSiblingEntity)
        .filter(Boolean)
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
    scoped_entities: scopes.length ? scopes : undefined,
    scoped_entities_truncated:
      Array.isArray(value.scoped_entities) && value.scoped_entities.length > scopes.length
        ? value.scoped_entities.length - scopes.length
        : undefined,
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
    return "No evidence matched this query. This is a retrieval fact, not a conclusion about the investigation. Check literal-vs-regex syntax and identity scope before changing retrieval paths.";
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
  try {
    payload = JSON.parse(text);
  } catch {
    return text;
  }
  if (!payload || typeof payload !== "object") return text;

  const operation = String(payload.operation || "");
  const data = payload.data && typeof payload.data === "object" ? payload.data : {};
  const status = String(payload.status || "");
  const coverage = compactCoverage(payload.coverage);
  const progress = compactProgress(data.progress);
  const rawEvidence = Array.isArray(payload.evidence) ? payload.evidence : [];
  const source_sha256 = sourceSha256(rawEvidence);

  if (operation === "search") {
    const constraints = Array.isArray(data.correlation_constraints)
      ? data.correlation_constraints.map(compactConstraint)
      : [];
    const gaps = Array.isArray(payload.missing_evidence)
      ? payload.missing_evidence.map(compactGap)
      : [];
    const evidence = rawEvidence.map(compactEvidence);
    const matchedExistingEvidence = Array.isArray(data.matched_existing_evidence)
      ? data.matched_existing_evidence.slice(0, 50).map(compactEvidenceRef).filter(Boolean)
      : [];

    return JSON.stringify({
      status,
      evidence,
      matched_existing_evidence: matchedExistingEvidence.length ? matchedExistingEvidence : undefined,
      source_sha256,
      coverage,
      progress,
      guidance: retrievalGuidance(status, coverage),
      correlation_constraints: constraints.length ? constraints : undefined,
      missing_evidence: gaps.length ? gaps : undefined,
      retrieval_reason: status !== "ok" ? data.stop_reason : undefined,
    });
  }

  if (operation === "expand") {
    const observedReferences = Array.isArray(data.observed_references)
      ? data.observed_references.slice(0, 6)
      : [];
    const observedRelations = Array.isArray(data.observed_relations)
      ? data.observed_relations.slice(0, 8).map(compactRelation)
      : [];
    const evidence = rawEvidence.map(compactEvidence);
    const projectedText = data.replayed
      ? data.text
      : (data.new_text !== undefined ? data.new_text : data.text);
    return JSON.stringify({
      status,
      evidence,
      source_sha256,
      coverage,
      progress,
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
  pi.on("tool_call", async (event) => {
    activityStarted.set(event.toolCallId, Date.now());
  });

  pi.on("tool_result", async (event) => {
    const started = activityStarted.get(event.toolCallId) ?? Date.now();
    activityStarted.delete(event.toolCallId);
    const row: HostToolActivity = {
      tool: event.toolName,
      category: classifyHostTool(event.toolName),
      duration_ms: Math.max(0, Date.now() - started),
      status: event.isError ? "error" : "ok",
      metadata: event.toolName === "bash" ? { opaque: true } : undefined,
    };
    activityEvents.push(row);
    if (activityEvents.length > 512) activityEvents.splice(0, activityEvents.length - 512);
    await queueHostActivityWrite();
    const baseDetails =
      event.details && typeof event.details === "object" && !Array.isArray(event.details)
        ? (event.details as Record<string, unknown>)
        : {};
    return {
      details: {
        ...baseDetails,
        tracecite_host_activity: row,
        tracecite_host_activity_summary: hostActivitySummary(),
      },
    } as any;
  });

  pi.registerTool({
    name: "tracecite_search",
    label: "TraceCite Search",
    description:
      "Search a large local text/log file through TraceCite's canonical retrieval contract. Returns only evidence not already exposed in this Pi retrieval session; repeated evidence bodies are suppressed while compact refs identify which old evidence matched. Literal matching is the default; set regex=true for regex syntax. It does not plan the investigation, decide root cause, or decide when the Agent should stop.",
    promptSnippet:
      "tracecite_search returns session-scoped evidence novelty and identity-safety facts. Repeated evidence bodies are suppressed, but matched_existing_evidence reports compact refs for old evidence matched by the current query. Use regex=true for regex operators. You remain responsible for hypotheses, tool choice, investigation order, conclusions, and stopping.",
    promptGuidelines: [
      "Treat a search hit as an observation, not support for a causal hypothesis by itself.",
      "For large evidence files, prefer TraceCite over broad native grep/read used only to discover evidence locations.",
      "If a query uses regex operators such as |, .*, [], (), ^, or $, set regex=true; otherwise the query is literal.",
      "Treat correlation constraints, scoped entities, and observed sibling entities as identity-safety facts, not root-cause claims.",
      "If identifier_only_correlation_safe=false, use minimum_safe_correlation_key and distinguish competing observed sibling entities before correlating timelines.",
      "Use tracecite_expand or a narrow native read before making exact claims from a compact search preview.",
      "Do not repeat the same immutable-source search merely to re-read evidence; reuse refs, expand, or replay it.",
      "matched_existing_evidence means the current query matched previously delivered evidence; it does not mean that evidence is understood, important, causal, or sufficient.",
      "A zero-new-evidence result only says this retrieval added nothing new to the current session; it does not say the investigation is complete.",
      "When a search has high fanout, prefer an identity-scoped query over increasing output or dumping the source with native grep.",
    ],
    parameters: Type.Object({
      file: Type.String({ description: "Path to the local source file, relative to the current working directory or absolute." }),
      query: Type.String({ description: "Literal query by default. If this string contains regex syntax, also set regex=true." }),
      regex: Type.Optional(Type.Boolean({ description: "Interpret query as a regular expression. Required when using regex operators such as | or .*; default false." })),
      max_evidence: Type.Optional(Type.Integer({ minimum: 1, maximum: 50, description: "Maximum evidence rows to return; default 20." })),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const args = ["search", params.file, params.query, "--max-evidence", String(params.max_evidence ?? 20)];
      if (params.regex) args.push("--regex");
      const text = projectForPi(await runBridge(args, ctx.cwd, signal));
      return {
        content: [{ type: "text", text }],
        details: {
          operation: "search",
          file: params.file,
          query: params.query,
          regex: Boolean(params.regex),
          canonical_retrieve: true,
          persistent_retrieval_session: true,
          evidence_only: true,
          compact_agent_view: true,
        },
      };
    },
  });

  pi.registerTool({
    name: "tracecite_expand",
    label: "TraceCite Expand",
    description:
      "Materialize bounded exact source context around a line. By default only line content not already exposed in this retrieval session is returned. Set replay=true to deliberately re-read known context; replayed text is not counted as new evidence.",
    promptSnippet:
      "tracecite_expand returns new exact context by default. If you need to reconsider old context, explicitly replay it; replay is a re-read, not new evidence.",
    promptGuidelines: [
      "Treat observed_references as literal fields found in the materialized evidence only.",
      "Treat observed_relations as textual co-observation or structured-block membership only; they do not establish identity, importance, or causality.",
      "When overlapping context was already exposed, TraceCite may return only unseen line ranges rather than repeating the whole window.",
      "Do not broadly read/grep the same expanded range just to see it again; use replay=true for an intentional reread.",
      "Use replay=true only when you intentionally need the old text again. Reuse source_sha256 when available so the replay is tied to the same immutable source version.",
    ],
    parameters: Type.Object({
      file: Type.String({ description: "Path to the same local source file." }),
      line: Type.Integer({ minimum: 1, description: "1-based anchor line chosen by the Agent." }),
      radius: Type.Optional(Type.Integer({ minimum: 0, maximum: 30, description: "Context lines before and after the anchor; default 8." })),
      sha256: Type.Optional(Type.String({ description: "Expected source SHA-256 from prior evidence when available." })),
      replay: Type.Optional(Type.Boolean({ description: "Explicitly re-read previously exposed context. Replayed content is not new evidence." })),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const args = ["expand", params.file, String(params.line), "--radius", String(params.radius ?? 8), "--max-chars", "12000"];
      if (params.sha256) args.push("--sha256", params.sha256);
      if (params.replay) args.push("--replay");
      const text = projectForPi(await runBridge(args, ctx.cwd, signal));
      return {
        content: [{ type: "text", text }],
        details: {
          operation: "expand",
          file: params.file,
          line: params.line,
          radius: params.radius ?? 8,
          replay: Boolean(params.replay),
          canonical_retrieve: true,
          persistent_retrieval_session: true,
          evidence_only: true,
          compact_agent_view: true,
        },
      };
    },
  });
}
