"""``iaiops store`` — what the local store holds, and what may safely leave it.

Continuous collection turns the local store from an incidental by-product into
something with a lifecycle. Measured on this codebase: three tags at 200ms is
2.0 GB a week and 102 GB a year, while the stop events derived from that same
year come to about 3 MB.

So the answer to "where does the data go" is two answers. Raw samples have a
lifetime. Derived facts do not — they are what keeps "what happened in March"
answerable after March's samples are gone.

``prune`` is a dry run unless ``--apply``, and refuses entirely without a seal
watermark: raw samples may only be removed once their value has been extracted.
"""

from __future__ import annotations

from pathlib import Path

import typer

from iaiops.cli._common import _emit, cli_errors, console

store_app = typer.Typer(help="The local sample store: size, retention, pruning.")


def _mb(n: int) -> str:
    return f"{n / 1e6:,.1f} MB"


@cli_errors
def store_status_cmd(
    db: Path = typer.Option(None, "--db"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """How much history is held, how far back, and what the policy says."""
    from iaiops.core.retain.policy import RetentionPolicy
    from iaiops.core.retain.prune import plan_prune
    from iaiops.core.runtime.config import load_config
    from iaiops.core.sink.sqlite_local import local_db_path, store_coverage

    try:
        declared = load_config().retention_raw_days
    except Exception:  # noqa: BLE001 — an unconfigured site still has a store
        declared = None
    policy = RetentionPolicy(raw_days=declared) if declared else RetentionPolicy()

    coverage = store_coverage(db)
    path = Path(db).expanduser() if db else local_db_path()
    size = path.stat().st_size if path.exists() else 0
    planned = plan_prune(db, policy)

    payload = {
        "path": str(path),
        "bytes": size,
        "coverage": coverage,
        "retention": policy.as_dict(),
        "declared_in_config": declared is not None,
        "would_expire": planned["rows_to_remove"],
    }
    if as_json:
        _emit(payload)
        return

    console.print(f"\n[bold]Local store[/] — {path}\n")
    console.print(f"  {coverage['samples']:,} samples · {coverage['tags']} tags · {_mb(size)}")
    if coverage["samples"]:
        console.print(f"  {coverage['oldest']} → {coverage['newest']}")
        console.print(
            f"  best-covered tag {coverage.get('best_covered_tag', '?')!r}: "
            f"{coverage.get('span_days', 0):g} days"
        )
    console.print(f"\n[bold]Retention[/] — {policy.summary}")
    if declared is None:
        console.print(
            "  [yellow]Not declared in config.yaml[/] — the default applies. "
            "Continuous collection without a stated policy fills a disk on a schedule."
        )
    if planned["rows_to_remove"]:
        console.print(
            f"\n  {planned['rows_to_remove']:,} rows are older than "
            f"{planned['cutoff'][:10]} and would expire."
        )
        console.print("  [dim]Run `iaiops store prune` to see what that would do.[/]")


@cli_errors
def store_prune_cmd(
    sealed_before: str = typer.Option(
        None,
        "--sealed-before",
        help="ISO timestamp up to which derived facts exist. Required to actually remove.",
    ),
    db: Path = typer.Option(None, "--db"),
    apply: bool = typer.Option(False, "--apply", help="Actually remove. Irreversible."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Remove expired raw samples. Dry run unless --apply.

    Refuses without --sealed-before: raw samples may only be removed once their
    value has been extracted into derived facts, or the deletion silently
    destroys the only record of a period nobody has looked at yet.
    """
    from datetime import datetime

    from iaiops.core.retain.policy import RetentionPolicy
    from iaiops.core.retain.prune import prune
    from iaiops.core.runtime.config import load_config

    try:
        declared = load_config().retention_raw_days
    except Exception:  # noqa: BLE001
        declared = None
    policy = RetentionPolicy(raw_days=declared) if declared else RetentionPolicy()

    seal = None
    if sealed_before:
        seal = datetime.fromisoformat(sealed_before.replace("Z", "+00:00"))

    result = prune(db, policy, sealed_before=seal, apply=apply)
    if as_json:
        _emit(result)
        return

    if result["status"] == "refused":
        console.print(f"\n[red]Refused.[/] {result['reason']}")
        return
    if not result["applied"]:
        console.print(
            f"\n[bold]Would remove[/] {result['rows_to_remove']:,} rows older than "
            f"{result['cutoff'][:19]}, keeping {result['rows_to_keep']:,}."
        )
        console.print(f"[dim]{result['reason']}[/]")
        return
    console.print(
        f"\n[bold]Removed[/] {result['rows_removed']:,} rows; {result['rows_kept']:,} remain."
    )
    console.print(f"[dim]{result['note']}[/]")


# Effect-based risk (HLD §3.1): a dry run changes nothing and is audited at
# `low`; `--apply` deletes history irreversibly and is audited at `high` behind
# the approval gate. Pruning is destructive in the way an OT write is — there is
# no undo for samples that no longer exist — so it belongs on the same footing.
store_prune_cmd._cli_apply_param = "apply"

store_app.command("status")(store_status_cmd)
store_app.command("prune")(store_prune_cmd)

__all__ = ["store_app"]
