"""Released governed iaiops MQTT egress → real broker → eKuiper window rule."""

from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
import threading
import time
from datetime import UTC, datetime
from http.client import HTTPConnection
from urllib.parse import urlsplit

import paho.mqtt.client as mqtt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18883)
    parser.add_argument("--rest", default="http://127.0.0.1:9081")
    args = parser.parse_args()
    rest = urlsplit(args.rest)
    if rest.scheme != "http" or rest.hostname != "127.0.0.1" or rest.path not in ("", "/"):
        raise ValueError("The lab REST API must be http://127.0.0.1:<port>.")
    # Isolate the real governance audit and budget from the operator's state.
    with tempfile.TemporaryDirectory(prefix="iaiops-ekuiper-audit-") as state:
        os.environ["IAIOPS_HOME"] = state
        from mcp_server.tools.egress_tools import uns_publish

        def api(method, path, payload=None, missing_ok=False):
            data = None if payload is None else json.dumps(payload).encode()
            connection = HTTPConnection("127.0.0.1", rest.port or 80, timeout=5)
            try:
                connection.request(
                    method, path, body=data, headers={"Content-Type": "application/json"}
                )
                response = connection.getresponse()
                body = response.read().decode()
                if missing_ok and response.status in (400, 404):
                    return ""
                if response.status >= 400:
                    raise RuntimeError(f"eKuiper {method} {path}: {body}")
                return body
            finally:
                connection.close()

        stream, rule = "iaiops_community", "iaiops_community_quality"
        rows = []
        ready = threading.Event()
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

        def on_connect(client, userdata, flags, reason_code, properties):
            client.subscribe("community/result", qos=1)

        def on_subscribe(client, userdata, mid, reason_codes, properties):
            ready.set()

        def on_message(client, userdata, message):
            payload = json.loads(message.payload)
            rows.extend(payload if isinstance(payload, list) else [payload])

        client.on_connect, client.on_subscribe, client.on_message = (
            on_connect,
            on_subscribe,
            on_message,
        )
        client.connect("127.0.0.1", args.port)
        client.loop_start()
        assert ready.wait(3), "result subscription not ready"
        try:
            api("DELETE", f"/rules/{rule}", missing_ok=True)
            api("DELETE", f"/streams/{stream}", missing_ok=True)
            api(
                "POST",
                "/streams",
                {
                    "sql": "CREATE STREAM iaiops_community "
                    "(metric STRING, value FLOAT, timestamp STRING, tags STRUCT(quality STRING)) "
                    'WITH (DATASOURCE="community/iaiops/#", FORMAT="json", TYPE="mqtt")'
                },
            )
            api(
                "POST",
                "/rules",
                {
                    "id": rule,
                    "sql": "SELECT count(*) AS sample_count, avg(value) AS mean_value "
                    "FROM iaiops_community "
                    'WHERE tags->quality = "good" GROUP BY TUMBLINGWINDOW(ss, 2)',
                    "actions": [
                        {
                            "mqtt": {
                                "server": f"tcp://127.0.0.1:{args.port}",
                                "topic": "community/result",
                                "qos": 1,
                                "retained": False,
                                "omitIfEmpty": True,
                            }
                        }
                    ],
                },
            )
            time.sleep(1)  # Allow the source's independent broker subscription to start.
            now = datetime.now(UTC).isoformat()
            points = [
                {"ref": "meter.power", "value": value, "timestamp": now, "quality": quality}
                for value, quality in [
                    (10, "good"),
                    (20, "good"),
                    (30, "good"),
                    (999, "bad"),
                    (None, "missing"),
                ]
            ]
            published = uns_publish(
                points=points,
                topic_prefix="community/iaiops",
                host="127.0.0.1",
                port=args.port,
                qos=1,
            )
            assert published["published"] == 4, published
            assert published["skipped_non_numeric"] == 1, published
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                if sum(row.get("sample_count") or 0 for row in rows) >= 3:
                    break
                time.sleep(0.1)
            count = sum(row.get("sample_count") or 0 for row in rows)
            total = sum(
                (row.get("sample_count") or 0) * (row.get("mean_value") or 0) for row in rows
            )
            assert count == 3 and math.isclose(total, 60), rows
            before = len(rows)
            time.sleep(3.2)
            assert len(rows) == before, "silence unexpectedly produced more numeric observations"
            print(
                json.dumps(
                    {
                        "status": "PASS",
                        "published": published,
                        "windows": rows,
                        "checks": [
                            "governed MQTT egress",
                            "bad quality excluded",
                            "missing numeric value skipped",
                            "window count/sum preserved",
                            "silence is not zero",
                        ],
                    },
                    indent=2,
                )
            )
        finally:
            api("DELETE", f"/rules/{rule}", missing_ok=True)
            api("DELETE", f"/streams/{stream}", missing_ok=True)
            client.disconnect()
            client.loop_stop()


if __name__ == "__main__":
    main()
