# TraceCite Core

TraceCite Core converts raw text into structured, line-addressable evidence for agents.
It contains the reusable text layer only: records, segmenters, sources, preprocessing,
matching, filtering, events, run manifests, and the public plugin SDK.

The package is deliberately stdlib-only and has no device, product, network-service,
or application dependency.

```bash
python -m pip install -e .
python -m pytest
tracecite-core --help
```

```python
from tracecite_core import RawTextSegmenter, filter_text

result = filter_text("example.log", r"timeout|error", segmenter=RawTextSegmenter())
print(result.output_path, result.match_records)
```

Compatibility policy: schemas and run semantics inherited from the original v2/v3
implementation remain stable. The new distribution starts at `0.1.0`.

The standalone `tracecite-core` CLI exposes pure-text `filter`, `segment`, `source`,
manifest `verify`, and `plugin` diagnostics. It never imports a device layer.
