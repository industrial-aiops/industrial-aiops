# Sparkplug decoder interoperability with Eclipse Tahu

Pinned third-party input: Eclipse Tahu `5736e404889d4b95910613040a99ba79589ffb13`.
The fixture encoder imports Tahu's own Python API and protobuf in a separate
process; the consumer uses iaiops' own decoder through a real MQTT subscription.
No Tahu source is vendored or modified. Use the upstream EPL-2.0 source as provided.

This checks independent encoding/decoding, alias resolution, source timestamps,
death, rebirth and staleness. It is **not** a complete independent EoN implementation,
Sparkplug TCK run, commercial device test or Sparkplug Compatible certification.

Run an isolated anonymous broker on loopback port 18883 (test data only), install
`iaiops[sparkplug]==0.34.0`, and extract the pinned Tahu source. Then:

```sh
python verify_live.py --tahu-core /path/to/tahu/python/core --port 18883
```

The encoder uses `PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python` because the pinned
Tahu Python source contains older generated protobuf descriptors. This setting
is confined to the encoder subprocess; the installed iaiops decoder is unchanged.
The script publishes only test NBIRTH/NDATA/NDEATH payloads and never sends NCMD/DCMD.

The pinned broker command/configuration is also provided in
[`../ekuiper/README.md`](../ekuiper/README.md). This decoder test does not depend on
the eKuiper process.
