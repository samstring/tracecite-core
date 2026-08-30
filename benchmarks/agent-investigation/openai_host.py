from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping, Sequence

from tracecite.extension.evidence import EntityRef, EvidenceRelation
from tracecite.extension.retrieval import ProviderEvidence, RetrieveRequest
from tracecite.integrations.evidence_package import build_evidence_package
from tracecite.integrations.investigator import investigate
from tracecite.integrations.json_evidence_provider import JsonEvidenceProvider
from tracecite.runtime.correlation import EvidenceNode, correlate
from tracecite.runtime.traversal_frontier import TraversalLimits
from tracecite.runtime.grouping import group_evidence
from tracecite.runtime.reducer import ReductionPolicy, reduce_evidence


API_KEY_ENV = "OPENAI_API_KEY"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
MAX_TOOL_OUTPUT_CHARS = 12_000
_EVIDENCE_ID_RE = re.compile(r"\b(?:crash|event|network|span|client):[A-Za-z0-9._-]+\b")

SYSTEM_PROMPT = """You are debugging a production incident from runtime evidence only.
Use only the benchmark tools provided to you. Do not use web search or outside knowledge.
Reconstruct the relevant sequence before giving a causal conclusion. Distinguish direct
observations from inference. If evidence is insufficient, say unknown/partial rather than
inventing a cause. Your final answer must cite concrete evidence IDs or precise source
locations that support the conclusion. Keep investigating until the evidence is sufficient
or the tool/turn budget is exhausted."""


def _env_path(name: str) -> Path:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"missing environment variable: {name}")
    return Path(value).resolve()


def _append_event(path: Path, event: Mapping[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(event), ensure_ascii=False, sort_keys=True) + "\n")


def _input_files(root: Path) -> tuple[Path, ...]:
    files = tuple(sorted(path.resolve() for path in root.iterdir() if path.is_file()))
    if not files:
        raise RuntimeError("benchmark input directory is empty")
    return files


def _safe_input(root: Path, name: str) -> Path:
    candidate = (root / Path(str(name)).name).resolve()
    if candidate.parent != root.resolve() or not candidate.is_file():
        raise ValueError(f"unknown input file: {name}")
    return candidate


def _truncate(value: str, limit: int = MAX_TOOL_OUTPUT_CHARS) -> str:
    if len(value) <= limit:
        return value
    suffix = f"\n...[truncated {len(value) - limit} chars]"
    return value[: max(0, limit - len(suffix))] + suffix


def _usage(response: Mapping[str, Any]) -> dict[str, int]:
    raw = response.get("usage")
    if not isinstance(raw, Mapping):
        return {}
    result: dict[str, int] = {}
    for source, target in (("input_tokens", "input_tokens"), ("output_tokens", "output_tokens")):
        value = raw.get(source)
        if isinstance(value, int) and value >= 0:
            result[target] = value
    input_details = raw.get("input_tokens_details")
    if isinstance(input_details, Mapping):
        cached = input_details.get("cached_tokens")
        if isinstance(cached, int) and cached >= 0:
            result["cached_input_tokens"] = cached
    output_details = raw.get("output_tokens_details")
    if isinstance(output_details, Mapping):
        reasoning = output_details.get("reasoning_tokens")
        if isinstance(reasoning, int) and reasoning >= 0:
            result["reasoning_tokens"] = reasoning
    for source, target in (
        ("cache_read_input_tokens", "cache_read_input_tokens"),
        ("cache_creation_input_tokens", "cache_creation_input_tokens"),
    ):
        value = raw.get(source)
        if isinstance(value, int) and value >= 0:
            result[target] = value
    return result


def _visible_text(response: Mapping[str, Any]) -> str:
    chunks: list[str] = []
    output = response.get("output")
    if not isinstance(output, list):
        return ""
    for item in output:
        if not isinstance(item, Mapping) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, Mapping) and part.get("type") == "output_text":
                text = part.get("text")
                if isinstance(text, str):
                    chunks.append(text)
    return "\n".join(chunks).strip()


def _function_calls(response: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    output = response.get("output")
    if not isinstance(output, list):
        return []
    return [
        item
        for item in output
        if isinstance(item, Mapping) and item.get("type") == "function_call"
    ]


def _post_response(payload: Mapping[str, Any]) -> dict[str, Any]:
    api_key = os.environ.get(API_KEY_ENV, "").strip()
    if not api_key:
        raise RuntimeError(f"{API_KEY_ENV} is required for the OpenAI benchmark host")
    base = os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    request = urllib.request.Request(
        f"{base}/responses",
        data=json.dumps(dict(payload)).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "TraceCite-Agent-Benchmark/1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            value = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API HTTP {exc.code}: {body[:2000]}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("OpenAI Responses API returned a non-object payload")
    return value


def _function_tool(name: str, description: str, properties: Mapping[str, Any], required: Sequence[str]) -> dict[str, Any]:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": dict(properties),
            "required": list(required),
            "additionalProperties": False,
        },
    }


def _common_file_property(files: Sequence[Path]) -> dict[str, Any]:
    return {"type": "string", "enum": [path.name for path in files]}


def _tools_for_mode(mode: str, files: Sequence[Path]) -> list[dict[str, Any]]:
    file_property = _common_file_property(files)
    if mode == "shell_rg":
        return [
            _function_tool(
                "rg_search",
                "Regex-search all supplied raw evidence files and return bounded line-numbered context, similar to rg -n -C.",
                {
                    "query": {"type": "string"},
                    "file": {"type": ["string", "null"], "enum": [None, *[p.name for p in files]]},
                    "context": {"type": "integer", "minimum": 0, "maximum": 5},
                    "max_matches": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                ["query", "file", "context", "max_matches"],
            ),
            _function_tool(
                "read_lines",
                "Read a bounded line range from one raw evidence file.",
                {
                    "file": file_property,
                    "start_line": {"type": "integer", "minimum": 1},
                    "end_line": {"type": "integer", "minimum": 1},
                },
                ["file", "start_line", "end_line"],
            ),
        ]
    if mode in {"tracecite", "tracecite_context"}:
        return [
            _function_tool(
                "tracecite_search",
                "Search one evidence source through TraceCite and receive bounded recoverable evidence with Coverage.",
                {
                    "file": file_property,
                    "query": {"type": "string"},
                    "regex": {"type": "boolean"},
                },
                ["file", "query", "regex"],
            )
        ]
    if mode == "tracecite_intelligence":
        return [
            _function_tool(
                "evidence_search",
                "Search provider evidence labels/IDs/attributes. Results are accumulated, correlated, grouped, reduced, and returned as a token-aware EvidencePackage. You choose the next entity to retrieve.",
                {"query": {"type": "string"}},
                ["query"],
            ),
            _function_tool(
                "evidence_entity",
                "Retrieve evidence for one stable entity discovered in prior evidence; then rebuild the correlated token-aware package.",
                {
                    "namespace": {"type": "string"},
                    "kind": {"type": "string"},
                    "value": {"type": "string"},
                },
                ["namespace", "kind", "value"],
            ),
        ]
    if mode == "tracecite_investigate":
        return [
            _function_tool(
                "investigate_runtime_evidence",
                "Run bounded deterministic multi-source exploration from a crash evidence ID. If evidence_id is null and exactly one crash exists, it is selected automatically. Returns a correlated, reduced, citable EvidencePackage and explicit Coverage/stop reason.",
                {"evidence_id": {"type": ["string", "null"]}},
                ["evidence_id"],
            )
        ]
    raise ValueError(f"unsupported benchmark mode: {mode}")


class ToolRuntime:
    def __init__(self, *, mode: str, input_root: Path, scratch: Path, context_id: str) -> None:
        self.mode = mode
        self.input_root = input_root.resolve()
        self.scratch = scratch.resolve()
        self.context_id = context_id
        self.files = _input_files(self.input_root)
        self.providers: tuple[JsonEvidenceProvider, ...] = ()
        self.accumulated: dict[str, ProviderEvidence] = {}
        self.relations: dict[tuple[str, str, str, str, str], EvidenceRelation] = {}
        self.seed_ids: list[str] = []
        if mode in {"tracecite_intelligence", "tracecite_investigate"}:
            self.providers = tuple(JsonEvidenceProvider.from_path(path) for path in self.files)

    def _rg_search(self, args: Mapping[str, Any]) -> str:
        query = str(args.get("query") or "")
        if not query:
            raise ValueError("query must be non-empty")
        regex = re.compile(query, flags=re.IGNORECASE)
        context = int(args.get("context", 2))
        max_matches = int(args.get("max_matches", 20))
        selected = self.files
        if args.get("file"):
            selected = (_safe_input(self.input_root, str(args["file"])),)
        chunks: list[str] = []
        matches = 0
        for path in selected:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            for index, line in enumerate(lines):
                if regex.search(line) is None:
                    continue
                start = max(0, index - context)
                end = min(len(lines), index + context + 1)
                chunks.append(f"== {path.name}:{index + 1} ==")
                chunks.extend(f"{path.name}:{line_no + 1}:{lines[line_no]}" for line_no in range(start, end))
                matches += 1
                if matches >= max_matches:
                    return _truncate("\n".join(chunks))
        return _truncate("\n".join(chunks) if chunks else "NO MATCHES")

    def _read_lines(self, args: Mapping[str, Any]) -> str:
        path = _safe_input(self.input_root, str(args.get("file") or ""))
        start = int(args.get("start_line", 1))
        end = int(args.get("end_line", start))
        if end < start or end - start > 200:
            raise ValueError("invalid/broad line range")
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        start_index = max(0, start - 1)
        end_index = min(len(lines), end)
        return _truncate("\n".join(f"{path.name}:{i + 1}:{lines[i]}" for i in range(start_index, end_index)))

    def _tracecite_search(self, args: Mapping[str, Any]) -> str:
        path = _safe_input(self.input_root, str(args.get("file") or ""))
        query = str(args.get("query") or "")
        if not query:
            raise ValueError("query must be non-empty")
        ledger = self.scratch / "ledger"
        ledger.mkdir(parents=True, exist_ok=True)
        command = [
            sys.executable,
            "-m",
            "tracecite.integrations.stateful_cli",
            "search",
            str(path),
            query,
            "--compact",
            "--ledger-dir",
            str(ledger),
            "--agent-profile",
            "frame",
            "--max-output-chars",
            "6000",
            "--max-evidence",
            "20",
            "--max-line-chars",
            "700",
            "--lightweight",
        ]
        if bool(args.get("regex")):
            command.append("--regex")
        if self.mode == "tracecite_context":
            if not self.context_id:
                raise RuntimeError("tracecite_context requires context_id")
            command.extend(["--context-id", self.context_id])
        completed = subprocess.run(
            command,
            cwd=self.scratch,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
        )
        output = completed.stdout.strip()
        if completed.returncode != 0:
            output = (output + "\n" + completed.stderr.strip()).strip()
        return _truncate(output or "NO OUTPUT")

    def _remember(self, records: Sequence[ProviderEvidence], relations: Sequence[EvidenceRelation]) -> None:
        for record in records:
            self.accumulated.setdefault(record.id, record)
        for relation in relations:
            self.relations.setdefault(relation.identity, relation)

    def _package(self) -> str:
        nodes = tuple(
            EvidenceNode(
                id=item.id,
                kind=item.kind,
                source=item.source,
                timestamp=item.timestamp,
                severity=item.severity,
                label=item.label,
                entities=item.entities,
                evidence_uri=item.evidence_uri,
                attributes=item.attributes,
            )
            for item in self.accumulated.values()
        )
        ids = {node.id for node in nodes}
        active_relations = tuple(
            relation
            for relation in self.relations.values()
            if relation.source_id in ids and relation.target_id in ids
        )
        graph = correlate(nodes, declared_relations=active_relations)
        grouping = group_evidence(graph.nodes)
        reduction = reduce_evidence(
            graph,
            grouping,
            policy=ReductionPolicy(seed_ids=tuple(self.seed_ids), max_items=24),
        )
        package = build_evidence_package(graph, grouping, reduction, max_tokens=2400, recovery_limit=24)
        return _truncate(json.dumps(package.to_dict(), ensure_ascii=False, sort_keys=True))

    def _evidence_search(self, args: Mapping[str, Any]) -> str:
        query = str(args.get("query") or "").casefold().strip()
        if not query:
            raise ValueError("query must be non-empty")
        matches: list[ProviderEvidence] = []
        for provider in self.providers:
            for evidence_id in sorted(provider._by_id):  # benchmark adapter: provider-neutral fixture inspection
                record = provider.get(evidence_id)
                haystack = json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True).casefold()
                if query in haystack:
                    matches.append(record)
        matches = matches[:50]
        if not matches:
            return "NO MATCHES"
        for record in matches:
            if not self.seed_ids and record.kind == "crash":
                self.seed_ids.append(record.id)
        self._remember(matches, ())
        return self._package()

    def _evidence_entity(self, args: Mapping[str, Any]) -> str:
        entity = EntityRef(
            str(args.get("kind") or ""),
            str(args.get("value") or ""),
            namespace=str(args.get("namespace") or ""),
        )
        request = RetrieveRequest(entities=(entity,), limit=100, reason="agent_directed")
        matched: list[ProviderEvidence] = []
        relations: list[EvidenceRelation] = []
        for provider in self.providers:
            if provider.can_handle(request):
                result = provider.retrieve(request)
                matched.extend(result.evidence)
                relations.extend(result.relations)
        self._remember(matched, relations)
        return self._package() if matched else "NO MATCHES"

    def _investigate(self, args: Mapping[str, Any]) -> str:
        evidence_id = args.get("evidence_id")
        seed = str(evidence_id or "").strip()
        if not seed:
            crashes: list[str] = []
            for provider in self.providers:
                for candidate in sorted(provider._by_id):
                    if provider.get(candidate).kind == "crash":
                        crashes.append(candidate)
            if len(crashes) != 1:
                return json.dumps({"status": "needs_seed", "crash_candidates": crashes}, ensure_ascii=False)
            seed = crashes[0]
        result = investigate(
            self.providers,
            seed_evidence_ids=(seed,),
            exploration_policy=TraversalLimits(max_depth=3, max_retrievals=20, max_no_growth_rounds=4),
            reduction_policy=ReductionPolicy(seed_ids=(seed,), max_items=24),
            max_tokens=2400,
            recovery_limit=24,
        )
        return _truncate(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))

    def call(self, name: str, args: Mapping[str, Any]) -> str:
        if name == "rg_search" and self.mode == "shell_rg":
            return self._rg_search(args)
        if name == "read_lines" and self.mode == "shell_rg":
            return self._read_lines(args)
        if name == "tracecite_search" and self.mode in {"tracecite", "tracecite_context"}:
            return self._tracecite_search(args)
        if name == "evidence_search" and self.mode == "tracecite_intelligence":
            return self._evidence_search(args)
        if name == "evidence_entity" and self.mode == "tracecite_intelligence":
            return self._evidence_entity(args)
        if name == "investigate_runtime_evidence" and self.mode == "tracecite_investigate":
            return self._investigate(args)
        raise ValueError(f"tool {name!r} is not available in mode {self.mode!r}")


def run() -> int:
    mode = os.environ.get("TRACECITE_BENCH_MODE", "").strip()
    model = os.environ.get("TRACECITE_BENCH_MODEL", "").strip()
    question_path = _env_path("TRACECITE_BENCH_QUESTION")
    input_root = _env_path("TRACECITE_BENCH_INPUTS")
    scratch = _env_path("TRACECITE_BENCH_SCRATCH")
    transcript = _env_path("TRACECITE_BENCH_TRANSCRIPT")
    context_id = os.environ.get("TRACECITE_BENCH_CONTEXT_ID", "").strip()
    if not model:
        raise RuntimeError("TRACECITE_BENCH_MODEL is required")

    runtime = ToolRuntime(mode=mode, input_root=input_root, scratch=scratch, context_id=context_id)
    tools = _tools_for_mode(mode, runtime.files)
    question = question_path.read_text(encoding="utf-8")
    file_names = ", ".join(path.name for path in runtime.files)
    prompt = f"{question}\n\nAvailable evidence files: {file_names}."
    conversation: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    max_turns = int(os.environ.get("TRACECITE_BENCH_MAX_TURNS", "10"))
    if max_turns < 1 or max_turns > 30:
        raise ValueError("TRACECITE_BENCH_MAX_TURNS must be 1-30")

    final_text = ""
    for round_index in range(1, max_turns + 1):
        response = _post_response(
            {
                "model": model,
                "instructions": SYSTEM_PROMPT,
                "input": conversation,
                "tools": tools,
                "tool_choice": "auto",
                "store": False,
            }
        )
        visible = _visible_text(response)
        event: dict[str, Any] = {
            "type": "model",
            "round": round_index,
            "content": visible,
        }
        usage = _usage(response)
        if usage:
            event["usage"] = usage
        event["provider_response_id"] = response.get("id")
        _append_event(transcript, event)

        output_items = response.get("output")
        if isinstance(output_items, list):
            conversation.extend(item for item in output_items if isinstance(item, dict))

        calls = _function_calls(response)
        if not calls:
            final_text = visible
            break

        for call in calls:
            name = str(call.get("name") or "")
            call_id = str(call.get("call_id") or "")
            raw_arguments = call.get("arguments")
            args: dict[str, Any] = {}
            try:
                decoded = json.loads(raw_arguments) if isinstance(raw_arguments, str) else {}
                if not isinstance(decoded, dict):
                    raise ValueError("tool arguments must decode to an object")
                args = decoded
                started = time.monotonic()
                output = runtime.call(name, args)
                duration_ms = round((time.monotonic() - started) * 1000, 3)
            except Exception as exc:
                output = json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False)
                duration_ms = 0.0
            output = _truncate(output)
            _append_event(
                transcript,
                {
                    "type": "tool",
                    "round": round_index,
                    "tool": name,
                    "input": args,
                    "output": output,
                    "duration_ms": duration_ms,
                },
            )
            conversation.append({"type": "function_call_output", "call_id": call_id, "output": output})
    else:
        final_text = "Investigation stopped because the model-turn budget was exhausted."

    evidence = sorted(set(_EVIDENCE_ID_RE.findall(final_text)))
    _append_event(transcript, {"type": "final", "answer": final_text, "evidence": evidence})
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except Exception as exc:
        transcript_value = os.environ.get("TRACECITE_BENCH_TRANSCRIPT", "").strip()
        if transcript_value:
            try:
                _append_event(Path(transcript_value), {"type": "host_error", "error": type(exc).__name__, "message": str(exc)})
            except Exception:
                pass
        print(f"benchmark host failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
