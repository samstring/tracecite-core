# Investigation question

A VS Code renderer/window on Windows freezes after the system clock is moved backwards, especially when the affected window is then closed. The main process can remain responsive. The supplied files contain the reproducible behavior, the relevant pre-fix asynchronous logging worker code, and an isolated timing observation from the same investigation.

Use only those files to determine whether the strongest explanation is dialog/update handling or the logging worker's shutdown/wait behavior. Explain the mechanism connecting the backwards clock adjustment to the renderer freeze, including what happens when the async logger is being destroyed and why the main process can still be responsive. Cite exact evidence lines for the material claims.

Do not use web search, upstream issue comments outside the supplied evidence, the eventual spdlog fix, or external implementation knowledge while solving the case.
