"""Named MCP console entry points — convenience shims over ``IAIOPS_MCP``.

The ``IAIOPS_MCP`` env var already delivers the capability (pick which protocol
tool groups a server process exposes). These ``iaiops-mcp-<name>`` scripts are
pure sugar: each injects the equivalent selection then starts the *same* server
via :func:`mcp_server.server.main`. No server logic is duplicated.

The shim set is generated data-driven from the profile menu — every protocol key
in ``PROTOCOL_MODULES`` and every named profile in ``NAMED_PROFILES`` (except the
default ``all``, already served by the plain ``iaiops-mcp``) — so it can never
drift out of sync with the menu. ``server.main`` reads ``IAIOPS_MCP`` at run time,
so the shim sets it *before* delegating.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from mcp_server import server
from mcp_server.profiles import NAMED_PROFILES, PROTOCOL_MODULES

__all__ = ["ENTRYPOINT_SELECTIONS"]

# Every protocol + every named profile except the default 'all' (== plain iaiops-mcp).
ENTRYPOINT_SELECTIONS: tuple[str, ...] = tuple(PROTOCOL_MODULES) + tuple(
    name for name in NAMED_PROFILES if name != "all"
)


def _run(selection: str) -> None:
    """Inject the ``IAIOPS_MCP`` selection, then start the shared server."""
    os.environ["IAIOPS_MCP"] = selection
    server.main()


def _make_main(selection: str) -> Callable[[], None]:
    """Build a no-arg ``main_<selection>`` shim that launches the scoped server."""

    def main() -> None:
        _run(selection)

    main.__name__ = f"main_{selection}"
    main.__qualname__ = main.__name__
    main.__doc__ = (
        f"Launch the iaiops MCP server scoped to IAIOPS_MCP={selection!r} "
        f"(sugar for `IAIOPS_MCP={selection} iaiops-mcp`)."
    )
    return main


# Register one module-level shim per selection so console scripts can target
# ``mcp_server.entrypoints:main_<selection>``.
for _selection in ENTRYPOINT_SELECTIONS:
    globals()[f"main_{_selection}"] = _make_main(_selection)

del _selection
