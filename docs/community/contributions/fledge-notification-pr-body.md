# Clarify optional evaluation data in notification delivery reasons

Related to fledge-iot/fledge#1716; this documentation change does not close it.

The delivery-plugin guide currently shows only reason, asset and timestamp.
Document the optional nested data object, an illustrative single-item datapoint
lookup, compatibility when data is absent, and the distinction between evaluation
aggregates and original readings. No API or runtime behavior changes.

Evidence: notification-service develop e0e8437 calls addDataToReason before
queueing delivery. Five local C++ function cases preserve the supplied evaluation
data and original reason fields. This is function-level execution with a no-op
logger, not a full service/plugin test. Deployed service-version differences and
actual delivery-plugin capture remain separate checks.

Validation: patch applies to Fledge develop a20fc6d; the added RST fragment renders
with docutils --halt=warning. Full project Sphinx build was not run.
