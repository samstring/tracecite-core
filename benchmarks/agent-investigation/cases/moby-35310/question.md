# Investigation question

A Docker Swarm service update is repeatedly rejecting tasks with `Unable to complete atomic operation, key modified`. The supplied evidence contains the relevant network teardown/debug sequence and the pre-fix `endpoint_count` storage path.

Use only the supplied files to determine whether the strongest explanation is ordinary transient concurrent store contention or a network/endpoint lifecycle inconsistency that leaves per-network endpoint-count state in the wrong lifecycle. Explain the causal sequence from network teardown, through endpoint cleanup, to the later task rejection. Explain why the `ErrKeyModified` retry path does not by itself make this safe when teardown and endpoint updates are out of order. Cite exact evidence lines for the material claims.

Do not use web search, the upstream issue discussion, maintainer comments, or the eventual fix while solving the case.
