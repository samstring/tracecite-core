# Investigation question

A Gitea Actions job produced an extremely repetitive workflow log. In the issue reproduction, one million identical lines produce a roughly 41 MB plain-text log in this benchmark; opening the expanded step log in the Gitea UI causes memory use far larger than the stored log size and can OOM the server.

The supplied evidence is the complete one-million-line reproduction log plus the relevant pre-fix Actions view/controller source from the affected revision. Use only those files to identify the strongest root cause of the memory amplification. Explain how an expanded log cursor determines how many rows are read, how those rows are materialized before the HTTP response is sent, and why a highly repetitive/compressible log can still cause very large in-memory and JSON payloads. Cite exact evidence lines from both the log and source.

Do not use web search, the upstream GitHub issue, issue comments, or later fixes while solving the case.
