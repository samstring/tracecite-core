import { execFile } from "node:child_process";
import { tmpdir } from "node:os";
import { join } from "node:path";
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
  ]) {
    if (value[key] !== undefined && value[key] !== null) out[key] = value[key];
  }
  return Object.keys(out).length ? out : undefined;
}

function compactProgress(value: any) {
  if (!value || typeof value !== "object") return undefined;
  const delta = value.delta && typeof value.delta === "object" ? value.delta : undefined;
  const out: any = {
    delta: delta ? {
      new_evidence: delta.new_evidence,
      new_relations: delta.new_relations,
      new_lines: delta.new_lines,
    } : undefined,
    seen_evidence: value.seen_evidence,
    seen_lines: value.seen_lines,
  };
  if (value.stop?.recommended) out.stop = value.stop;
  return out;
}

function compactConstraint(value: any) {
  if (!value || typeof value !== "object") return value;
  const scopes = Array.isArray(value.scoped_entities)
    ? value.scoped_entities.slice(0, 12)
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

function retrievalGuidance(status: string, coverage: any, progress: any): string | undefined {
  if (progress?.stop?.recommended) {
    return "STOP TraceCite retrieval for the current evidence scope: it is no longer producing new evidence. Use the evidence already collected to answer. Resume only for a materially new hypothesis with a narrower, explicit identity scope.";
  }
  if (status === "no_new_evidence") {
    return "No new evidence was produced. Do not repeat or broadly rephrase this search/expansion; either answer from existing evidence or state that the deeper claim is not established.";
  }
  if (status === "no_match") {
    return "No evidence matched. Do not automatically broaden the search just to find a deeper cause; only continue if a specific alternative hypothesis gives you a new scoped query.";
  }
  const matchLines = Number(coverage?.match_lines || 0);
  const returned = Number(coverage?.evidence_returned || 0);
  if (coverage?.evidence_truncated && returned > 0 && matchLines >= returned * 4) {
    return "High-fanout search: returned rows may mix sibling tests, namespaces, pods, or claims. Narrow using a stable identifier from the target failure before making identity or causal inferences.";
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

  if (operation === "search") {
    const constraints = Array.isArray(data.correlation_constraints)
      ? data.correlation_constraints.map(compactConstraint)
      : [];
    const gaps = Array.isArray(payload.missing_evidence)
      ? payload.missing_evidence.map(compactGap)
      : [];
    const evidence = Array.isArray(payload.evidence)
      ? payload.evidence.map(compactEvidence)
      : [];

    return JSON.stringify({
      status,
      evidence,
      coverage,
      progress,
      guidance: retrievalGuidance(status, coverage, progress),
      correlation_constraints: constraints.length ? constraints : undefined,
      missing_evidence: gaps.length ? gaps : undefined,
      stop_reason: status !== "ok" ? data.stop_reason : undefined,
    });
  }

  if (operation === "expand") {
    const observedReferences = Array.isArray(data.observed_references)
      ? data.observed_references.slice(0, 6)
      : [];
    const observedRelations = Array.isArray(data.observed_relations)
      ? data.observed_relations.slice(0, 8).map(compactRelation)
      : [];
    const evidence = Array.isArray(payload.evidence)
      ? payload.evidence.map(compactEvidence)
      : [];
    return JSON.stringify({
      status,
      evidence,
      coverage,
      progress,
      guidance: retrievalGuidance(status, coverage, progress),
      text: data.text,
      observed_references: observedReferences.length ? observedReferences : undefined,
      observed_relations: observedRelations.length ? observedRelations : undefined,
      evidence_semantics: observedRelations.length
        ? "observed_relations describe literal textual structure only; Agent owns identity and causal interpretation"
        : undefined,
      stop_reason: status !== "ok" ? data.stop_reason : undefined,
    });
  }

  return text;
}

export default function traceciteTools(pi: ExtensionAPI) {
  pi.registerTool({
    name: "tracecite_search",
    label: "TraceCite Search",
    description:
      "Search a large local text/log file through TraceCite's canonical retrieval contract. Returns compact line-addressable evidence plus provenance/coverage and mechanical identity-safety facts. It does not plan the investigation or decide root cause.",
    promptSnippet:
      "tracecite_search returns compact evidence and evidence-state facts; you remain responsible for hypotheses, tool choice, investigation order, conclusions, and stopping when evidence stops growing.",
    promptGuidelines: [
      "Treat a search hit as an observation, not support for a causal hypothesis by itself.",
      "Treat correlation constraints and scoped entities as identity-safety facts, not root-cause claims or instructions.",
      "Use tracecite_expand or native read before making exact claims from a compact search preview.",
      "When progress.stop.recommended is true, stop TraceCite retrieval for that scope. Do not keep broadening merely to discover a deeper cause; if the requested deeper contributor is not directly established, say so.",
      "When a search has high fanout, narrow by the target test/namespace/pod/claim identifier before correlating sibling evidence.",
    ],
    parameters: Type.Object({
      file: Type.String({ description: "Path to the local source file, relative to the current working directory or absolute." }),
      query: Type.String({ description: "Literal or regex query chosen by the Agent." }),
      regex: Type.Optional(Type.Boolean({ description: "Interpret query as a regular expression." })),
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
      "Materialize bounded exact source context around a line chosen by the Agent. Returns exact text plus literal reference and structural-relation facts; it does not recommend another action.",
    promptSnippet:
      "tracecite_expand materializes exact evidence context; observed references and structural relations are evidence facts, not investigation instructions. Stop expanding a scope when progress says evidence is no longer growing.",
    promptGuidelines: [
      "Treat observed_references as literal fields found in the materialized evidence only.",
      "Treat observed_relations as textual co-observation or structured-block membership only; they do not establish identity, importance, or causality.",
      "When status is no_new_evidence or progress.stop.recommended is true, do not repeat overlapping expansions. Use the evidence already observed or state the evidence boundary.",
    ],
    parameters: Type.Object({
      file: Type.String({ description: "Path to the same local source file." }),
      line: Type.Integer({ minimum: 1, description: "1-based anchor line chosen by the Agent." }),
      radius: Type.Optional(Type.Integer({ minimum: 0, maximum: 30, description: "Context lines before and after the anchor; default 8." })),
      sha256: Type.Optional(Type.String({ description: "Optional expected source SHA-256 from prior evidence." })),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const args = ["expand", params.file, String(params.line), "--radius", String(params.radius ?? 8), "--max-chars", "12000"];
      if (params.sha256) args.push("--sha256", params.sha256);
      const text = projectForPi(await runBridge(args, ctx.cwd, signal));
      return {
        content: [{ type: "text", text }],
        details: {
          operation: "expand",
          file: params.file,
          line: params.line,
          radius: params.radius ?? 8,
          canonical_retrieve: true,
          persistent_retrieval_session: true,
          evidence_only: true,
          compact_agent_view: true,
        },
      };
    },
  });
}
