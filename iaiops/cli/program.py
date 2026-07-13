"""``iaiops program ...`` — legacy PLC program explainer (A8, read-only).

Structural extraction over EXPORTED program text files (Siemens SCL/ST .scl/.st,
AWL/STL .awl, Rockwell .L5X) — never a live PLC upload. Every element cites
source_file + line (rung number for ladder) so downstream explanations quote
real locations. Advisory: regex/line/xml extraction, not a full grammar.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from iaiops.cli._common import _emit, cli_errors
from iaiops.core.brain import plc_program as ops

program_app = typer.Typer(
    help="Explain exported PLC programs (ST/AWL/L5X): outline / xref / section. "
    "Read-only over files — never uploads from a live PLC.",
    no_args_is_help=True,
)

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
