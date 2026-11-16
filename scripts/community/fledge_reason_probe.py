"""Execute one pinned upstream C++ reason-enrichment function, not a Fledge service."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

PIN = "e0e84373c5bbd2fab26c9a033c84c45812c1d260"
RELATIVE = "C/services/notification/notification_queue.cpp"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--compiler", default="clang++")
    args = parser.parse_args()
    revision = subprocess.check_output(
        ["git", "-C", str(args.source), "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != PIN:
        parser.error(f"Expected source commit {PIN}")
    if args.out.exists():
        parser.error("Output must not already exist")
    path = args.source / RELATIVE
    # Reject local edits as well as a different checkout revision.
    original = subprocess.check_output(["git", "-C", str(args.source), "show", f"HEAD:{RELATIVE}"])
    if path.read_bytes() != original:
        parser.error("Upstream source has local edits")
    source = original.decode()
    match = re.search(
        r"static void addDataToReason\(string& reason, const string& data\)\n"
        r"\{.*?\n\}",
        source,
        re.S,
    )
    if match is None:
        parser.error("Pinned function not found")
    function = match.group()
    # Only replace the logging sink. The upstream function body remains byte-for-byte.
    wrapper = r"""
#include <iostream>
#include <string>
using namespace std;
struct Logger {
    static Logger* getLogger() { static Logger instance; return &instance; }
    template<class... Args> void debug(const char*, Args...) {}
};
"""
    wrapper += function
    wrapper += r"""
int main() {
    string reason, data;
    while (getline(cin, reason) && getline(cin, data)) {
        addDataToReason(reason, data);
        cout << reason << endl;
    }
}
"""
    args.out.mkdir(parents=True)
    cpp, binary = args.out / "probe.cpp", args.out / "probe"
    cpp.write_text(wrapper)
    subprocess.run(
        [args.compiler, "-std=c++11", str(cpp), "-o", str(binary)],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    reason = {"reason": "triggered", "asset": ["sinusoid"], "timestamp": "2026-11-17T00:00:00Z"}
    cases = [
        (
            "single-item",
            reason,
            {"sinusoid": {"sinusoid": 87.3}, "timestamp_sinusoid": 1794873600.0},
        ),
        ("second-value", reason, {"sinusoid": {"sinusoid": 91.7}}),
        ("cleared", {**reason, "reason": "cleared"}, {"sinusoid": {"sinusoid": 50.0}}),
        ("empty-data", reason, {}),
        ("escaped-text", reason, {"label": 'quote " and slash \\'}),
    ]
    inputs = "".join(json.dumps(r) + "\n" + json.dumps(d) + "\n" for _, r, d in cases)
    run = subprocess.run(
        [str(binary)], input=inputs, text=True, capture_output=True, check=True, timeout=10
    )
    lines = run.stdout.splitlines()
    if len(lines) != len(cases):
        raise RuntimeError("Unexpected output count")
    results = []
    for (name, before, data), line in zip(cases, lines, strict=True):
        after = json.loads(line)
        if after.get("data") != data or any(after.get(k) != v for k, v in before.items()):
            raise RuntimeError(f"Data preservation failed: {name}")
        results.append(
            {"case": name, "input_reason": before, "evaluation_data": data, "output_reason": after}
        )
    report = {
        "source_commit": revision,
        "source_path": RELATIVE,
        "source_sha256": hashlib.sha256(original).hexdigest(),
        "function_sha256": hashlib.sha256(function.encode()).hexdigest(),
        "compiler": subprocess.check_output([args.compiler, "--version"], text=True).splitlines()[
            0
        ],
        "scope": "upstream C++ function; logger stub; no service/plugin/broker",
        "cases_passed": len(results),
        "results": results,
    }
    (args.out / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "cases_passed": len(results),
                "source_commit": revision,
                "result": str(args.out / "result.json"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
