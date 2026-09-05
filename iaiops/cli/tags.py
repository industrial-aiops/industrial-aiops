"""``iaiops tags`` — confirm what the point list MEANS, as a table.

HLD §10.1: point-list semantic confirmation is naturally a table interaction
(tens to hundreds of rows to tick or re-categorise), and the CLI's part is to
*export a CSV, let a person edit it, and import it back* rather than ask row by
row on a command line. The App page was ordered after this; this is the fallback
it rests on, and it did not exist.

`apply` emits the config.yaml edit rather than writing it. There is no config
writer in this product, and a YAML round-trip would drop the comments a site
wrote for itself — but the deeper reason is that config.yaml must stay the one
source of truth. `oee measure` reads roles off the config tag objects, so a
parallel store would have let `readiness` report the mapping as met while
`oee measure` still could not run.

Contacts nothing.
"""

from __future__ import annotations

import csv
from pathlib import Path

import typer

from iaiops.cli._common import cli_errors, console

tags_app = typer.Typer(
    help="Confirm what each monitored tag means to the line — export, edit, apply.",
    no_args_is_help=True,
)


@cli_errors
def export_cmd(
    out: Path = typer.Argument(..., help="Where to write the sheet (.csv)."),
) -> None:
    """Write every monitored tag to a sheet for a person to fill in.

    The `role` column comes out EMPTY on purpose — including next to a tag called
    `GoodPartsCounter`. Which tag counts production is process knowledge, and a
    wrong guess yields a plausible-looking OEE, which is worse than an error
    (D16). `declared_role` shows what config.yaml already says, so you can see it
    without it being pre-filled.

    Fill in `role` (one of run_state, total_count, good_count, reject_count) and,
    for run_state, `running_when` — which value means the line is producing.
    """
    from iaiops.core.governance.evidence import validate_output_path
    from iaiops.core.runtime.config import load_config
    from iaiops.core.runtime.tag_sheet import SHEET_COLUMNS, sheet_rows

    path = validate_output_path(out, suffixes=(".csv",))
    rows = sheet_rows(load_config())
    if not rows:
        raise ValueError(
            "No monitored tags to confirm. Find devices first (`iaiops scan run "
            "--targets <cidr>`), then add endpoints and their tags (`iaiops init`)."
        )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(SHEET_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    console.print(
        f"\n[green]✓[/] {len(rows)} tag(s) written to [bold]{path}[/]\n"
        "  [dim]Fill in `role` (run_state, total_count, good_count, reject_count) and,\n"
        "  for run_state, `running_when` — which value means producing.\n"
        "  Nothing was guessed for you: a wrong production counter yields a\n"
        "  plausible OEE, which is worse than an error.[/]\n"
    )


@cli_errors
def apply_cmd(
    sheet: Path = typer.Argument(..., help="The filled-in sheet (.csv)."),
    by: str = typer.Option(..., "--by", help="Who confirmed these."),
    out: Path = typer.Option(None, "--out", help="Write the config patch here instead of stdout."),
) -> None:
    """Check a filled sheet and print the exact config.yaml edit.

    All or nothing: one bad row refuses the whole sheet, because a half-applied
    point list is one nobody can reason about. Blank `role` cells are skipped
    rather than treated as withdrawals — a sheet that has been through a
    spreadsheet loses cells routinely.

    Nothing is written to config.yaml. Paste the patch into the matching `tags:`
    entries, then re-run `iaiops readiness` to see what it unlocked.
    """
    from iaiops.core.governance.evidence import validate_output_path
    from iaiops.core.runtime.config import load_config
    from iaiops.core.runtime.tag_sheet import config_patch, validate_rows

    file = Path(sheet).expanduser()
    if not file.exists():
        raise ValueError(f"No sheet at {file}.")
    with file.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    try:
        config = load_config()
    except Exception:  # noqa: BLE001 — an unconfigured site is a real state
        config = None
    edits = validate_rows(rows, config)
    if not edits:
        console.print(
            f"\n[yellow]?[/] {len(rows)} row(s) read, none confirmed — every `role` "
            "cell is blank.\n  [dim]A blank cell means 'no change', not 'withdraw'.[/]\n"
        )
        return

    patch = config_patch(edits, by=by)
    if out is not None:
        path = validate_output_path(out, suffixes=(".yaml", ".yml"))
        path.write_text(patch, encoding="utf-8")
        console.print(f"\n[green]✓[/] {len(edits)} confirmed — patch written to [bold]{path}[/]\n")
    else:
        console.print(f"\n[green]✓[/] {len(edits)} confirmed. Merge this into config.yaml:\n")
        console.print(patch)
    console.print(
        "[dim]Nothing was written to config.yaml. After merging, run "
        "`iaiops onboard status` for the next step (`iaiops readiness` for the "
        "full list of what it unlocked).[/]\n"
    )


@cli_errors
def page_cmd(
    out: Path = typer.Argument(..., help="Where to write the page (.html)."),
    lang: str = typer.Option("en", "--lang", help="Page language (en, zh)."),
) -> None:
    """Write the same sheet as a page a person ticks through, then downloads.

    HLD §13.9's App front end, delivered as a file rather than a served app: a
    localhost server in an OT box has to answer which address it binds and who
    authenticates, and a page with no identity cannot record WHO confirmed a tag
    — which is the one thing this step exists to capture. The author is supplied
    at `tags apply`, where the refusals also live.

    The page decides nothing. It re-implements no rule: `apply` remains the only
    judge, so the two can never disagree.
    """
    from iaiops.core.governance.evidence import validate_output_path
    from iaiops.core.runtime.config import load_config
    from iaiops.core.runtime.tag_page import render_tag_page

    path = validate_output_path(out, suffixes=(".html", ".htm"))
    from datetime import UTC, datetime

    path.write_text(
        render_tag_page(
            load_config(),
            lang=lang,
            generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        ),
        encoding="utf-8",
    )
    console.print(
        f"\n[green]✓[/] page written to [bold]{path}[/]\n"
        "  [dim]Open it, set the roles, download the sheet, then:\n"
        "  iaiops tags apply sheet.csv --by <you>[/]\n"
    )


tags_app.command("export")(export_cmd)
tags_app.command("page")(page_cmd)
tags_app.command("apply")(apply_cmd)

__all__ = ["tags_app", "export_cmd", "apply_cmd"]
