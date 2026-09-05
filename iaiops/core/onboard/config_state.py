"""What config.yaml currently says, and — separately — whether it could be read.

Small, and shared, because the distinction it draws was got wrong in two places
at once: an absent config and an unparseable config are not the same state, and
collapsing them let ``onboard draft`` offer endpoints a site had already tuned.
``onboard status`` had it right from the start via ``facts["config_error"]``;
this puts both front ends on the same footing.

The address half exists for the second half of the same guard: the draft's own
header tells the reader to rename what it emits, so recognising an endpoint by
the name the draft generated works exactly once.
"""

from __future__ import annotations

from typing import Any


def endpoint_address(target: Any) -> str:
    """A configured endpoint's address, as the draft would have written it.

    Used to recognise an endpoint that is already configured under a name the
    site chose. Matching on the NAME alone stops working the moment somebody
    takes the draft's own advice — its header says "rename this" — because the
    next scan then re-offers ``opcua-10-0-0-9`` as new and the site ends up with
    the same device configured twice.
    """
    protocol = str(getattr(target, "protocol", "")).strip().lower()
    for field in ("endpoint_url", "agent_url", "host"):
        value = str(getattr(target, field, "") or "").strip().lower()
        if value:
            return f"{protocol}|{value}"
    return ""


def existing_endpoint_names() -> tuple[tuple[str, ...], str]:
    """The endpoint names config.yaml already defines, and why we could not tell.

    A bare ``except`` here returned "no endpoints exist" for two different
    states. A config that is ABSENT really has none — the ordinary first run,
    and ``load_config`` already returns an empty config for it rather than
    raising, so no branch here is needed and a ``FileNotFoundError`` clause
    written for it was dead code that looked like handling. A config that will
    not PARSE has however many endpoints it has, and answering () for that
    disarmed the guard which keeps a re-scan from handing someone a block that
    replaces an endpoint their site has already tuned. Reproduced: with a good
    config the draft withheld the endpoint; with the same file plus one bad
    indent it offered it as new.
    """
    try:
        from iaiops.core.runtime.config import load_config

        targets = load_config().targets or ()
        return tuple(str(getattr(t, "name", "")) for t in targets), ""
    except Exception as exc:  # noqa: BLE001 — a broken config is a state, not a crash
        return (), f"{type(exc).__name__}: {exc}"


def existing_endpoints() -> tuple[tuple[str, ...], tuple[str, ...], str]:
    """Names, addresses, and the reason we could not read them."""
    try:
        from iaiops.core.runtime.config import load_config

        targets = load_config().targets or ()
    except Exception as exc:  # noqa: BLE001 — a broken config is a state, not a crash
        return (), (), f"{type(exc).__name__}: {exc}"
    names = tuple(str(getattr(t, "name", "")) for t in targets)
    addresses = tuple(a for a in (endpoint_address(t) for t in targets) if a)
    return names, addresses, ""


__all__ = ["endpoint_address", "existing_endpoint_names", "existing_endpoints"]
