import { execFile } from "node:child_process";
import { promisify } from "node:util";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const execFileAsync = promisify(execFile);
const MAX_BUFFER = 256 * 1024;

async function runTraceCite(args: string[], cwd: string, signal?: AbortSignal): Promise<string> {
  try {
    const { stdout, stderr } = await execFileAsync("tracecite", args, {
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
    const message = String(error?.message || error || "TraceCite command failed");
    return [
      `@TRACECITE_ERROR ${message}`,
      stdout ? `@STDOUT ${stdout}` : "",
      stderr ? `@STDERR ${stderr}` : "",
    ]
      .filter(Boolean)
      .join("\n");
  }
}

function compactConstraint(value: any) {
  if (!value || typeof value !== "object") return value;
  return {
    kind: value.kind,
    identifier_key: value.identifier_key,
    identifier_value: value.identifier_value,
    identifier_only_correlation_safe: value.identifier_only_correlation_safe,
    minimum_safe_correlation_key: value.minimum_safe_correlation_key,
    sibling_entity_count_observed: value.sibling_entity_count_observed,
    source_uniqueness: value.source_uniqueness,
  };
}

function compactGap(value: any) {
  if (!value || typeof value !== "object") return value;
  return {
    kind: value.kind,
    detail: value.detail,
    actionable: value.actionable,
    identifier_key: value.identifier_key,
    identifier_value: value.identifier_value,
    recommended_action: value.recommended_action,
  };
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
  if (operation === "search") {
    const data = payload.data && typeof payload.data === "object" ? payload.data : {};
    const priorityAction = data.actionable_retrieval ?? null;
    const constraints = Array.isArray(data.correlation_constraints)
      ? data.correlation_constraints.map(compactConstraint)
      : [];
    const gaps = Array.isArray(payload.missing_evidence)
      ? payload.missing_evidence.map(compactGap)
      : [];
    const signalHints = Array.isArray(data.signal_hints) ? data.signal_hints.slice(0, 5) : [];
    const genericNext = Array.isArray(payload.next_queries) ? payload.next_queries.slice(0, 5) : [];
    const nextQueries = priorityAction?.query ? [String(priorityAction.query)] : genericNext;

    return JSON.stringify({
      operation: payload.operation,
      status: payload.status,
      outcome: payload.outcome,
      priority_action: priorityAction,
      priority_note: priorityAction
        ? "Execute this action next to advance the current mechanical evidence/integrity gap. Earlier searches with the same text do not close this ordered step because the action was derived from the current result. This is navigation, not a root-cause claim."
        : undefined,
      evidence: payload.evidence,
      coverage: payload.coverage,
      evidence_source: data.evidence_source,
      correlation_constraints: constraints.length ? constraints : undefined,
      missing_evidence: gaps.length ? gaps : undefined,
      signal_hints: signalHints.length ? signalHints : undefined,
      next_queries: nextQueries.length ? nextQueries : undefined,
      routing: data.routing,
    });
  }

  if (operation === "expand") {
    const data = payload.data && typeof payload.data === "object" ? payload.data : {};
    return JSON.stringify({
      operation: payload.operation,
      status: payload.status,
      outcome: payload.outcome,
      evidence: payload.evidence,
      coverage: payload.coverage,
      text: data.text,
    });
  }

  return text;
}

export default function traceciteTools(pi: ExtensionAPI) {
  pi.registerTool({
    name: "tracecite_search",
    label: "TraceCite Search",
    description:
      "Search a large local text/log file with bounded, line-addressable evidence. Returns coverage, immutable evidence refs, signal hints, and any mechanically required next retrieval action. This is retrieval evidence, not a root-cause judgement.",
    promptSnippet:
      "Use tracecite_search for bounded evidence discovery in large logs; treat its output as evidence/navigation, never as causal truth.",
    promptGuidelines: [
      "When tracecite_search returns priority_action, execute that action next before unrelated broadening. Treat the priority actions as an ordered mechanical gap-closure sequence; a same-text search performed before the current result does not satisfy the newly derived step.",
      "tracecite_search constraints protect evidence correlation; they do not prove a root cause.",
      "Expand decisive TraceCite hits before citing or semantically interpreting them.",
    ],
    parameters: Type.Object({
      file: Type.String({ description: "Path to the local source file, relative to the current working directory or absolute." }),
      query: Type.String({ description: "Literal or regex query." }),
      regex: Type.Optional(Type.Boolean({ description: "Interpret query as a regular expression." })),
      max_evidence: Type.Optional(
        Type.Integer({ minimum: 1, maximum: 50, description: "Maximum evidence rows to return; default 20." }),
      ),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const args = [
        "search",
        params.file,
        params.query,
        "--no-snapshot",
        "--compact",
        "--max-evidence",
        String(params.max_evidence ?? 20),
        "--max-output-chars",
        "16000",
        "--lightweight",
      ];
      if (params.regex) args.push("--regex");
      const text = projectForPi(await runTraceCite(args, ctx.cwd, signal));
      return {
        content: [{ type: "text", text }],
        details: { operation: "search", file: params.file, query: params.query },
      };
    },
  });

  pi.registerTool({
    name: "tracecite_expand",
    label: "TraceCite Expand",
    description:
      "Materialize bounded source context around a specific line found by TraceCite. Use this to inspect/cite a decisive hit rather than reasoning only from compact search labels. Returns exact source lines and evidence metadata; it does not interpret causality.",
    promptSnippet:
      "Expand important TraceCite hits before citing or interpreting them.",
    promptGuidelines: [
      "Use tracecite_expand to materialize the exact source context for evidence that matters to the final explanation.",
    ],
    parameters: Type.Object({
      file: Type.String({ description: "Path to the same local source file." }),
      line: Type.Integer({ minimum: 1, description: "1-based anchor line." }),
      radius: Type.Optional(
        Type.Integer({ minimum: 0, maximum: 30, description: "Context lines before and after the anchor; default 8." }),
      ),
      sha256: Type.Optional(
        Type.String({ description: "Optional expected source SHA-256 from a prior TraceCite result." }),
      ),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const radius = params.radius ?? 8;
      const args = [
        "expand",
        params.file,
        String(params.line),
        "--before",
        String(radius),
        "--after",
        String(radius),
        "--max-chars",
        "16000",
      ];
      if (params.sha256) args.push("--expected-sha256", params.sha256);
      const text = projectForPi(await runTraceCite(args, ctx.cwd, signal));
      return {
        content: [{ type: "text", text }],
        details: { operation: "expand", file: params.file, line: params.line, radius },
      };
    },
  });
}
