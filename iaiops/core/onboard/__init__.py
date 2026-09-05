"""``iaiops onboard`` — the one path from "what is on this network" to an answer.

Every piece of this path already existed and nothing joined them: a site could
scan 40 devices and then retype all 40 by hand, and nothing anywhere said which
of the seven commands to run next. Both are addressed here, and neither is a
wizard — :mod:`.path` reports where a site actually stands, and :mod:`.draft`
carries the scan's findings forward as a draft a person merges.

Contacts nothing; writes nothing.
"""

from iaiops.core.onboard.draft import draft_from_scan
from iaiops.core.onboard.model import (
    STATE_DONE,
    STATE_NEXT,
    STATE_WAITING,
    Draft,
    DraftEndpoint,
    DraftField,
    OnboardPath,
    SkippedHost,
    Step,
)
from iaiops.core.onboard.path import assess_path
from iaiops.core.onboard.render import render_yaml

__all__ = [
    "STATE_DONE",
    "STATE_NEXT",
    "STATE_WAITING",
    "Draft",
    "DraftEndpoint",
    "DraftField",
    "OnboardPath",
    "SkippedHost",
    "Step",
    "assess_path",
    "draft_from_scan",
    "render_yaml",
]
