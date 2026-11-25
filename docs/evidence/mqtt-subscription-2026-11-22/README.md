# MQTT subscription startup race — 2026-11-22

Baseline main: de9ae0a; package 0.34.1, fix unreleased. First CI attempt
[44974096242](https://github.com/industrial-aiops/industrial-aiops/actions/runs/44974096242/attempts/1)
failed in `test_a_published_value_is_readable_through_the_held_session` on Python
3.11: no sample within five seconds. The unchanged job passed on retry.

The source confirms a startup contract bug: `connect()` / `loop_start()` and
`subscribe()` enqueue asynchronous work, but `mqtt_tap_session` yielded without
waiting for CONNACK/SUBACK or checking the subscription result. A non-retained,
one-shot publication before subscription establishment can be lost; polling the
cache afterwards cannot recover it. Six deterministic tests fail on the old
implementation (`red.log`), including a delayed acceptance that demonstrates the
session returns while the subscriber is not ready. The historical CI log has no
packet trace, so the exact ordering in that specific runner is **not proven**.
This fixes the demonstrated race consistent with that failure, not a claimed
forensic reconstruction of the lost message.

The tap now waits for connection readiness and the matching successful SUBACK
within one shared `target.timeout_s` deadline, with callback registration before
sending and an acknowledgement map protecting the callback-before-return race.
Immediate subscribe errors, denied/empty SUBACK, missing/wrong-mid ACK and
CONNACK timeout fail rather than advertising readiness. Existing session cleanup
handles preparation failures. No protocol data, stale timer or historical-value
policy changed. Automatic reconnection/resubscription is outside this change.

The real-broker publisher now waits for QoS-1 PUBACK and disconnects in `finally`
instead of assuming 0.3 seconds is enough. The polling helper does **not** republish;
its misleading old docstring was corrected. Stale reads remain failures, never
refreshed to make the test pass.

Final focused regression (subscription, cache/history, session factory, session
reads and collection/session reuse): **116 passed** (`green.log`). Eight new
startup tests cover delayed/denied/empty/missing/wrong-mid ACK, immediate error,
CONNACK timeout and synchronous ACK. Repository Ruff check/format passed (698
files); Bandit Medium+ scan exit 0 (`bandit.log`). Real Mosquitto 2 on a disposable loopback-published Docker broker: the complete
`tests/test_uns_tap_live.py` passed five consecutive runs (**20 passed**, `live.log`),
including one-shot reads, expiry and collection gaps. The temporary broker was
removed. Remote CI is checked after integration; its run URL is reported in the
delivery message. No physical
Sparkplug gateway, production broker, TLS/ACL broker policy or PLC was tested.
