# Investigation question

A Kubernetes compatibility-version feature-gate test started failing immediately after the release-1.37 branch cut. The test is running a current 1.38 control plane with emulation set to 1.37, and the validator reports that `DRAFractionalCapacityRange` should be enabled while the live feature metrics report it disabled.

The supplied files are the complete Prow build log and the complete live metrics snapshot from the same failing run. Use only those files to determine whether the strongest explanation is a runtime feature-gate failure or a compatibility-validator/reference-data mismatch. Explain why the live value can legitimately be `0` at emulated version 1.37, what distinction between same-version feature specs the validator must preserve, and why the failure appears at the branch cut. Cite the strongest evidence from both files.

Do not use web search, the upstream GitHub issue, maintainer comments, or the eventual fix while solving the case.
