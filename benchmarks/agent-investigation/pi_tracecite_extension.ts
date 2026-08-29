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

export default function traceciteTools(pi: ExtensionAPI) {
  pi.registerTool({
    name: "tracecite_search",
    label: "TraceCite Search",
    description:
      "Search a large local text/log file with bounded, line-addressable evidence. Returns coverage, immutable evidence refs, signal hints, and bounded matches. This is retrieval evidence, not a root-cause judgement. Prefer it when a broad native grep would return too much context; expand decisive hits before relying on them.",
    promptSnippet:
      "Use tracecite_search for bounded evidence discovery in large logs; treat its output as evidence/navigation, never as causal truth.",
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
      const text = await runTraceCite(args, ctx.cwd, signal);
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
      const text = await runTraceCite(args, ctx.cwd, signal);
      return {
        content: [{ type: "text", text }],
        details: { operation: "expand", file: params.file, line: params.line, radius },
      };
    },
  });
}
