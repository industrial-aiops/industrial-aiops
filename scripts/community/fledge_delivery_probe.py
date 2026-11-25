"""Execute pinned upstream enrichment and delivery-wrapper functions with a capture callback."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

from fledge_reason_probe import PIN


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--compiler", default="clang++")
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Output must not already exist")
    subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("fledge_reason_probe.py")),
            "--source",
            str(args.source),
            "--out",
            str(args.out),
            "--compiler",
            args.compiler,
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=90,
    )
    relative = "C/services/notification/delivery_plugin.cpp"
    original = subprocess.check_output(["git", "-C", str(args.source), "show", f"{PIN}:{relative}"])
    if (args.source / relative).read_bytes() != original:
        parser.error("Delivery source has local edits")
    match = re.search(r"bool DeliveryPlugin::deliver\(.*?\n\{.*?\n\}", original.decode(), re.S)
    if match is None:
        parser.error("Pinned delivery function not found")
    function = match.group()
    wrapper = (args.out / "probe.cpp").read_text().split("int main() {", 1)[0]
    wrapper = "#include <ctime>\n" + wrapper
    wrapper = wrapper.replace(
        "template<class... Args> void debug",
        "template<class... Args> void warn(const char*, Args...) {}\n"
        "    template<class... Args> void debug",
        1,
    )
    wrapper += r"""
class DeliveryPlugin {
public:
    using Callback = bool (*)(void*, const string&, const string&, const string&, const string&);
    Callback pluginDeliverPtr = nullptr;
    void* m_instance = nullptr;
    string expandMacros(const string& text, const string&) { return text; }
    bool deliver(const string&, const string&, const string&, const string&);
};
"""
    wrapper += function
    wrapper += r"""
static string captured;
static bool callbackResult = true;
static int calls = 0;
static bool capture(void*, const string&, const string&, const string& reason, const string&) {
    captured = reason;
    ++calls;
    return callbackResult;
}
int main() {
    DeliveryPlugin delivery;
    delivery.pluginDeliverPtr = capture;
    string reason, data;
    while (getline(cin, reason) && getline(cin, data)) {
        addDataToReason(reason, data);
        if (!delivery.deliver("capture", "fixture", reason, "literal message")) return 2;
        if (captured != reason) return 3;
        cout << captured << endl;
    }
    callbackResult = false;
    if (delivery.deliver("capture", "fixture", "{}", "literal message")) return 4;
    int before = calls;
    delivery.pluginDeliverPtr = nullptr;
    if (delivery.deliver("capture", "fixture", "{}", "literal message")) return 5;
    if (calls != before) return 6;
    cout << "{\"callback_failure_propagated\":true,\"missing_callback_refused\":true}" << endl;
}
"""
    cpp, binary = args.out / "delivery.cpp", args.out / "delivery"
    cpp.write_text(wrapper)
    subprocess.run(
        [args.compiler, "-std=c++11", str(cpp), "-o", str(binary)],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    base = json.loads((args.out / "result.json").read_text())
    cases = base["results"]
    inputs = "".join(
        json.dumps(c["input_reason"]) + "\n" + json.dumps(c["evaluation_data"]) + "\n"
        for c in cases
    )
    result = subprocess.run(
        [str(binary)], input=inputs, text=True, capture_output=True, check=True, timeout=10
    )
    outputs = [json.loads(line) for line in result.stdout.splitlines()]
    if len(outputs) != len(cases) + 1:
        raise RuntimeError("Unexpected callback output count")
    for case, output in zip(cases, outputs[:-1], strict=True):
        if output != case["output_reason"]:
            raise RuntimeError(f"Callback payload differs: {case['case']}")
    report = {
        "source_commit": PIN,
        "enrichment_file_sha256": base["source_sha256"],
        "enrichment_function_sha256": base["function_sha256"],
        "compiler": base["compiler"],
        "delivery_file_sha256": hashlib.sha256(original).hexdigest(),
        "delivery_function_sha256": hashlib.sha256(function.encode()).hexdigest(),
        "captured_cases": len(cases),
        "checks": outputs[-1],
        "scope": "Native functions; logger/class/macro/callback scaffolding; no service/plugin",
        "captured_reasons": outputs[:-1],
    }
    (args.out / "delivery-result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"captured_cases": len(cases), **outputs[-1]}))


if __name__ == "__main__":
    main()
