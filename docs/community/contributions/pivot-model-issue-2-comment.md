I checked `models/pivottm`, `models/pivotts` and `models/pivottc` at `c00cbf776c90a3e0d0ffdeee4e6659508ba1d2cb` while looking for a small Python contribution.

The three files parse as JSON model illustrations with concrete values and namespace-like keys; I did not find top-level JSON Schema declarations in those files. That may explain why treating the files themselves as JSON Schema produces incomplete bindings. This is an observation about these three files, not a claim that no authoritative schema exists elsewhere.

A standard-library round-trip check preserved every field/value in all three examples:

```python
import json
from pathlib import Path

for name in ("pivottm", "pivotts", "pivottc"):
    model = json.loads((Path("models") / name).read_text())
    assert json.loads(json.dumps(model)) == model
```

For typed class generation, could you point to the maintained schema/model definition that establishes cardinality, optional fields, enums and numeric constraints? Inferring those from one concrete example would risk losing valid variants. I would also keep quality flags and time-quality fields intact rather than treating the example values as confirmed operational health.

Would a short lossless Python loading/inspection example be useful first, with typed bindings following once the authoritative definition and expected Python API are agreed? I have a small local inspector covering those three examples; no schema or protocol-conformance claim is intended.
