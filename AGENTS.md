# TraceCite main project boundaries

- This repository publishes the main `tracecite` distribution.
- `tracecite_core` is the stable, Python-standard-library-only evidence layer.
- `tracecite.runtime` may depend on `tracecite_core`; Core must never import Runtime.
- `tracecite.extension` exposes public registration contracts and may depend on Core and Runtime.
- `tracecite.integrations` adapts Runtime to CLI and future Agent hosts.
- Keep device, product, company, application, and domain knowledge out of this repository.
- Mobile, CI, and third-party projects are extensions that depend only on public TraceCite APIs.
- Preserve evidence and run schema semantics unless a migration is documented and tested.
- Keep the public `tracecite_core` import stable until a documented schema migration replaces it.
