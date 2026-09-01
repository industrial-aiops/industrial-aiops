"""``iaiops verify ...`` — executable evidence about the product's own behaviour.

Today one check: ``verify determinism``, which runs a pinned dataset through the
analysis layers under several arms and writes a record of the digests. It exists
because "our analysis is deterministic and needs no model" is a sentence a
validation team is asked to accept, and a sentence is not a test case. This makes
it one: same input, same SHA-256, in a fresh interpreter, with the network
blocked — a step someone can put in an IQ/OQ protocol, run, and sign.

Read-only, no device I/O, no network. Exits 1 when the arms disagree, so it can
be a gate rather than a report nobody reads.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from iaiops.cli._common import _emit, cli_errors, console

verify_app = typer.Typer(
    help="Executable evidence about iaiops itself: determinism of the analysis.",
    no_args_is_help=True,
)


@verify_app.command("determinism")
@cli_errors
def determinism_cmd(
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Write the signable record to this file (.json)."),
    ] = None,
    subprocesses: Annotated[
        bool,
        typer.Option(
            "--subprocesses/--no-subprocesses",
            help="Also re-run in fresh interpreters at two fixed hash seeds (default on).",
        ),
    ] = True,
    quiet: Annotated[
        bool, typer.Option("--quiet", help="Print only the suite digest and the verdict.")
    ] = False,
) -> None:
    """Prove the analysis is reproducible: same input → same digests, no model, no network.

    Runs every check in the reference suite over the pinned reference dataset,
    twice in this process and once in each of two fresh interpreters started at
    different PYTHONHASHSEED values — the arm that catches a set or dict
    iteration order reaching a result, which one run never can. The socket API
    raises throughout, so a computation that went looking for a device or a host
    fails here instead of quietly working on a machine that happened to be online.

    The record separates ``result`` (the reproducible part, the part to sign)
    from ``context`` (when and where this run happened). Two good runs produce
    identical results and different contexts — do not diff whole records.
    """
    from iaiops.core.verify.determinism import VERDICT_REPRODUCIBLE, run_determinism_check

    record = run_determinism_check(subprocesses=subprocesses)
    result = record["result"]

    if out is not None:
        from iaiops.core.governance.evidence import validate_output_path

        path = validate_output_path(out, suffixes=(".json",))
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", "utf-8")
        record = {**record, "written_to": str(path)}

    if quiet:
        _emit(
            {
                "verdict": result["verdict"],
                "suite_digest": result["suite_digest"],
                **({"written_to": record["written_to"]} if "written_to" in record else {}),
            }
        )
    else:
        _emit(record)

    if result["verdict"] != VERDICT_REPRODUCIBLE:
        console.print(
            "[red]Not reproducible.[/] Arms that disagreed: "
            f"{', '.join(result['arms_disagreeing']) or '(none)'}; "
            f"model modules the run pulled in: "
            f"{', '.join(result['model_modules_loaded_by_the_run']) or '(none)'}"
        )
        raise typer.Exit(1)


@verify_app.command("suite")
@cli_errors
def suite_cmd() -> None:
    """List what the determinism check covers, without running it."""
    from iaiops.core.verify import dataset as ds
    from iaiops.core.verify.suite import CHECKS

    _emit(
        {
            "dataset": {"name": ds.NAME, "revision": ds.REVISION, "span_s": ds.total_span_s()},
            "check_count": len(CHECKS),
            "checks": [{"name": c.name, "covers": c.covers} for c in CHECKS],
        }
    )
