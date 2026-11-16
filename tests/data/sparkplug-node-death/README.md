# External Tahu lifecycle fixture

Generated on 2026-11-16 using Eclipse Tahu develop
`c19db8c926dcc8c1f28ad604a13d73d95f281323`. Source licence: EPL-2.0.
No upstream source is vendored here. Three protocol payloads encode synthetic
NBIRTH, device DBIRTH with `Run=1`, and parent NDEATH. `Run` is a fixture name,
not a declared site role. `result.json` preserves the **pre-fix** result and hashes.
`after.json` preserves the fixed replay result. These are offline replay results,
not broker, hardware or Sparkplug certification evidence.

From the repository root, with gh authenticated or public API access:

```bash
mkdir -p /tmp/iaiops-tahu-core
python3 - <<'PYCODE'
import base64, json, subprocess
from pathlib import Path
ref = 'c19db8c926dcc8c1f28ad604a13d73d95f281323'
for name in ['sparkplug_b.py', 'sparkplug_b_pb2.py', 'array_packer.py']:
    data = json.loads(subprocess.check_output([
        'gh', 'api', f'repos/eclipse-tahu/tahu/contents/python/core/{name}?ref={ref}']))
    Path('/tmp/iaiops-tahu-core', name).write_bytes(base64.b64decode(data['content']))
PYCODE
uv sync --extra sparkplug
.venv/bin/python scripts/community/sparkplug_probe.py \
  --upstream-core /tmp/iaiops-tahu-core --out /tmp/iaiops-tahu-result
.venv/bin/pytest -q tests/test_sparkplug_parent_death.py
```

The output directory must not already exist; choose a different name on reruns.
Source hashes are checked before execution. The old upstream generated protobuf
uses the pure-Python compatibility backend in an isolated subprocess; iaiops
uses its normal backend. The default-metric-timestamp observation already has
upstream PRs #398/#472; this fixture is not a new report of that issue.
