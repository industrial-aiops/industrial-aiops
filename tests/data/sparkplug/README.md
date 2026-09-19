# Recorded Sparkplug B stream

`frames/` holds 122 payloads exactly as a real broker delivered them to a
subscriber: one NBIRTH, 120 NDATA, and one NDEATH. `manifest.json` records each
frame's topic, QoS, retain flag, size and SHA-256.

| | |
|---|---|
| Broker | mosquitto 2.1.2, `eclipse-mosquitto:2` container, unmodified — on lab host A |
| Node | `capture.py` in this directory — **ours**, written from the Sparkplug B 3.0 spec — on lab host B |
| Recorder | a third machine; all three talk over the lab LAN |
| Not | a vendor device. This is rung 2a for the broker and our own code for the node. |

What the stream contains, and why each part is here:

- **Names only in NBIRTH.** `Running`, `PartCount`, `Temp` are named once with
  aliases 11/12/13; all 360 metric entries in the 120 NDATA frames carry the
  alias and no name. A test that builds payloads itself tends to send names,
  and that is how a real node's behaviour was once missed.
- **A stopped window.** Frames 61–70 have `Running = false` and the counter
  holds at 260.
- **A broker-published death, the slow kind.** The node registers NDEATH as its
  MQTT Last Will and is then *frozen* (`docker pause`), not killed. Its socket
  stays open, so the broker can only declare it dead when keepalive expires: the
  NDEATH arrived **7.5 s** after the last NDATA (keepalive 5 s × 1.5). That is a
  pulled cable rather than a crash, and those seconds with no death signal are
  exactly what `stale_after_s` has to cover. The last frame is the broker's.
- **Node timestamps in epoch milliseconds**, which must survive to the reading
  rather than being replaced by arrival time.

Not in it: DBIRTH/DDATA (devices under the node), a re-BIRTH, a `STATE`
message, or retained messages.

Re-record (overwrites `frames/` and `manifest.json`; the tests pin the stream's
shape, not the timestamps). Single machine, node killed:

    docker run -d --rm --name iaiops-mosq -p 127.0.0.1:21883:1883 \
        eclipse-mosquitto:2 mosquitto -c /mosquitto-no-auth.conf
    .venv/bin/python tests/data/sparkplug/capture.py --port 21883

Three hosts, node frozen (how the committed corpus was made): run the broker on
host A as above but published on the LAN, then

    .venv/bin/python tests/data/sparkplug/capture.py --host <A> --port 21883 \
        --node-cmd "ssh <B> docker run --rm --name iaiops-node -v ~/capture.py:/cap/capture.py \
            --entrypoint python ghcr.io/industrial-aiops/iaiops:0.22.0-factory -u /cap/capture.py \
            --role node --host <A> --port 21883" \
        --death-cmd "ssh <B> docker pause iaiops-node" --death "frozen …"

Any image with `paho-mqtt` and `iaiops[sparkplug]` works for the node.
