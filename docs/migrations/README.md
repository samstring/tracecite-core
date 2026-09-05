# Schema and API migration notes

These notes describe versioned public-schema and API migrations:

- [Extension Protocol v1 -> v2 (English)](extension-protocol-v2.md)
- [Extension Protocol v1 -> v2（简体中文）](extension-protocol-v2.zh-CN.md)
- [Filter provenance (English)](filter-provenance.md)
- [Filter provenance（简体中文）](filter-provenance.zh-CN.md)
- [Regex resource gate (English)](regex-resource-gate.md)
- [正则资源门禁（简体中文）](regex-resource-gate.zh-CN.md)
- [Persisted-schema compatibility governance (English)](schema-compatibility.md)
- [持久化 schema 兼容性治理（简体中文）](schema-compatibility.zh-CN.md)
- [Bounded derived-value descriptors (English)](0003-derived-value-descriptors.md)
- [有界 Derived-Value Descriptor（简体中文）](0003-derived-value-descriptors.zh-CN.md)

Extension Protocol versioning is independent from persisted Investigation, Knowledge, Scenario, and Manifest schema versions. A domain-extension API migration therefore does not imply a persisted-data schema migration unless explicitly documented.
