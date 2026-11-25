"""Inspect PIVOT model examples without inventing a schema or confirming semantics."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

FIELDS = {"Validity", "oldData", "clockFailure", "clockNotSynchronized", "TmValidity"}


def indicators(value, path=""):
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}/{key}"
            if key in FIELDS:
                found.append({"path": child, "raw_value": item})
            found.extend(indicators(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(indicators(item, f"{path}/{index}"))
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Output must not already exist")
    reports = []
    for name in ["pivottm", "pivotts", "pivottc"]:
        data = (args.models / name).read_bytes()
        obj = json.loads(data)
        roundtrip = json.loads(json.dumps(obj))
        if roundtrip != obj:
            raise RuntimeError(f"Roundtrip differs: {name}")
        reports.append(
            {
                "model": name,
                "sha256": hashlib.sha256(data).hexdigest(),
                "roundtrip_equal": True,
                "top_level_keys": list(obj),
                "schema_keywords_present": sorted(
                    set(obj) & {"$schema", "properties", "$defs", "required"}
                ),
                "raw_indicators": indicators(obj),
            }
        )
    result = {
        "scope": "JSON example inspection, not schema/protocol validation",
        "site_semantics": "unconfirmed",
        "examples": reports,
    }
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {"examples_read": len(reports), "roundtrips_equal": True, "semantics_confirmed": False}
        )
    )


if __name__ == "__main__":
    main()
