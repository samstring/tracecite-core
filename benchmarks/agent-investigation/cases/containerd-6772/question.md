# Investigation question

A Kubernetes node running containerd 1.6.2 becomes unhealthy under heavy pod churn: pod creation and termination stop making progress, many `runc init` processes accumulate, and restarting containerd can temporarily recover the node. A complete containerd goroutine dump was captured while the incident was active.

Use the supplied **complete goroutine dump only** to identify the most likely synchronization failure and the subsystem involved. Reconstruct the competing call paths that can block one another, explain how that can prevent task startup and leave `runc init` processes waiting, and cite the strongest stack evidence for your conclusion.

Do not use web search, the upstream GitHub issue, maintainer comments, or the eventual fix while solving the case.
