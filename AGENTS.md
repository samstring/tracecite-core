# TraceCite Core boundaries

- Keep this project Python-standard-library-only at runtime.
- Do not add mobile-device, product, company, or application imports or defaults.
- Public imports use `tracecite_core`.
- Mobile and company projects may depend on Core; Core must never depend on them.
- Preserve evidence and run schema semantics unless a migration is documented and tested.

