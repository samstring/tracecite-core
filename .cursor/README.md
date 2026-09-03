# Cursor integration note

TraceCite intentionally does **not** ship a repository-local `.cursor/rules/*.mdc` investigation rule.

General Cursor setup is user-global:

- install `tracecite-investigate` at `~/.agents/skills/tracecite-investigate/`;
- add the conditional TraceCite investigation rule as a Cursor User Rule in **Customize -> Rules**;
- invoke `/tracecite-investigate` only when the current task actually uses TraceCite.

Do not reintroduce a relevance-triggered project rule for generic debugging/log investigation. Merely working on an incident or log task must not activate TraceCite policy.

See `docs/agent-global-setup.md` and `docs/agent-integration.md`.
