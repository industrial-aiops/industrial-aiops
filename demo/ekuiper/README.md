# iaiops → MQTT → LF Edge eKuiper

This integration uses the released iaiops 0.34.0 governed `uns_publish` tool and
eKuiper 2.4.2. It publishes already-read, **simulated** meter points to a local
broker, selects operator-declared good-quality points, and computes two-second
processing-time windows. No OT device or control channel is involved.

Payload contract is the existing iaiops MQTT egress shape:
`{metric, value, timestamp, tags}`. The tool accepts top-level `quality` on input
and its normalizer carries that field into `tags.quality` on the wire. An arbitrary
input `tags` dictionary is not copied. Human point semantics remain operator declarations.

## Run

1. Install `iaiops[mqtt]==0.34.0` in a dedicated Python environment.
2. Run a local test broker on loopback port 18883 with anonymous access confined
   to this isolated lab. Run the checksum-verified official eKuiper 2.4.2 release
   with `MQTT_SOURCE__DEFAULT__SERVER=tcp://127.0.0.1:18883` and its REST API on
   loopback port 9081. Configure the API listener explicitly; never expose it
   unauthenticated on a shared interface.
3. Run `python verify_live.py --port 18883 --rest http://127.0.0.1:9081`.

Broker command, from this directory:

```sh
docker run --rm --name iaiops-community-mqtt -p 127.0.0.1:18883:1883 \
  -v "$PWD/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro" \
  public.ecr.aws/docker/library/eclipse-mosquitto@sha256:75d6662dee52c947dc9dd9c29f1d8d7ffef78ddaf38001caa09755681e8bbc98
```

In the extracted eKuiper release directory, set these keys in its existing
configuration files (retain other defaults), then launch `./bin/kuiperd` there:

```yaml
# etc/kuiper.yaml
basic:
  ip: 127.0.0.1
  restIp: 127.0.0.1
  restPort: 9081
```

```yaml
# etc/mqtt_source.yaml
default:
  qos: 1
  server: tcp://127.0.0.1:18883
  protocolVersion: '3.1.1'
```

The script creates and deletes only stream `iaiops_community` and rule
`iaiops_community_quality`. Use a dedicated eKuiper instance: those names are
reserved for the demo. The real tool governance runs with temporary audit state.

## Acceptance and remaining work

- Good numeric samples 10, 20 and 30 contribute a total count of three and sum 60.
- Bad-quality 999 is filtered; missing numeric values are skipped by iaiops.
- A silent publisher produces no zero-valued observations.
- `omitIfEmpty: true` suppresses empty window results at the MQTT sink.
- Windows use **processing time**, not the source ISO timestamp. Late/out-of-order
  event-time handling, reconnect behavior, TLS and real meters require separate
  validation before the upstream integration proposal is called complete.

Official upstream API/source references:
https://github.com/lf-edge/ekuiper/tree/v2.4.2/docs/en_US
