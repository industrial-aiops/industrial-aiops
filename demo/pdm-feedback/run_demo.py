"""Offline synthetic reviewer fixture using the real governed confirmation CLI.

This simulates a predeclared human answer; it is not a real plant/operator test.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--out-dir", required=True, type=Path)
args = parser.parse_args()
# Never write to the operator's real knowledge/audit stores.
if args.out_dir.exists():
    raise SystemExit("Choose a NEW output directory")
args.out_dir.mkdir(parents=True, mode=0o700)
state = args.out_dir.resolve() / "isolated-home"
env = {**os.environ, "HOME": str(state), "IAIOPS_HOME": str(state)}
env.pop("IAIOPS_CONFIG", None)
env.pop("OT_AIOPS_HOME", None)


def call(arguments, expected=0):
    p = subprocess.run(
        [sys.executable, "-c", "from iaiops.cli import app; app()", *arguments],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if p.returncode != expected:
        raise SystemExit(p.stdout + p.stderr)
    return p.stdout


def write(name, value):
    p = args.out_dir / name
    p.write_text(json.dumps(value, indent=2) + "\n")
    return str(p)


evaluation = str(args.out_dir / "evaluation.zip")
call(
    [
        "pdm-evaluation",
        "run",
        "--input",
        str(Path(__file__).parent / "dataset.json"),
        "--out",
        evaluation,
    ]
)
opened = json.loads(
    call(
        [
            "pdm-evaluation",
            "open-case",
            "--evaluation",
            evaluation,
            "--window",
            "detected",
            "--site",
            "synthetic-demo",
        ]
    )
)
request = {
    "schema": "iaiops.pdm-feedback-request/v1",
    "outcome": "pending",
    "by": "synthetic reviewer fixture",
}
base = [
    "pdm-evaluation",
    "feedback",
    "--evaluation",
    evaluation,
    "--window",
    "detected",
    "--site",
    "synthetic-demo",
]
call([*base, "--input", write("pending.json", request), "--out", str(args.out_dir / "pending.zip")])
request["outcome"] = "confirmed"
call(
    [
        *base,
        "--input",
        write("premature.json", request),
        "--out",
        str(args.out_dir / "must-not-exist.zip"),
    ],
    expected=1,
)
assert not (args.out_dir / "must-not-exist.zip").exists()
# An EXPLICIT simulated answer, never derived from a forecast or audit action.
call(
    [
        "case",
        "confirm",
        opened["case_id"],
        "--cause",
        "mechanical_fault",
        "--by",
        request["by"],
        "--site",
        "synthetic-demo",
        "--json",
    ]
)
request["maintenance"] = {
    "work_order_id": "synthetic-maintenance-001",
    "device_id": "synthetic-motor-detected",
    "case_id": opened["case_id"],
    "diagnosis_id": opened["diagnosis_id"],
    "cause": "mechanical_fault",
    "completed_at": "2026-11-20T02:00:00Z",
    "actions": ["synthetic inspection/replacement record"],
}
call(
    [
        *base,
        "--input",
        write("confirmed.json", request),
        "--out",
        str(args.out_dir / "confirmed.zip"),
    ]
)
with zipfile.ZipFile(args.out_dir / "confirmed.zip") as z:
    result = json.loads(z.read("feedback.json"))
    confirmation = json.loads(z.read("case-confirmation-reference.json"))
    assert confirmation["status"] == "matching_records"
    assert z.read("evaluation-audit-reference.json")
    assert result["maintenance_bridge"]["n_mapped"] == 1 and result["updates_applied"] == []
with zipfile.ZipFile(evaluation) as z:
    report = json.loads(z.read("evaluation.json"))
    assert report["metrics"]["event_recall"] == 1 / 3
print(
    json.dumps(
        {
            "scenario": "synthetic, scripted reviewer, no real human/plant claim",
            "case_id": opened["case_id"],
            "pending_then_confirmed": True,
            "premature_confirmation_refused": True,
            "metrics": report["metrics"],
            "updates_applied": result["updates_applied"],
        },
        indent=2,
    )
)
