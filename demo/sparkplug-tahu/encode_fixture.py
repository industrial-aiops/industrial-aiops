"""Run in a separate process with the pinned Tahu python/core on PYTHONPATH."""

import base64
import json
import time

import sparkplug_b as tahu


def pack(payload):
    return base64.b64encode(payload.SerializeToString()).decode()


death = tahu.getNodeDeathPayload()
birth = tahu.getNodeBirthPayload()
timestamp_ms = int(time.time() * 1000)
tahu.addMetric(birth, "Power", 10, tahu.MetricDataType.Double, 42.0, timestamp_ms)
data = tahu.getDdataPayload()
tahu.addMetric(data, None, 10, tahu.MetricDataType.Double, 43.0, timestamp_ms)
tahu.getNodeDeathPayload()
rebirth = tahu.getNodeBirthPayload()
tahu.addMetric(rebirth, "Energy", 10, tahu.MetricDataType.Double, 44.0, timestamp_ms)
print(
    json.dumps(
        {
            "birth": pack(birth),
            "data": pack(data),
            "death": pack(death),
            "rebirth": pack(rebirth),
            "timestamp_ms": timestamp_ms,
        }
    )
)
