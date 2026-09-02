// Thin Pi extension entrypoint. The implementation lives next to this file so the
// public Host surface and architecture contract remain explicit and easy to audit.
// Runtime TraceCite results carry evidence and mechanical transport metadata only.
// Investigation strategy may live in the Agent/skill layer; hypotheses, meaning and
// stopping are never selected by the TraceCite runtime.
//
// Canonical surface declarations retained here for architecture/regression checks:
// name: "tracecite_retrieve"
// name: "tracecite_materialize"
// name: "tracecite_replay"
// name: "tracecite_aggregate"
// name: "tracecite_traverse"
// name: "tracecite_verify"
// name: "tracecite_search"
// name: "tracecite_expand"
// rangeArgs("replay", p)
//
// Host telemetry contract:
// pi.on("tool_call"
// pi.on("tool_result"
// tool === "grep"
// tool === "read"
// tool === "bash"
// return "opaque_shell"
// metadata: event.toolName === "bash" ? { opaque: true }
// TRACECITE_PI_ACTIVITY
//
// Evidence guard:
// - benchmark: TRACECITE_BENCHMARK_MODE=tracecite forces strict evidence isolation;
// - product: an explicit user request such as "用 tracecite" / "use tracecite" activates
//   the same native-evidence guard for that Pi agent run when an evidence root is configured.

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import traceciteTools from "./pi_tracecite_extension_impl.ts";
import traceciteEvidenceGuard from "./pi_strict_evidence_boundary.ts";

export default function traceciteExtension(pi: ExtensionAPI) {
  traceciteEvidenceGuard(pi);
  traceciteTools(pi);
}
