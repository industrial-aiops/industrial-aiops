"""Reproduce both cases through the governed CLI and verify all exported hashes."""

import argparse
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--out-dir", type=Path, required=True)
args = parser.parse_args()
args.out_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
for case, expected_code in (("sufficient", 0), ("insufficient", 2)):
    target = args.out_dir / f"{case}.zip"
    command = [
        sys.executable,
        "-c",
        "from iaiops.cli import app; app()",
        "diagnostic-card",
        "--input",
        str(Path(__file__).parent / f"{case}.json"),
        "--out",
        str(target),
        "--replay",
    ]
    completed = subprocess.run(command, check=False)
    if completed.returncode != expected_code:
        raise SystemExit(f"{case}: expected exit {expected_code}, got {completed.returncode}")
    with zipfile.ZipFile(target) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        for name, entry in manifest["files"].items():
            if hashlib.sha256(archive.read(name)).hexdigest() != entry["sha256"]:
                raise SystemExit(f"Hash mismatch: {name}")
        report = json.loads(archive.read("assessment.json"))
        assert not report["live_readiness"]
        if case == "sufficient":
            measured = report["diagnostic"]["measurement"]
            assert measured["stops"] == 1 and measured["stopped_s"] == 6
            assert report["diagnostic"]["root_cause"] is None
        else:
            assert report["status"] == "insufficient_evidence" and report["diagnostic"] is None
        (args.out_dir / f"{case}.html").write_bytes(archive.read("card.html"))
print("Both outcomes and every inventory hash verified; replay only, no live OT claim.")
