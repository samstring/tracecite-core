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
    source: value.source,
    identifier_key: value.identifier_key,
    identifier_value: value.identifier_value,
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
  const data = payload.data && typeof payload.data === "object" ? payload.data : {};

  if (operation === "search") {
    const constraints = Array.isArray(data.correlation_constraints)
      ? data.correlation_constraints.map(compactConstraint)
      : [];
    const gaps = Array.isArray(payload.missing_evidence)
      ? payload.missing_evidence.map(compactGap)
      : [];

    return JSON.stringify({
      operation: payload.operation,
      status: payload.status,
      outcome: payload.outcome,
      evidence: payload.evidence,
      coverage: payload.coverage,
      progress: data.progress,
      stop_reason: data.stop_reason,
      evidence_source: data.evidence_source,
      correlation_constraints: constraints.length ? constraints : undefined,
      missing_evidence: gaps.length ? gaps : undefined,
      routing: data.routing,
    });
  }

  if (operation === "expand") {
    const observedReferences = Array.isArray(data.observed_references)
      ? data.observed_references.slice(0, 6)
      : [];
    return JSON.stringify({
      operation: payload.operation,
      status: payload.status,
      outcome: payload.outcome,
      evidence: payload.evidence,
      coverage: payload.coverage,
      progress: data.progress,
      stop_reason: data.stop_reason,
      text: data.text,
      observed_references: observedReferences.length ? observedReferences : undefined,
      observed_references_note: observedReferences.length ? data.observed_references_note : undefined,
    });
  }

  return text;
}

export default function traceciteTools(pi: ExtensionAPI) {
  pi.registerTool({
    name: "tracecite_search",
    label: "TraceCite Search",
    description:
      "Search a large local text/log file through TraceCite's canonical retrieval contract. Returns bounded line-addressable evidence, provenance/coverage state, novelty, and mechanical identity/correlation facts. It does not plan the investigation or decide root cause.",
    promptSnippet:
      "tracecite_search returns evidence and evidence-state facts; you remain responsible for hypotheses, tool choice, investigation order, and conclusions.",
    promptGuidelines: [
      "Treat a search hit as an observation, not support for a causal hypothesis by itself.",
      "Treat correlation constraints as identity-safety facts, not root-cause claims or instructions.",
      "Use materialized line context when making exact citations from compact evidence pointers.",
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
          independent_retrieval_session: true,
          evidence_only: true,
        },
      };
    },
  });

  pi.registerTool({
    name: "tracecite_expand",
    label: "TraceCite Expand",
    description:
      "Materialize bounded source context through TraceCite's canonical retrieval contract around a line chosen by the Agent. Returns exact text, provenance/coverage state, and reference-like fields literally observed in that text; it does not recommend another action.",
    promptSnippet:
      "tracecite_expand materializes exact evidence context; observed references are facts from that context, not investigation instructions.",
    promptGuidelines: [
      "Treat observed_references as literal fields found in the materialized evidence only; they do not establish identity, importance, or causality.",
    ],
    parameters: Type.Object({
      file: Type.String({ description: "Path to the same local source file." }),
      line: Type.Integer({ minimum: 1, description: "1-based anchor line chosen by the Agent." }),
      radius: Type.Optional(Type.Integer({ minimum: 0, maximum: 30, description: "Context lines before and after the anchor; default 8." })),
      sha256: Type.Optional(Type.String({ description: "Optional expected source SHA-256 from prior evidence." })),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const args = ["expand", params.file, String(params.line), "--radius", String(params.radius ?? 8), "--max-chars", "16000"];
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
          independent_retrieval_session: true,
          evidence_only: true,
        },
      };
    },
  });
}
