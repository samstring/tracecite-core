# Investigation question

A Harvester 1.2.1 cluster cannot start an upgrade to 1.2.2 because the admission webhook rejects the request with `machine fleet-local/custom-318894c86e3c is not running`.

The supplied files are complete original files extracted from the issue's support bundle: one kube-apiserver log, one Rancher log, and the complete `Machine` resource dump for `fleet-local`. Use only those files to determine the strongest root cause of the upgrade blocker. Explain why the named machine is still participating in reconciliation even though it is not a current healthy node, what state shows it is stale/incomplete, and how that stale state leads to the webhook rejection. Cite exact evidence lines from the logs and machine dump.

Do not use web search, the upstream GitHub issue, issue comments, or the eventual workaround while solving the case.
