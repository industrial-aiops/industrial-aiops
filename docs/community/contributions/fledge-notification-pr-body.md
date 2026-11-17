The notification delivery guide currently illustrates only reason, asset and timestamp. Add an optional nested `data` example, explain how to access the evaluated datapoint, and retain compatibility with reasons that do not carry evaluation data. Clarify that window evaluation data may be aggregate data rather than a single original sample.

Related to #1716; this documentation change does not close that feature request and does not alter the plugin API or runtime.

Evidence: notification-service develop at `e0e84373c5bbd2fab26c9a033c84c45812c1d260` calls `addDataToReason(reason, data)` before queueing delivery. A focused local C++ execution of the unmodified enrichment function, with only a no-op logging sink, preserved supplied evaluation data and original reason fields in five cases. This was not a full service or delivery-plugin test. The new example is illustrative, not represented as a captured production notification.

Validation: applied against Fledge develop `cf091f09fd456a767c155fc7474944dd9057c4c1`; added RST fragment rendered using docutils with `--halt=warning` and Pygments. Full project Sphinx build was not run.
