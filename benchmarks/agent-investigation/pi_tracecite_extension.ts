// Thin Pi extension entrypoint. The implementation lives next to this file so the
// public Host surface and architecture contract remain explicit and easy to audit.
// Host convergence feedback never chooses hypotheses or stopping; the Agent owns both.
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
// Strict benchmark evidence boundary (enabled only with TRACECITE_BENCHMARK_MODE=tracecite):
// native read/grep/find/ls/bash access to runtime evidence is blocked before execution.

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import traceciteTools from "./pi_tracecite_extension_impl.ts";
import strictEvidenceBoundary from "./pi_strict_evidence_boundary.ts";

export default function traceciteExtension(pi: ExtensionAPI) {
  strictEvidenceBoundary(pi);
  traceciteTools(pi);
}
