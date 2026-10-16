"""``iaiops reset`` — remove all local data and settings (dry-run unless --apply).

CLI only, on purpose: there is no MCP tool for it. An agent that can erase the
audit trail is the failure the trail exists to prevent.
"""

from __future__ import annotations

import typer

from iaiops.cli._common import _emit, cli_errors, console, write_command


@write_command
@cli_errors
def reset_cmd(
    apply: bool = typer.Option(
        False, "--apply", help="Actually remove everything (omit = list what would go)."
    ),
) -> None:
    """[HIGH RISK] Remove all iaiops data and settings: config, secrets, audit, history.

    Without --apply, lists what would be removed and changes nothing. With
    --apply it needs a named approver (`iaiops approve reset_cmd --by <name>`)
    and two confirmations. Export evidence first if you may need it
    (`iaiops compliance evidence --out bundle.zip`).
    """
    from iaiops.core.runtime.reset import apply_reset, plan_reset

    plan = plan_reset()
    if not apply:
        _emit({**plan, "dry_run": True})
        return
    console.print(
        f"[red]DESTRUCTIVE:[/] removes {plan['entry_count']} item(s) under "
        f"{', '.join(plan['roots'])} — configuration, encrypted secrets, the audit "
        "trail and its archives, undo and approval state, collected history. "
        f"{len(plan['kept'])} unrecognised item(s) there are kept."
    )
    for note in plan["notes"]:
        console.print(f"[yellow]! {note}[/]")
    if not typer.confirm("Has the evidence you may need been exported?", default=False):
        raise typer.Abort()
    if not typer.confirm("Final confirm — remove everything now?", default=False):
        raise typer.Abort()
    result = apply_reset(plan)
    _emit(result)
    if result["errors"]:
        raise typer.Exit(1)
