from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import benchmarking as legacy
from . import root_cause_benchmarking as root_eval

SUITE_SCHEMA_VERSION = 1
SUITE_ID = "github-root-cause-30"
ROOT_CAUSE_DIMENSIONS = root_eval.ROOT_CAUSE_DIMENSIONS
QUESTION = """Investigate the failure using only the provided evidence files.

Determine:
1. where the failure is localized,
2. the immediate failure mechanism,
3. the upstream contributing condition or regression,
4. the corrective change that best aligns with the evidence.

Cite exact evidence line numbers for the important claims. Do not assume access to maintainer diagnosis, linked fix PRs, or evaluator truth.
"""
DEFAULT_THRESHOLDS = {
    "dimension_recall": 0.75,
    "citation_accuracy": 0.5,
    "evidence_marker_recall": 0.0,
    "max_unsupported_claim_hits": 0,
    "max_contradiction_hits": 0,
}
# row = id, cohort, source, failure_localization, immediate_failure_mechanism,
#       upstream_contributor, fix_alignment
_CASE_ROWS = [
  ["doublecmd-2264", "strict", "existing:benchmarks/agent-investigation/cases/doublecmd-2264", "(?:(wfx|sftp).*(settings|wfx\\.ini)|wfx\\.ini)", "(?:EFCreateError|cannot create|permission|read.?only)", "(?:/usr/share/doublecmd/settings|root.?owned|installation.*directory)", "(?:user.?writable|writable.*settings|move.*settings|configuration.*directory)"],
  ["doublecmd-2616", "strict", "existing:benchmarks/agent-investigation/cases/doublecmd-2616", "(?:ZIP.*WCX|WCX.*ZIP|archive.*plugin)", "(?:access violation|plugin.*(initiali[sz]|lifetime)|invalid.*plugin)", "(?:bundled.*ZIP.*plugin|WCX.*(state|lifetime|initiali[sz]))", "(?:(fix|correct).*(ZIP|WCX).*(plugin|initiali[sz]|lifetime)|plugin.*lifetime)"],
  ["doublecmd-2731", "strict", "existing:benchmarks/agent-investigation/cases/doublecmd-2731", "(?:File Associations|file association.*icon|icon.*(path|filename))", "(?:access violation|path.*par(s|sing)|filename.*par(s|sing))", "(?:[:/].*(icon|path)|(icon|path).*(colon|slash|[:/]))", "(?:validate.*(icon|path)|safe.*par(s|sing)|handle.*(colon|slash|path))"],
  ["doublecmd-2772", "strict", "existing:benchmarks/agent-investigation/cases/doublecmd-2772", "(?:grid|widget.*startup|grids\\.pas)", "(?:EConvertError|invalid.*format|convert.*error)", "(?:(form|resource|property|default).*(grid|widget)|grid.*(property|resource))", "(?:(correct|validate|default).*(grid|property|resource)|resource.*fix)"],
  ["doublecmd-2777", "strict", "existing:benchmarks/agent-investigation/cases/doublecmd-2777", "(?:File Associations|extassoc\\.xml|Qt6)", "(?:EAccessViolation|access violation)", "(?:(persisted|saved).*(file association|extassoc)|extassoc\\.xml.*(state|config))", "(?:(sanitize|reset|validate|fix).*(extassoc|file association|config)|load.*saf)"],
  ["doublecmd-2809", "strict", "existing:benchmarks/agent-investigation/cases/doublecmd-2809", "(?:ChildSizing\\.EnlargeVertical|form.*resource|startup)", "(?:(invalid|unknown).*(property|resource)|deseriali[sz])", "(?:shipped.*(form|resource)|ChildSizing\\.EnlargeVertical)", "(?:(remove|correct|fix).*(ChildSizing|resource|property))"],
  ["doublecmd-2815", "reporter_hypothesis", "existing:benchmarks/agent-investigation/cases/doublecmd-2815", "(?:\\bF3\\b|viewer|macOS.*viewer)", "(?:viewer.*(fail|regression|not.*open)|F3.*(fail|regression))", "(?:revision.*regression|macOS.*viewer.*regression)", "(?:(restore|fix).*(viewer|F3)|viewer.*regression)"],
  ["doublecmd-3061", "strict", "existing:benchmarks/agent-investigation/cases/doublecmd-3061", "(?:YAML.*highlighter|syntax.*highlight)", "(?:access violation|out.?of.?bounds|parser.*(crash|violation))", "(?:(escaped|backslash).*(YAML|scalar|string)|YAML.*(escape|backslash))", "(?:(bound|safe|fix).*(YAML|highlighter|parser)|handle.*escape)"],
  ["flutter-179398", "strict", "existing:benchmarks/agent-investigation/cases/flutter-179398", "(?:Impeller.*RoundSuperellipse|RoundSuperellipse|DrawCircularArc)", "(?:memory corruption|EXC_BAD_ACCESS|SIGSEGV|invalid.*memory)", "(?:(round.?superellipse|circular arc).*(geometry|tessell|generation)|geometry.*corrupt)", "(?:(fix|correct).*(RoundSuperellipse|DrawCircularArc|arc|geometry)|e09862d)"],
  ["kubernetes-140848", "strict", "existing:benchmarks/agent-investigation/cases/kubernetes-140848", "(?:kubelet.*(default|config)|PodLevelResourcesFixDefaulting)", "(?:panic|nil pointer|nil dereference)", "(?:PodLevelResourcesFixDefaulting.*(enabled|true).*(PodLevelResources.*(disabled|false))|feature.?gate.*depend)", "(?:(enforce|fix|validate).*(feature.?gate|PodLevelResources)|dependency.*gate)"],
  ["prometheus-18018", "strict", "existing:benchmarks/agent-investigation/cases/prometheus-18018", "(?:PromQL|predict_linear|range function)", "(?:empty.*(vector|matrix).*(index|panic)|index.*out of range)", "(?:@ modifier.*(no data|empty)|range.*function.*empty)", "(?:(guard|handle|check).*(empty|zero).*(vector|matrix)|range function.*empty)"],
  ["pulumi-20529", "strict", "existing:benchmarks/agent-investigation/cases/pulumi-20529", "(?:provider.*(Update|Check|Diff)|provider lifecycle)", "(?:race|unexpected.*Update|Update.*without.*(Check|Diff)|state.*mismatch)", "(?:(replacement|removal).*(overlap|concurr)|provider.*(replace|remove).*(update|race))", "(?:(seriali[sz]|synchroni[sz]|order|fix).*(provider|Update|replacement)|provider.*lifecycle.*fix)"],
  ["pulumi-14231", "strict", "github:pulumi/pulumi#14231#14234", "(?:PCL.*binder|bind.*(invoke|signature)|invoke.*signature)", "(?:panic.*(output.?versioned|invoke)|nil.*(argument|args)|no arguments)", "(?:output.?versioned.*invoke.*(without|no).*arg|missing.*argument.*binding)", "(?:handle.*(no|zero).*(arg|argument)|bind.*signature.*without.*arg)"],
  ["pulumi-21700", "strict", "github:pulumi/pulumi#21700#21815", "(?:refresh.*run-program|refresh step|snapshot|journal)", "(?:assert|missing.*new.*resource|step.*completion.*early|race)", "(?:(completion|completion source).*(before|early).*(step|snapshot)|refresh.*race)", "(?:fulfill.*completion.*complete|complete function.*(completion|fulfill)|wait.*step.*complete)"],
  ["flutter-167887", "strict", "github:flutter/flutter#167887#167954", "(?:Flutter.*tool|WASM|web.*build|late variable)", "(?:late.*(not.*assign|unassign|initiali)|LateInitializationError)", "(?:WASM.*(enabled|path).*(late|assignment)|regression.*165006)", "(?:assign.*late.*WASM|initiali[sz].*late.*WASM|fix.*WASM.*assignment)"],
  ["flutter-190799", "reporter_hypothesis", "github:flutter/flutter#190799#190819", "(?:native asset|NativeAssetsManifest|dlopen|framework)", "(?:(second|two).*(copy|mapping)|SIGSEGV|EXC_BAD_ACCESS|stale.*handle)", "(?:@rpath.*(manifest|install name).*(mismatch|different)|install name.*manifest.*mismatch)", "(?:frameworkInstallName|record.*install name|manifest.*@rpath|same.*install name)"],
  ["otel-collector-13117", "strict", "github:open-telemetry/opentelemetry-collector#13117#13118", "(?:confmap|map.*assign)", "(?:panic.*nil.*map|assign.*nil.*map|nil map)", "(?:nil.*map.*non.?nil|map.*assignment.*nil)", "(?:(guard|handle|allow).*(nil map)|prevent.*nil.*map.*panic)"],
  ["otel-contrib-24908", "strict", "github:open-telemetry/opentelemetry-collector-contrib#24908#24979", "(?:Datadog.*metrics.*exporter|metrics exporter)", "(?:panic.*multiple exporters|concurrent.*mutat|data.*race)", "(?:MutatesData.*(false|missing|not.*set)|capabilit.*MutatesData)", "(?:MutatesData.*true|set.*capabilit.*metrics exporter)"],
  ["otel-contrib-16469", "strict", "github:open-telemetry/opentelemetry-collector-contrib#16469#16470", "(?:Prometheus receiver.*Shutdown|prometheusreceiver.*shutdown)", "(?:panic.*shutdown|nil.*(cancelFunc|scrapeManager)|nil pointer)", "(?:(cancelFunc|scrapeManager).*(nil|not.*initiali)|shutdown.*before.*start)", "(?:nil.?check.*(cancelFunc|scrapeManager)|guard.*Shutdown)"],
  ["envoy-43513", "strict", "github:envoyproxy/envoy#43513#43526", "(?:peak.?ewma|Peak EWMA|load balancer)", "(?:isThreadSafe|thread.?safety.*(assert|violation)|segfault)", "(?:createTimer.*worker|timer.*dispatcher.*owning thread|Event::Dispatcher.*worker)", "(?:remove.*timer|inline.*aggregation.*chooseHost|avoid.*dispatcher.*timer)"],
  ["envoy-7154", "strict", "github:envoyproxy/envoy#7154#7192", "(?:router.*response timeout|upstream.*timeout)", "(?:null pointer.*(body|trailer|decode)|crash.*after.*headers)", "(?:retry hedging.*reset|upstream request.*not.*reset.*headers)", "(?:reset.*upstream.*response timeout|restore.*reset.*after.*headers)"],
  ["containerd-8742", "strict", "github:containerd/containerd#8742#8748", "(?:docker\\.NewResolver|NewResolver|resolver\\.go)", "(?:DATA RACE|race condition|concurrent.*map)", "(?:NewResolver.*map.*(read|access)|shared.*map.*without.*lock)", "(?:(lock|copy|synchroni[sz]).*(map|header|resolver)|resolve.*race)"],
  ["containerd-10062", "strict", "github:containerd/containerd#10062#10133", "(?:introspectRuntimeFeatures|CRI.*runtime features)", "(?:nil.*panic|nil pointer|MarshalAnyToProto.*nil)", "(?:options.*nil.*MarshalAnyToProto|PluginInfo.*options.*nil)", "(?:if.*options.*nil|guard.*options|skip.*marshal.*nil)"],
  ["containerd-4795", "strict", "github:containerd/containerd#4795#4855", "(?:docker.*(resolver|push|registry)|remotes/docker)", "(?:concurrent map access|concurrent map (read|write)|panic)", "(?:shared.*map.*concurrent|map.*without.*(lock|copy))", "(?:(copy|lock|synchroni[sz]).*map|avoid.*concurrent.*map)"],
  ["kubernetes-39480", "strict", "github:kubernetes/kubernetes#39480#39493", "(?:kubelet.*volume type|volume.*type check|VolumeSpec)", "(?:nil deref|nil pointer|panic)", "(?:PersistentVolume.*Volume.*nil|VolumeSpec.*(Volume|PersistentVolume).*not.*both)", "(?:only.*local.*(volume|temporal)|avoid.*PV.*memory|nil.?check.*PersistentVolume)"],
  ["kubernetes-86676", "reporter_hypothesis", "github:kubernetes/kubernetes#86676#86689", "(?:CPUManager.*checkpoint|CPUManagerCheckpoint)", "(?:checksum.*(mismatch|corrupt)|checkpoint.*corrupt)", "(?:CPUManagerCheckpointV1.*type name|checksum.*type.*name|migration.*V1.*V2)", "(?:checksum.*CPUManagerCheckpoint(?!V1)|lock.*checksum.*pre.?1\\.18|verify.*V1.*original.*type)"],
  ["argocd-25189", "strict", "github:argoproj/argo-cd#25189#25192", "(?:cluster cache.*listResources|resource.*list|pager)", "(?:panic.*nil|nil.*UnstructuredList|GetContinue.*nil)", "(?:List.*return.*nil.*error|res.*nil.*error)", "(?:empty.*UnstructuredList|ensure.*res.*not.*nil|return.*empty list)"],
  ["argocd-18020", "strict", "github:argoproj/argo-cd#18020#18840", "(?:server-side diff|server-side apply|gvkParser)", "(?:panic.*nil.*gvkParser|nil.*gvkParser|incorrect.*diff)", "(?:gvkParser.*not.*initiali|server-side.*diff.*parser)", "(?:initiali[sz].*gvkParser|fix.*server-side.*diff.*parser)"],
  ["argocd-7898", "strict", "github:argoproj/argo-cd#7898#11805", "(?:repo-server|git.*checkout|index\\.lock)", "(?:index\\.lock.*exists|git.*locked|checkout.*timeout)", "(?:SIGKILL.*ARGOCD_EXEC_TIMEOUT|unclean.*checkout.*SIGKILL|git.*killed.*lock)", "(?:SIGTERM.*wait.*git.*exit|clean.*checkout.*before.*continue|graceful.*terminate)"],
  ["prometheus-19432", "reporter_hypothesis", "github:prometheus/prometheus#19432#19433", "(?:rules.*FileLoader|rulefmt\\.Parse|LoadGroups)", "(?:nil.*logger.*panic|slog.*Logger.*nil|nil pointer)", "(?:default.*FileLoader.*capture.*logger.*before.*default|Logger.*default.*after.*FileLoader)", "(?:default.*logger.*before.*FileLoader|move.*logger.*default.*earlier|NewNopLogger.*before)"],
]


def _parse_source(spec: str) -> dict[str, Any]:
    if spec.startswith("existing:"):
        return {"kind": "existing_case", "path": spec[len("existing:"):]}
    if not spec.startswith("github:"):
        raise ValueError(f"unsupported source: {spec}")
    value = spec[len("github:"):]
    repo, issue, fix = value.rsplit("#", 2)
    return {"kind": "github_issue", "repo": repo, "number": int(issue), "fix_pr": int(fix)}


def suite_cases() -> list[dict[str, Any]]:
    result = []
    for row in _CASE_ROWS:
        case_id, cohort, source_spec, *patterns = row
        if len(patterns) != len(ROOT_CAUSE_DIMENSIONS):
            raise ValueError(f"{case_id}: invalid root-cause rubric")
        source = _parse_source(source_spec)
        root_cause = {
            dimension: {"patterns": [pattern]}
            for dimension, pattern in zip(ROOT_CAUSE_DIMENSIONS, patterns, strict=True)
        }
        item = {"id": case_id, "cohort": cohort, "source": source, "root_cause": root_cause}
        if source["kind"] == "github_issue":
            repo = source["repo"]
            item["source_issue"] = f"https://github.com/{repo}/issues/{source['number']}"
            item["fix_reference"] = f"https://github.com/{repo}/pull/{source['fix_pr']}"
        result.append(item)
    return result


def _case_map() -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in suite_cases()}


def validate_suite(repo_root: Path) -> dict[str, Any]:
    cases = suite_cases()
    if len(cases) != 30:
        raise ValueError(f"{SUITE_ID} must contain exactly 30 cases, got {len(cases)}")
    ids = [item["id"] for item in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("suite contains duplicate case ids")
    cohorts = Counter()
    projects = Counter()
    for item in cases:
        cohort = str(item["cohort"])
        if cohort not in {"strict", "reporter_hypothesis", "partial_fix"}:
            raise ValueError(f"{item['id']}: unsupported cohort {cohort}")
        cohorts[cohort] += 1
        root_eval.validate_gold({"root_cause_schema_version": 1, "root_cause": item["root_cause"]})
        source = item["source"]
        if source["kind"] == "existing_case":
            path = (repo_root / source["path"]).resolve()
            if not path.is_dir():
                raise ValueError(f"{item['id']}: missing existing case {path}")
            legacy.validate_case(path)
            case_json = json.loads((path / "case.json").read_text(encoding="utf-8"))
            project = str((case_json.get("provenance") or {}).get("project") or item["id"].split("-", 1)[0])
        else:
            project = str(source["repo"])
        projects[project] += 1
    return {"status": "ok", "schema_version": SUITE_SCHEMA_VERSION, "suite_id": SUITE_ID, "cases": len(cases), "cohorts": dict(sorted(cohorts.items())), "projects": dict(sorted(projects.items()))}


def _http_json(url: str) -> Mapping[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "TraceCite-Root-Cause-Benchmark/1"})
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = json.load(response)
    if not isinstance(payload, Mapping):
        raise ValueError(f"expected JSON object from {url}")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _generic_gold(item: Mapping[str, Any]) -> dict[str, Any]:
    return {"root_cause_schema_version": 1, "root_cause": item["root_cause"], "evidence_markers": [], "unsupported_claims": [], "contradictions": [], "root_cause_thresholds": dict(DEFAULT_THRESHOLDS), "leak_terms": []}


def _project_for_existing(case_payload: Mapping[str, Any], case_id: str) -> str:
    project = (case_payload.get("provenance") or {}).get("project")
    return str(project or case_id.split("-", 1)[0])


def _materialize_existing(item: Mapping[str, Any], repo_root: Path, work_dir: Path, generated_dir: Path) -> dict[str, Any]:
    source_dir = (repo_root / str(item["source"]["path"])).resolve()
    source_case = json.loads((source_dir / "case.json").read_text(encoding="utf-8"))
    prepared = legacy.prepare_case(source_dir, work_dir / "prepared")
    case_id = str(item["id"])
    generated = generated_dir / case_id
    generated.mkdir(parents=True, exist_ok=True)
    (generated / "question.md").write_text(QUESTION, encoding="utf-8")
    source_issue = source_case.get("source_issue")
    fix_reference = source_case.get("fix_reference")
    case_payload = {"schema_version": 1, "id": case_id, "title": source_case.get("title") or case_id, "source_issue": source_issue, "fix_reference": fix_reference, "question_file": "question.md", "gold_file": "gold.json", "inputs": source_case["inputs"], "provenance": {"project": _project_for_existing(source_case, case_id), "cohort": item["cohort"], "source_kind": "existing_case", "reporter_only_evidence": True}}
    _write_json(generated / "case.json", case_payload)
    _write_json(generated / "gold.json", _generic_gold(item))
    root_eval.validate_case(generated)
    return {"id": case_id, "cohort": item["cohort"], "project": case_payload["provenance"]["project"], "case_dir": str(generated), "prepared_manifest": str(prepared["manifest"]), "source_issue": source_issue, "fix_reference": fix_reference}


def _materialize_github(item: Mapping[str, Any], work_dir: Path, generated_dir: Path) -> dict[str, Any]:
    source = item["source"]
    repo = str(source["repo"])
    number = int(source["number"])
    api_url = f"https://api.github.com/repos/{repo}/issues/{number}"
    issue = _http_json(api_url)
    if issue.get("pull_request"):
        raise ValueError(f"{item['id']}: source number resolves to a pull request")
    body = str(issue.get("body") or "")
    title = str(issue.get("title") or f"{repo}#{number}")
    snapshot_text = f"# {title}\n\n{body.rstrip()}\n"
    case_id = str(item["id"])
    snapshot = work_dir / "snapshots" / case_id / "issue.md"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text(snapshot_text, encoding="utf-8")
    digest = _sha256(snapshot)
    generated = generated_dir / case_id
    generated.mkdir(parents=True, exist_ok=True)
    (generated / "question.md").write_text(QUESTION, encoding="utf-8")
    input_spec = {"id": "reporter-issue", "url": api_url, "filename": "issue.md", "sha256": digest, "required": True}
    case_payload = {"schema_version": 1, "id": case_id, "title": title, "source_issue": item["source_issue"], "fix_reference": item["fix_reference"], "question_file": "question.md", "gold_file": "gold.json", "inputs": [input_spec], "provenance": {"project": repo, "cohort": item["cohort"], "source_kind": "github_issue_body", "reporter_only_evidence": True, "issue_updated_at": issue.get("updated_at"), "snapshot_sha256": digest}}
    _write_json(generated / "case.json", case_payload)
    _write_json(generated / "gold.json", _generic_gold(item))
    root_eval.validate_case(generated)
    prepared_root = work_dir / "prepared" / case_id
    prepared_input = prepared_root / "inputs" / "issue.md"
    prepared_input.parent.mkdir(parents=True, exist_ok=True)
    prepared_input.write_bytes(snapshot.read_bytes())
    prepared_manifest = prepared_root / "prepared.json"
    _write_json(prepared_manifest, {"schema_version": 1, "case_id": case_id, "question": str((generated / "question.md").resolve()), "inputs": [{"id": "reporter-issue", "path": str(prepared_input.resolve()), "bytes": prepared_input.stat().st_size, "sha256": digest, "source_url": item["source_issue"]}]})
    return {"id": case_id, "cohort": item["cohort"], "project": repo, "case_dir": str(generated), "prepared_manifest": str(prepared_manifest), "source_issue": item["source_issue"], "fix_reference": item["fix_reference"], "snapshot_sha256": digest, "issue_updated_at": issue.get("updated_at")}


def materialize_suite(repo_root: Path, work_dir: Path, case_ids: Iterable[str] | None = None) -> dict[str, Any]:
    validate_suite(repo_root)
    selected = set(case_ids or [])
    known = _case_map()
    unknown = selected - set(known)
    if unknown:
        raise ValueError(f"unknown case ids: {', '.join(sorted(unknown))}")
    work_dir.mkdir(parents=True, exist_ok=True)
    generated_dir = work_dir / "cases"
    rows = []
    for item in suite_cases():
        if selected and item["id"] not in selected:
            continue
        row = _materialize_existing(item, repo_root, work_dir, generated_dir) if item["source"]["kind"] == "existing_case" else _materialize_github(item, work_dir, generated_dir)
        rows.append(row)
    index = {"schema_version": SUITE_SCHEMA_VERSION, "suite_id": SUITE_ID, "cases": rows}
    index_path = work_dir / "suite-index.json"
    _write_json(index_path, index)
    return {**index, "index": str(index_path)}


def _last_host_reason(transcript: Path) -> str:
    if not transcript.is_file():
        return "host_error"
    reason = "host_error"
    with transcript.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, Mapping) and event.get("type") == "host_error":
                reason = str(event.get("failure_reason") or event.get("error") or "host_error")
    return reason


def _infra_reason(reason: str) -> bool:
    return reason in {"provider_insufficient_balance", "provider_rate_limited", "provider_unavailable"}


def run_suite(repo_root: Path, work_dir: Path, output_dir: Path, *, mode: str, model: str, host: Path, timeout_seconds: int, case_ids: Iterable[str] | None = None) -> dict[str, Any]:
    materialized = materialize_suite(repo_root, work_dir, case_ids)
    output_dir.mkdir(parents=True, exist_ok=True)
    runs_dir = output_dir / "runs"
    scores_dir = output_dir / "scores"
    failures_dir = output_dir / "failures"
    runs_dir.mkdir(exist_ok=True)
    scores_dir.mkdir(exist_ok=True)
    failures_dir.mkdir(exist_ok=True)
    completed = passed = quality_failed = host_failed = infra_inconclusive = 0
    for row in materialized["cases"]:
        case_id = row["id"]
        transcript = runs_dir / f"{case_id}-{mode}.jsonl"
        command = [sys.executable, str(repo_root / "benchmarks/agent-investigation/run_host.py"), row["case_dir"], row["prepared_manifest"], "--mode", mode, "--model", model, "--seed", "1", "--timeout-seconds", str(timeout_seconds), "--output", str(transcript), "--pass-env", "OPENAI_API_KEY", "--pass-env", "OPENAI_BASE_URL", "--pass-env", "TRACECITE_BENCH_MAX_OUTPUT_TOKENS", "--", sys.executable, str(host)]
        proc = subprocess.run(command, cwd=repo_root, check=False)
        if proc.returncode != 0:
            reason = _last_host_reason(transcript)
            payload = {"case_id": case_id, "mode": mode, "stage": "host", "reason": reason, "returncode": proc.returncode, "cohort": row["cohort"], "project": row["project"]}
            _write_json(failures_dir / f"{case_id}-{mode}.json", payload)
            if _infra_reason(reason):
                infra_inconclusive += 1
            else:
                host_failed += 1
            continue
        score = root_eval.score_transcript(Path(row["case_dir"]), transcript)
        score["cohort"] = row["cohort"]
        _write_json(scores_dir / f"{case_id}-{mode}.json", score)
        completed += 1
        if score["passed"]:
            passed += 1
        else:
            quality_failed += 1
    summary = aggregate_results(output_dir, mode=mode)
    summary.update({"requested": len(materialized["cases"]), "completed": completed, "passed": passed, "quality_failed": quality_failed, "host_failed": host_failed, "infra_inconclusive": infra_inconclusive})
    _write_json(output_dir / "batch-summary.json", summary)
    return summary


def aggregate_results(output_dir: Path, *, mode: str | None = None) -> dict[str, Any]:
    scores = []
    scores_dir = output_dir / "scores"
    if scores_dir.is_dir():
        for path in sorted(scores_dir.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if mode and payload.get("mode") != mode:
                continue
            scores.append(payload)
    failures = []
    failures_dir = output_dir / "failures"
    if failures_dir.is_dir():
        for path in sorted(failures_dir.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if mode and payload.get("mode") != mode:
                continue
            failures.append(payload)
    cases = _case_map()
    by_cohort: dict[str, dict[str, Any]] = {}
    for cohort in sorted({item["cohort"] for item in cases.values()}):
        cohort_scores = [s for s in scores if cases.get(str(s.get("case_id")), {}).get("cohort") == cohort]
        cohort_failures = [f for f in failures if cases.get(str(f.get("case_id")), {}).get("cohort") == cohort]
        requested = sum(1 for item in cases.values() if item["cohort"] == cohort)
        by_cohort[cohort] = {"requested": requested, "scored": len(cohort_scores), "passed": sum(bool(s.get("passed")) for s in cohort_scores), "host_failures": len(cohort_failures), "pass_rate_scored": round(sum(bool(s.get("passed")) for s in cohort_scores) / len(cohort_scores), 4) if cohort_scores else None, "mean_dimension_recall": round(sum(float((s.get("quality") or {}).get("dimension_recall", 0.0)) for s in cohort_scores) / len(cohort_scores), 4) if cohort_scores else None, "mean_citation_accuracy": round(sum(float(((s.get("quality") or {}).get("citation") or {}).get("accuracy", 0.0)) for s in cohort_scores) / len(cohort_scores), 4) if cohort_scores else None}
    reasons = Counter(str(f.get("reason") or "host_error") for f in failures)
    return {"schema_version": SUITE_SCHEMA_VERSION, "suite_id": SUITE_ID, "mode": mode, "scores": len(scores), "score_passed": sum(bool(s.get("passed")) for s in scores), "failures": len(failures), "failure_reasons": dict(sorted(reasons.items())), "cohorts": by_cohort, "reported_input_tokens": sum(int((s.get("context_cost") or {}).get("reported_input_tokens") or 0) for s in scores), "reported_output_tokens": sum(int((s.get("context_cost") or {}).get("reported_output_tokens") or 0) for s in scores), "tool_output_chars": sum(int((s.get("context_cost") or {}).get("tool_output_chars") or 0) for s in scores), "cumulative_attempted_context_chars": sum(int((s.get("context_cost") or {}).get("cumulative_attempted_context_chars") or 0) for s in scores), "peak_attempted_context_chars": max([int((s.get("context_cost") or {}).get("peak_attempted_context_chars") or 0) for s in scores] or [0])}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TraceCite 30-case real GitHub root-cause suite")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--repo-root", type=Path, default=Path.cwd())
    materialize = sub.add_parser("materialize")
    materialize.add_argument("--repo-root", type=Path, default=Path.cwd())
    materialize.add_argument("--work-dir", type=Path, required=True)
    materialize.add_argument("--case-id", action="append", default=[])
    run = sub.add_parser("run")
    run.add_argument("--repo-root", type=Path, default=Path.cwd())
    run.add_argument("--work-dir", type=Path, required=True)
    run.add_argument("--output-dir", type=Path, required=True)
    run.add_argument("--mode", choices=("tracecite", "free_shell"), required=True)
    run.add_argument("--model", required=True)
    run.add_argument("--host", type=Path, required=True)
    run.add_argument("--timeout-seconds", type=int, default=600)
    run.add_argument("--case-id", action="append", default=[])
    aggregate = sub.add_parser("aggregate")
    aggregate.add_argument("--output-dir", type=Path, required=True)
    aggregate.add_argument("--mode", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate":
            payload = validate_suite(args.repo_root.resolve())
        elif args.command == "materialize":
            payload = materialize_suite(args.repo_root.resolve(), args.work_dir.resolve(), args.case_id or None)
        elif args.command == "run":
            payload = run_suite(args.repo_root.resolve(), args.work_dir.resolve(), args.output_dir.resolve(), mode=args.mode, model=args.model, host=args.host.resolve(), timeout_seconds=args.timeout_seconds, case_ids=args.case_id or None)
        else:
            payload = aggregate_results(args.output_dir.resolve(), mode=args.mode)
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
