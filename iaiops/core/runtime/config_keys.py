"""Which keys each ``config.yaml`` block accepts — and the refusal for the rest.

Every parser in :mod:`iaiops.core.runtime.config` reads its fields with
``d.get(...)``, so a key nobody reads simply **was not there**. A site that
wrote ``rolle: good_count`` had declared a production counter as far as it was
concerned; ``readiness`` then reported the OEE mapping as unmet, naming a gap
the operator had already filled, and pointing nowhere near the typo. Nothing
logged, nothing failed — the config file and the tool's idea of it had quietly
stopped being the same document.

That is the failure this module closes, and it closes it the way the rest of
this package does: by **refusing** rather than warning. An unsupported protocol
raises, an unknown tag role raises, a tag with no address raises. A warning here
would be one stderr line inside a long ``readiness`` run, and the thing it
guards is a wrong answer wearing the right shape.

The accepted sets are duplicated from the parsers on purpose — a parser must be
free to read a key without a table saying it may. ``tests/test_config_keys.py``
reads the parsers' own source and fails when the two drift apart, so the
duplication cannot rot into a false refusal.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from difflib import get_close_matches
from typing import Any

#: Below this ratio a "did you mean" is noise rather than help.
_SUGGEST_CUTOFF = 0.6


@dataclass(frozen=True)
class BlockKeys:
    """The accepted vocabulary of one config block, and how to teach it.

    ``primary`` is what the error prints — the keys someone should be writing.
    ``aliases`` are also accepted but stay out of the headline list so the
    message reads as a vocabulary rather than a changelog.
    """

    #: How the error names this block, e.g. "Tag #2 on endpoint 'line1'".
    what: str
    primary: tuple[str, ...]
    #: alias → the primary key it stands for.
    aliases: Mapping[str, str] = field(default_factory=dict)
    #: A wrong key → a complete sentence, for mistakes that are a rename or a
    #: misplacement rather than a misspelling, which ``difflib`` cannot see.
    hints: Mapping[str, str] = field(default_factory=dict)
    #: What went wrong when this block silently dropped the key instead.
    consequence: str = ""

    @property
    def accepted(self) -> frozenset[str]:
        return frozenset(self.primary) | frozenset(self.aliases)


TAG_KEYS = BlockKeys(
    what="Tag",
    primary=(
        "ref",
        "label",
        "warn_high",
        "alarm_high",
        "warn_low",
        "alarm_low",
        "role",
        "running_when",
    ),
    aliases={"node_id": "ref", "address": "ref"},
    hints={"name": "Did you mean 'label'? A tag's human name is 'label'."},
    consequence=(
        "An unrecognised key here used to vanish without a word, so a tag that "
        "declared a role never had one: 'iaiops readiness' then reported the "
        "OEE mapping as unmet, and nothing pointed back at this line."
    ),
)

ENDPOINT_KEYS = BlockKeys(
    what="Endpoint",
    primary=(
        "name",
        "protocol",
        "endpoint_url",
        "host",
        "port",
        "unit_id",
        "transport",
        "serial_port",
        "baudrate",
        "parity",
        "stopbits",
        "bytesize",
        "security_mode",
        "security_policy",
        "username",
        "rack",
        "slot",
        "plctype",
        "agent_url",
        "device",
        "flavor",
        "topic",
        "use_tls",
        "ca_cert",
        "client_cert",
        "client_key",
        "server_cert",
        "long_address",
        "nic",
        "expected_slaves",
        "timeout_s",
        "tags",
        "ideal_cycle_time_s",
    ),
    aliases={
        "broker": "host",
        "com_port": "serial_port",
        "ca_certs": "ca_cert",
        "certfile": "client_cert",
        "keyfile": "client_key",
        "interface": "nic",
        "timeout": "timeout_s",
    },
    hints={
        "ip": "Did you mean 'host'?",
        "label": "Did you mean 'name'? An endpoint's name is 'name'.",
        "password": (
            "Passwords are never written in config.yaml. Put it in the "
            "encrypted store with 'iaiops secret set <endpoint>'."
        ),
        "role": "'role' belongs on a tag inside this endpoint's 'tags:' list, not here.",
        "running_when": (
            "'running_when' belongs on the tag that declares role 'run_state', "
            "inside this endpoint's 'tags:' list, not here."
        ),
    },
    consequence=(
        "An unrecognised key here used to vanish without a word, so the setting "
        "was never applied and the endpoint ran on its defaults instead."
    ),
)

HISTORIAN_KEYS = BlockKeys(
    what="The 'historian:' block",
    primary=("reader", "host", "port", "user", "database", "db_path", "transport"),
    hints={
        "password": (
            "The historian password is never written in config.yaml. Put it in "
            "the encrypted store with 'iaiops secret set historian'."
        ),
        "type": "Did you mean 'reader'?",
    },
    consequence=(
        "An unrecognised key here used to vanish without a word, so the reader "
        "connected with its own defaults — or failed, naming something else."
    ),
)

RETENTION_KEYS = BlockKeys(
    what="The 'retention:' block",
    primary=("raw_days",),
    hints={"days": "Did you mean 'raw_days'?"},
    consequence=(
        "An unrecognised key here used to vanish without a word, so the "
        "retention decision was never made and raw samples kept accumulating."
    ),
)


def _suggestion(key: str, spec: BlockKeys) -> str:
    """The most useful thing to say about one wrong key, or "" for nothing."""
    hint = spec.hints.get(key)
    if hint:
        return hint
    close = get_close_matches(key, sorted(spec.accepted), n=1, cutoff=_SUGGEST_CUTOFF)
    if not close:
        return ""
    match = close[0]
    stands_for = spec.aliases.get(match)
    if stands_for:
        return f"Did you mean {match!r} (an accepted alias for {stands_for!r})?"
    return f"Did you mean {match!r}?"


def reject_unknown_keys(spec: BlockKeys, block: Any, where: str = "") -> Mapping[str, Any]:
    """Refuse a config block carrying a key no parser reads; return it narrowed.

    The return value exists for the one caller holding the block as ``object``
    (YAML hands back anything); everywhere else it is ignored.

    ``where`` locates the block for a human ("#2 on endpoint 'line1'"); it is
    appended to ``spec.what``. Blocks with only accepted keys return silently.

    A block that is not a mapping at all is refused here too. ``tags: ["40001"]``
    is a natural thing to write, and without this it reached the parsers as a
    ``TypeError`` naming string indices — or, once this function existed, as a
    list of the string's individual characters.
    """
    if not isinstance(block, Mapping):
        raise ValueError(
            f"{spec.what}{where} must be a mapping of settings, not {block!r}. "
            f"Accepted: {', '.join(spec.primary)}."
        )
    unknown = [str(k) for k in block if str(k) not in spec.accepted]
    if not unknown:
        return block

    listed = ", ".join(repr(k) for k in unknown)
    noun = "an unknown key" if len(unknown) == 1 else f"{len(unknown)} unknown keys"
    # One wrong key needs no "'rolle':" prefix — there is nothing to attach the
    # advice to but the key already named in the sentence before it.
    if len(unknown) == 1:
        advice = _suggestion(unknown[0], spec)
    else:
        advice = " ".join(
            f"{key!r}: {found}" for key in unknown if (found := _suggestion(key, spec))
        )

    raise ValueError(
        f"{spec.what}{where} has {noun}: {listed}. "
        f"{advice + ' ' if advice else ''}"
        f"Accepted: {', '.join(spec.primary)}. {spec.consequence}"
    )
