"""``iaiops program ...`` — PLC program explainer and change baseline (read-only).

Structural extraction over EXPORTED program text files (Siemens SCL/ST .scl/.st,
AWL/STL .awl, Rockwell .L5X) — never a live PLC upload. Every element cites
source_file + line (rung number for ladder) so downstream explanations quote
real locations. Advisory: regex/line/xml extraction, not a full grammar.

``snapshot`` / ``drift`` / ``history`` / ``forget`` add the change-control half:
record the structure of the version you consider approved, then ask later
exports whether anything moved. The store holds block names, hashes and counts —
never a declaration, a source line or a comment.
The verdict vocabulary is small on purpose — ``identical`` requires the same
SHA-256, and matching structure over different bytes is reported as *changed
outside the extracted structure*, never as a clearance.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from iaiops.cli._common import _emit, cli_errors
from iaiops.core.brain import plc_program as ops

program_app = typer.Typer(
    help="Explain and baseline exported PLC programs (ST/AWL/L5X): outline / xref / "
    "section / snapshot / drift. Read-only over files — never uploads from a live PLC.",
    no_args_is_help=True,
)

NameOption = Annotated[
    str | None,
    typer.Option(
        "--name",
        help="Program identity across exports. Defaults to the file's stem — the "
        "export path changes, the program does not.",
    ),
]

PathArg = Annotated[
    Path, typer.Argument(help="Exported program file (.st/.scl/.awl/.l5x/.txt, ≤5 MB)")
]


@program_app.command("outline")
@cli_errors
def outline_cmd(
    path: PathArg,
    max_blocks: Annotated[int, typer.Option(help="Cap on blocks listed")] = 50,
    max_vars: Annotated[int, typer.Option(help="Cap on variables per block")] = 100,
) -> None:
    """Structural outline: blocks, VAR sections, branches, timers, call graph."""
    outline = ops.outline_program(str(path))
    _emit(ops.outline_to_bounded_dict(outline, max_blocks=max_blocks, max_vars_per_block=max_vars))


@program_app.command("xref")
@cli_errors
def xref_cmd(
    path: PathArg,
    symbol: Annotated[
        str,
        typer.Argument(help="Symbol / tag / absolute address (e.g. Motor_Run, DB10.DBX0.1, M0.0)"),
    ],
) -> None:
    """Every read/write/call/declare site of a symbol, with lines quoted."""
    hits = ops.find_symbol(str(path), symbol)
    _emit(
        {
            "symbol": symbol,
            "hit_count": len(hits),
            "hits": [
                {
                    "access": h.access,
                    "block": h.block,
                    "source_file": h.source_file,
                    "line": h.line,
                    "source_line": h.source_line,
                }
                for h in hits
            ],
        }
    )


@program_app.command("section")
@cli_errors
def section_cmd(
    path: PathArg,
    block: Annotated[
        str, typer.Argument(help="Block/routine name (FB_x, OB1, MainProgram.MainRoutine)")
    ],
    max_lines: Annotated[int, typer.Option(help="Cap on source lines returned")] = 200,
) -> None:
    """Source text of one named block (capped), for targeted explanation."""
    _emit(ops.block_section(str(path), block, max_lines=max_lines))


@program_app.command("snapshot")
@cli_errors
def snapshot_cmd(
    path: PathArg,
    name: NameOption = None,
    label: Annotated[str, typer.Option(help="Short label, e.g. 'approved v3.2 / MOC-118'")] = "",
    note: Annotated[str, typer.Option(help="Free note recorded with the snapshot")] = "",
) -> None:
    """Record this export's structure as a baseline to compare later ones against.

    Re-snapshotting a byte-identical file records nothing and says so — a history
    padded with identical rows hides the rows that are not.
    """
    from iaiops.core.brain import program_baseline as pb

    _emit(pb.take_snapshot(str(path), name=name, label=label, note=note))


@program_app.command("drift")
@cli_errors
def drift_cmd(
    path: PathArg,
    name: NameOption = None,
    against: Annotated[
        str | None, typer.Option("--against", help="Snapshot id (default: the latest)")
    ] = None,
) -> None:
    """Has this program changed since the approved snapshot — and what moved?

    ``identical`` means the same SHA-256 and nothing else. ``logic_changed`` names
    the blocks and which categories differ. ``changed_outside_extracted_structure``
    means the bytes differ while every block fingerprint matched — usually comments
    or formatting, but these parsers extract structure rather than parse a grammar,
    so read the diff. It is a reason to look, not a clearance.
    """
    from iaiops.core.brain import program_baseline as pb

    _emit(pb.check_drift(str(path), name=name, against=against))


@program_app.command("history")
@cli_errors
def history_cmd(
    name: NameOption = None,
) -> None:
    """Tracked programs, or one program's snapshot history (no source stored)."""
    from iaiops.core.brain import program_baseline as pb

    _emit(pb.history(name))


@program_app.command("compare")
@cli_errors
def compare_cmd(
    name: Annotated[str, typer.Argument(help="Tracked program name")],
    before: Annotated[str, typer.Argument(help="Earlier snapshot id")],
    after: Annotated[str, typer.Argument(help="Later snapshot id")],
) -> None:
    """Diff two stored snapshots of the same program."""
    from iaiops.core.brain import program_baseline as pb

    _emit(pb.compare_snapshots(name, before, after))


@program_app.command("forget")
@cli_errors
def forget_cmd(
    name: Annotated[str, typer.Argument(help="Tracked program name")],
    keep: Annotated[int, typer.Option(help="Keep this many most-recent snapshots")] = 0,
) -> None:
    """Drop a program's snapshot history. Nothing is ever pruned automatically."""
    from iaiops.core.brain import program_baseline as pb

    _emit(pb.forget(name, keep=keep))


@program_app.command("xref-config")
@cli_errors
def xref_config_cmd(
    path: PathArg,
    endpoint: Annotated[
        str, typer.Option("--endpoint", help="Configured endpoint whose tags are joined")
    ],
    live: Annotated[
        bool,
        typer.Option(
            "--live", help="Also read the matched points now (read-only; a failed read is a gap)"
        ),
    ] = False,
) -> None:
    """Which program address is which configured point — exact address match only.

    Never by name: a label that reads like a symbol is not a match. Where the
    program format and the endpoint's protocol share no address space the
    result says why and lists nothing.
    """
    from iaiops.cli._common import resolve_target
    from iaiops.core.brain.plc_program import field_live, field_xref

    target = resolve_target(endpoint)
    result = field_xref.xref_program_endpoint(str(path), target)
    if live:
        result = {**result, "live": field_live.read_matched(target, result)}
    _emit(result)


@program_app.command("doc")
@cli_errors
def doc_cmd(
    path: PathArg,
    out: Annotated[Path, typer.Option("--out", help="HTML file to write (.html/.htm)")],
    endpoint: Annotated[
        str | None,
        typer.Option(
            "--endpoint", help="Also cross-reference this endpoint's points (exact address only)"
        ),
    ] = None,
    name: NameOption = None,
) -> None:
    """A self-contained HTML document of one exported program.

    Blocks, variables, I/O list, cross-reference, call graph and — when a
    snapshot exists — change history; with --endpoint, which configured point is
    which program address. Deterministic (same inputs, same bytes), zero network,
    no LLM. The program file is only read.
    """
    from iaiops.cli._common import resolve_target
    from iaiops.core.brain.plc_program import program_doc
    from iaiops.core.governance.evidence import validate_output_path

    target_path = validate_output_path(out, suffixes=(".html", ".htm"))
    target = resolve_target(endpoint) if endpoint else None
    html = program_doc.render(str(path), target=target, name=name)
    target_path.write_text(html, encoding="utf-8")
    _emit({"written": str(target_path), "bytes": len(html.encode("utf-8"))})
