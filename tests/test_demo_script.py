"""The demo's first line of output must not be a warning about the demo.

`./demo/oee-line/run_demo.sh` opens with `iaiops readiness`, and until
2026-08-26 the first thing a prospect saw was:

    Security warning: /var/folders/.../.iaiops has permissions 0o755
    (should be 700). Run: chmod 700 ...

The warning was RIGHT — `mkdir -p` lands at 0755 because its mode is masked by
umask. The product creates its own directories correctly (`iaiops/cli/init.py`
chmods both, and `core/governance/audit.py` carries the comment explaining why
mkdir's mode is not enough); the demo script was the one place that did not, so
the tool's own showcase opened by scolding itself.

These tests execute the shipped script's setup lines rather than restating them,
so deleting the `chmod` fails here instead of passing a test that was written to
match.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]
DEMO = REPO / "demo" / "oee-line" / "run_demo.sh"

#: The setup block, delimited by lines that are load-bearing for the demo itself
#: (the isolated HOME, and the config every step reads). The end moved when the
#: config write became a function: the demo now starts from a config with NO tag
#: roles and declares them mid-run, so the block ends at the CALL rather than at
#: the chmod inside it — slicing to the chmod cut the function in half, and the
#: extracted block did not parse.
_START = 'DEMO_HOME="$(mktemp -d)"'
_END = "write_config bare"


def _setup_block() -> str:
    body = DEMO.read_text(encoding="utf-8")
    start, end = body.index(_START), body.index(_END) + len(_END)
    return body[start:end]


@pytest.mark.skipif(not DEMO.exists(), reason="the demo is not present")
class TestTheDemoLeavesNothingWorldReadable:
    def _run_setup(self, tmp_path: Path) -> Path:
        """Execute the shipped setup lines and return the HOME they made."""
        script = f'PY={sys.executable!r}\n{_setup_block()}\necho "$DEMO_HOME"'
        out = subprocess.run(  # noqa: S603 — our own file, our own interpreter
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            check=True,
            cwd=tmp_path,
            env={**os.environ, "TMPDIR": str(tmp_path)},
        )
        return Path(out.stdout.strip().splitlines()[-1])

    def test_the_config_directory_is_private(self, tmp_path):
        home = self._run_setup(tmp_path)
        mode = stat.S_IMODE((home / ".iaiops").stat().st_mode)
        assert mode == 0o700, f"the demo's own config dir is {oct(mode)}"

    def test_the_config_file_is_private(self, tmp_path):
        """Already true before the fix — kept so the pair cannot regress apart.
        A 600 file inside a 755 directory still leaks its NAME and its siblings."""
        home = self._run_setup(tmp_path)
        assert stat.S_IMODE((home / ".iaiops" / "config.yaml").stat().st_mode) == 0o600

    def test_readiness_over_that_home_warns_about_nothing(self, tmp_path):
        """The behavioural assertion — what the room actually sees. Runs the real
        command over the directory the real script built."""
        home = self._run_setup(tmp_path)
        out = self._readiness(home)
        assert "Security warning" not in out, out[:400]

    def test_that_check_would_have_seen_the_warning(self, tmp_path):
        """The complement, and NOT optional. The first version of the test above
        shelled out to `python -m iaiops`, which does not exist — the package has
        no `__main__` — so it asserted that a "No module named" error contains no
        security warning, and passed whether or not the fix was there.

        This runs the same command over a 0755 directory and requires the warning
        to appear, which is the only thing that proves the assertion above is
        looking at real output."""
        home = self._run_setup(tmp_path)
        (home / ".iaiops").chmod(0o755)
        assert "Security warning" in self._readiness(home)

    @staticmethod
    def _readiness(home: Path) -> str:
        """Run the real CLI entry point (`iaiops = "iaiops.cli:app"`)."""
        out = subprocess.run(  # noqa: S603
            [sys.executable, "-c", "from iaiops.cli import app; app()", "readiness"],
            capture_output=True,
            text=True,
            cwd=REPO,
            env={**os.environ, "HOME": str(home)},
        )
        return out.stdout + out.stderr

    def test_the_setup_block_was_actually_found(self):
        """The guard's own smoke test: if the delimiters stop matching, every
        assertion above would run against an empty script and pass."""
        block = _setup_block()
        assert "mkdir -p" in block and "config.yaml" in block
        assert "endpoints:" in block, "the config the demo's four commands read"


@pytest.mark.skipif(not DEMO.exists(), reason="the demo is not present")
class TestTheDemoStaysIsolated:
    def test_it_never_writes_to_the_operators_own_home(self):
        """The promise the script prints at the end. Every iaiops invocation in
        it must carry the temporary HOME — one that does not is one that writes
        into the operator's real store and audit log."""
        for line in DEMO.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or "$IAIOPS " not in stripped:
                continue
            assert 'HOME="$DEMO_HOME"' in stripped, stripped
