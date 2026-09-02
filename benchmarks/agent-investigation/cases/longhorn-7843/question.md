# Investigation question

A Longhorn single-node cluster detects an RWO volume filesystem becoming read-only. Longhorn's auto-remount logic deletes the workload pod so Kubernetes can recreate it, but the replacement pods keep cycling and the volume remains read-only instead of recovering.

The supplied files are the complete `longhorn-manager` log and complete Longhorn CSI plugin log from the original support bundle. Use only those files to determine the strongest root cause. Explain the ordering between pod deletion/recreation and CSI publish/unpublish operations, why same-node pod recreation can preserve the read-only condition, and why repeated remount requests do not solve it. Cite exact evidence lines for the causal chain.

Do not use web search, the upstream GitHub issue, maintainer comments, or the eventual fix while solving the case.
