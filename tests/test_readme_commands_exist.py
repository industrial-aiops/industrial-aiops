"""Every `iaiops ...` command the READMEs teach has to exist.

Both READMEs ship inside the wheel, so a command that does not exist is not a
typo — it is the product telling a customer to run something that will fail. The
zh README taught `iaiops modbus detect-byte-order` for several releases;
`modbus_detect_byte_order` exists, but **only as an MCP tool**. Same shape as
every gap found this week — a capability with one front end, documented as if it
had both — just pointing the other way.

Nothing checked it, so this does. It resolves the command through Typer rather
than by grepping the source: a command that is defined but never registered would
pass a grep and still fail for the reader.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

READMES = ("README.md", "README.zh-CN.md")

#: Shell blocks only. Prose starting a line with "iaiops is designed ..." is a
#: sentence, not an invocation — the first version of this test reported it as a
#: missing command, which is the way a guard like this loses its credibility.
_SHELL_BLOCK = re.compile(r"```(?:bash|sh|console|shell)\n(.*?)```", re.DOTALL)

#: `iaiops <group> <command>` at the start of a line. Two words only: a
#: single-word invocation is a top-level command or a group's help.
_INVOCATION = re.compile(r"^iaiops ([a-z][a-z0-9-]*) ([a-z][a-z0-9-]*)", re.MULTILINE)

#: Words that follow `iaiops <group>` in the docs without being subcommands.
_NOT_COMMANDS = {"--help", "--version"}


def _root():
    return Path(__file__).resolve().parents[1]


def _documented() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for name in READMES:
        text = (_root() / name).read_text("utf-8")
        for block in _SHELL_BLOCK.findall(text):
            found |= {(g, c) for g, c in _INVOCATION.findall(block) if c not in _NOT_COMMANDS}
    return found


def _registered() -> set[tuple[str, str]]:
    """Every (group, command) the CLI actually exposes, straight from Typer."""
    from iaiops.cli._root import app

    pairs: set[tuple[str, str]] = set()
    top = {c.name for c in app.registered_commands if c.name}
    for group in app.registered_groups:
        if not group.name:
            continue
        for command in group.typer_instance.registered_commands:
            if command.name:
                pairs.add((group.name, command.name))
    # `iaiops readiness --json` style: a top-level command followed by a flag is
    # matched by the regex too, so allow (top-level, anything).
    pairs |= {(name, "*") for name in top}
    return pairs


def test_every_documented_command_exists():
    registered = _registered()
    top_level = {g for g, c in registered if c == "*"}
    missing = sorted(
        f"iaiops {g} {c}"
        for g, c in _documented()
        if g not in top_level and (g, c) not in registered
    )
    assert not missing, (
        "The READMEs teach commands that do not exist. Both ship inside the "
        "wheel, so this is what a customer is told to run:\n  " + "\n  ".join(missing)
    )


def test_the_check_can_actually_fail():
    """A finder that matched nothing would pass the test above forever."""
    assert len(_documented()) > 20, _documented()


def test_a_known_good_command_is_seen_by_both_halves():
    assert ("investigate", "plan") in _documented()
    assert ("investigate", "plan") in _registered()


class TestTheStatedToolCountsAreTrue:
    """The READMEs state how many governed tools there are and, more importantly,
    **which ones can change something**. That list is a security claim.

    It was wrong at 0.24.0 prep: both READMEs said "182 = 172 read + 10 writes"
    and listed ten. There are **eleven** writes — `historian_push` was being
    counted as a read. Understating the write surface is the direction that
    matters, and nothing checked it.
    """

    @staticmethod
    def _tools() -> dict[str, str]:
        import importlib
        import os
        import pkgutil

        os.environ["IAIOPS_MCP"] = "all"
        import mcp_server.tools as pkg

        found: dict[str, str] = {}
        for module in pkgutil.iter_modules(pkg.__path__):
            loaded = importlib.import_module(f"mcp_server.tools.{module.name}")
            for name in dir(loaded):
                fn = getattr(loaded, name)
                if getattr(fn, "_is_governed_tool", False):
                    found[name] = (fn.__doc__ or "").split("\n")[0]
        return found

    def test_the_total_matches_what_both_readmes_say(self):
        total = len(self._tools())
        for name in READMES:
            text = (_root() / name).read_text("utf-8")
            assert str(total) in text, f"{name} does not state the real total of {total}"

    def test_no_other_stated_total_contradicts_the_registry(self):
        """The scoping below protects the WRITE list; it left every other count free.

        `README.md` carried "163 of 173 tools are read-only" long after the
        surface reached 182 — the same document, nine tools apart from itself,
        with a guard sitting two paragraphs away. Narrowing a check to the line
        it was written for is correct; assuming that line is the only one making
        the claim is not.
        """
        tools = self._tools()
        registered = len(tools)
        # `[WRITE]` is the same classifier the write-list test uses, so the two
        # cannot disagree about what counts as a write.
        writes = sum(1 for doc in tools.values() if doc.startswith("[WRITE]"))
        pattern = re.compile(r"(\d+) of (?:the )?(\d+) tools")
        for name in ("README.md", "README.zh-CN.md"):
            text = (_root() / name).read_text("utf-8")
            for read_only, total in pattern.findall(text):
                assert int(total) == registered, (
                    f"{name} says {total} tools; the registry has {registered}"
                )
                assert int(read_only) <= registered - writes, (
                    f"{name} calls {read_only} of {total} read-only, but {writes} are "
                    f"high-risk writes — at most {registered - writes} can be read-only"
                )

    @staticmethod
    def _tool_count_line(text: str, total: int) -> str:
        """The one line that states the total and enumerates the writes.

        Scoped to that line on purpose. The first version asked whether each name
        appeared ANYWHERE in the README, which `historian_push` does — it is also
        in the list of tools that can send data off-box. Deleting it from the
        write list left that test green, which is the whole failure mode this
        class exists to catch.
        """
        lines = [ln for ln in text.splitlines() if str(total) in ln and "governed" in ln.lower()]
        if not lines:
            lines = [ln for ln in text.splitlines() if str(total) in ln and "受治理" in ln]
        assert lines, f"no line states the total of {total}"
        return "\n".join(lines)

    def test_every_write_tool_is_named_where_the_writes_are_enumerated(self):
        """Not the count — the NAMES, and not anywhere — in the list itself. A
        reader deciding what to expose has to find each one there, and a tool
        missing from that list reads as safe."""
        tools = self._tools()
        writes = sorted(n for n, doc in tools.items() if doc.startswith("[WRITE]"))
        assert writes, "no write tools found — the classifier stopped working"
        for name in READMES:
            text = (_root() / name).read_text("utf-8")
            line = self._tool_count_line(text, len(tools))
            missing = [w for w in writes if w not in line]
            assert not missing, (
                f"{name}'s tool-count line omits write tools: {', '.join(missing)}. "
                "Appearing elsewhere in the file does not count — a reader looking "
                "for what can change something reads this line."
            )

    def test_no_read_tool_is_listed_among_the_writes(self):
        """The complement. A README that listed everything would pass the test
        above and tell a reader nothing."""
        reads = {n for n, doc in self._tools().items() if doc.startswith("[READ]")}
        assert len(reads) > 100, len(reads)
