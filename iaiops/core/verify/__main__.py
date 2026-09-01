"""``python -m iaiops.core.verify`` — one suite run, digests on stdout.

The subprocess arm of the determinism check (see
:mod:`iaiops.core.verify.determinism`). Deliberately tiny and free of the CLI:
the point of this arm is a *fresh interpreter*, so it must import as little as
possible beyond the code under test.
"""

from __future__ import annotations

import json
import sys

from iaiops.core.verify.determinism import model_modules_loaded, run_suite, suite_digest


def main() -> int:
    checks = run_suite()
    # In a fresh interpreter nothing else ran, so a model library present here
    # was imported to compute the suite — the absolute form of the claim.
    sys.stdout.write(
        json.dumps(
            {
                "checks": checks,
                "suite_digest": suite_digest(checks),
                "model_modules_loaded": model_modules_loaded(),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
