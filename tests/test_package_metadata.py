"""PyPI rejects a `summary` (pyproject `description`) over 512 characters.

0.31.0's first publish failed with `400 'summary' field must be 512 characters or
less` after the protocol list grew by one entry — `twine check` does not check the
length, so nothing local caught it and the tag was cut before anyone knew.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PYPI_SUMMARY_LIMIT = 512


def test_the_pypi_summary_fits():
    root = Path(__file__).resolve().parent.parent
    meta = tomllib.loads((root / "pyproject.toml").read_text("utf-8"))["project"]
    summary = meta["description"]
    assert len(summary) <= PYPI_SUMMARY_LIMIT, (
        f"description is {len(summary)} chars; PyPI rejects more than {PYPI_SUMMARY_LIMIT}"
    )
    assert "\n" not in summary
