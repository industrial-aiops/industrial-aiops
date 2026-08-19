"""``iaiops scan`` — find what is on a plant network, as gently as possible.

The command order is the workflow, and it is deliberately not the obvious one.
``plan`` comes before ``run`` and is the one an operator is expected to use
first: it emits **nothing**, and prints exactly what a run would do — every host,
every port, every packet class, the worst-case duration, and the explicit list
of what this tool never does. That output is the thing a controls engineer signs
before anyone is allowed to touch the network.

``run`` then does it, stores the result, and can render the report in one step.

Two decisions that show up as flags:

* ``--profile legacy-safe`` exists for the case that decides whether this
  product is ever trusted: 1990s controllers where even a well-formed identify
  request is a risk. It sweeps only, one host at a time.
* ``--approved-by`` is refused nowhere and required by the ``standard`` and
  ``deep`` profiles. The library enforces it, not this layer, so calling the
  API directly cannot route around it.
"""

from __future__ import annotations

from pathlib import Path

import typer

from iaiops.cli._common import _emit, cli_errors, console

scan_app = typer.Typer(help="Site discovery — scan a network and inventory what is on it.")


def _build_plan(
    targets: str,
    profile: str,
    exclude: str,
    protocols: str,
    approved_by: str,
    ticket: str,
    seed: int,
    accept_large_scope: bool,
):
    """Turn CLI strings into a :class:`ScanPlan`, or raise a teaching error."""
    from iaiops.core.discovery.types import Authorization, ScanPlan

    cidrs, hosts = [], []
    for item in (t.strip() for t in targets.split(",")):
        if not item:
            continue
        (cidrs if "/" in item else hosts).append(item)
    if not cidrs and not hosts:
        raise ValueError(
            "No target given. Pass a CIDR or host, e.g. --targets 10.0.0.0/24 "
            "or --targets 10.0.0.5,10.0.0.6"
        )
    return ScanPlan(
        site="",
        cidrs=tuple(cidrs),
        hosts=tuple(hosts),
        excluded=tuple(x.strip() for x in exclude.split(",") if x.strip()),
        protocols=tuple(p.strip().lower() for p in protocols.split(",") if p.strip()),
        profile=profile,
        authorization=Authorization(approved_by=approved_by, ticket=ticket),
        seed=seed,
        accept_large_scope=accept_large_scope,
    )


def _with_site_and_stages(plan, site: str):
    """Apply the site label and the profile's stage ladder to a plan."""
    import dataclasses

    from iaiops.core.discovery.profiles import get_profile

    return dataclasses.replace(plan, site=site, stages=get_profile(plan.profile).stages)


TARGETS = typer.Option(
    ...,
    "--targets",
    "-t",
    help="Comma-separated CIDRs and/or hosts, e.g. 10.0.0.0/24 or 10.0.0.5,10.0.0.6.",
)
PROFILE = typer.Option(
    "inventory",
    "--profile",
    "-p",
    help="passive | inventory | standard | deep | legacy-safe. See `scan profiles`.",
)
EXCLUDE = typer.Option("", "--exclude", help="Comma-separated addresses to never touch.")
PROTOCOLS = typer.Option(
    "", "--protocols", help="Only these protocols. NARROWS the port set; never widens it."
)
APPROVED_BY = typer.Option("", "--approved-by", help="Who signed this scan off.")
TICKET = typer.Option("", "--ticket", help="Change ticket / work order reference.")
SEED = typer.Option(0, "--seed", help="Host-order shuffle seed. Same seed, same order.")
SITE = typer.Option("", "--site", help="Site / plant name, recorded in the report.")
BIG = typer.Option(False, "--accept-large-scope", help="Acknowledge a deliberately huge CIDR.")


@scan_app.command("profiles")
@cli_errors
def profiles_cmd() -> None:
    """List the scan profiles: what each stage does and whether sign-off is needed."""
    from iaiops.core.discovery.profiles import profile_menu

    _emit(list(profile_menu()))


@scan_app.command("plan")
@cli_errors
def plan_cmd(
    targets: str = TARGETS,
    profile: str = PROFILE,
    exclude: str = EXCLUDE,
    protocols: str = PROTOCOLS,
    approved_by: str = APPROVED_BY,
    ticket: str = TICKET,
    seed: int = SEED,
    site: str = SITE,
    accept_large_scope: bool = BIG,
    as_json: bool = typer.Option(False, "--json", help="Machine-readable preview."),
    out: Path = typer.Option(None, "--out", help="Also write the preview to a file."),
) -> None:
    """Preview a scan WITHOUT sending anything. The artifact an operator signs.

    Prints every host and port that would be touched, every class of packet that
    would be sent, the worst-case duration, and the explicit list of what this
    tool never does. Run this first; run it on a network you have not been given
    permission for, because it costs that network nothing.
    """
    from iaiops.core.discovery.preview import plan_preview, preview_text

    plan = _with_site_and_stages(
        _build_plan(
            targets, profile, exclude, protocols, approved_by, ticket, seed, accept_large_scope
        ),
        site,
    )
    if as_json:
        _emit(plan_preview(plan))
    else:
        console.print(preview_text(plan))

    if out is not None:
        from iaiops.core.governance.evidence import validate_output_path

        path = validate_output_path(out, suffixes=(".txt", ".json", ".md"))
        # The FILE's format follows its suffix; ``--json`` only ever governed
        # stdout. Tying the file to the flag meant `--out preview.json` (without
        # `--json`) wrote plain text under a .json name — an extension that lies
        # about its contents, which is worse than either format alone.
        body = _json(plan_preview(plan)) if path.suffix.lower() == ".json" else preview_text(plan)
        path.write_text(body, encoding="utf-8")
        console.print(f"[dim]written to {path}[/]")


def _json(data: object) -> str:
    import json

    return json.dumps(data, indent=2, default=str)


@scan_app.command("run")
@cli_errors
def run_cmd(
    targets: str = TARGETS,
    profile: str = PROFILE,
    exclude: str = EXCLUDE,
    protocols: str = PROTOCOLS,
    approved_by: str = APPROVED_BY,
    ticket: str = TICKET,
    seed: int = SEED,
    site: str = SITE,
    accept_large_scope: bool = BIG,
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the preview confirmation (for scripts and CI)."
    ),
    report: Path = typer.Option(None, "--report", help="Also write the HTML report here."),
    db: Path = typer.Option(None, "--db", help="Store file (default: the local iaiops store)."),
    no_store: bool = typer.Option(False, "--no-store", help="Do not persist the result."),
) -> None:
    """Run the scan, store it, and optionally render the report.

    Unless ``--yes`` is given, the zero-emission preview is printed and confirmed
    first — the same artifact ``scan plan`` produces. Someone about to touch a
    plant network should see what they are about to do, once, by default.
    """
    from iaiops.core.discovery.preview import preview_text
    from iaiops.core.discovery.report import render_result
    from iaiops.core.discovery.runner import run_scan
    from iaiops.core.sink.scan_store import save_scan

    plan = _with_site_and_stages(
        _build_plan(
            targets, profile, exclude, protocols, approved_by, ticket, seed, accept_large_scope
        ),
        site,
    )

    if not yes:
        console.print(preview_text(plan))
        try:
            proceed = typer.confirm("\nProceed and send the above?", default=False)
        except (typer.Abort, EOFError) as exc:
            # Nobody is there to answer. Detecting that by asking and failing is
            # better than guessing from ``isatty()``, which is wrong in both
            # directions — a test harness and a piped heredoc are both
            # answerable non-TTYs. Refusing is the only honest outcome: the
            # alternative is scanning a plant network because a pipeline could
            # not say no.
            raise ValueError(
                "No answer available for the confirmation prompt, so nothing was sent. "
                "Re-run with --yes once you have reviewed `iaiops scan plan`, which "
                "sends nothing."
            ) from exc
        if not proceed:
            console.print("[yellow]Nothing was sent.[/]")
            raise typer.Exit(0)

    result = run_scan(plan)

    scan_id = ""
    if not no_store:
        scan_id = save_scan(result, db)

    if report is not None:
        from iaiops.core.governance.evidence import validate_output_path

        path = validate_output_path(report, suffixes=(".html", ".htm"))
        path.write_text(render_result(result), encoding="utf-8")
        console.print(f"[dim]report written to {path}[/]")

    _emit(
        {
            "scan_id": scan_id or "(not stored)",
            "verdict": result.verdict,
            "hosts_seen": len(result.hosts),
            "devices_identified": len(result.devices),
            "wire_summary": result.wire_summary,
            "devices": [
                {
                    "ip": host.ip,
                    "mac": host.mac,
                    "protocols": [c.protocol for c in host.protocols],
                    "identity": host.identity,
                }
                for host in result.devices
            ],
            "notes": list(result.notes),
        }
    )


@scan_app.command("list")
@cli_errors
def list_cmd(
    db: Path = typer.Option(None, "--db", help="Store file (default: the local iaiops store)."),
    limit: int = typer.Option(20, "--limit", help="How many to show."),
) -> None:
    """List stored scans, newest first."""
    from dataclasses import asdict

    from iaiops.core.sink.scan_store import list_scans

    _emit([asdict(row) for row in list_scans(db, limit)])


@scan_app.command("report")
@cli_errors
def report_cmd(
    scan_id: str = typer.Argument("", help="Scan id. Omit for the most recent scan."),
    out: Path = typer.Option(..., "--out", help="Output HTML file."),
    db: Path = typer.Option(None, "--db", help="Store file (default: the local iaiops store)."),
) -> None:
    """Render a stored scan to one self-contained HTML file.

    The file loads nothing from anywhere and makes no network request when
    opened — it is meant to be mailed to someone, or read on an air-gapped
    laptop in a plant office.
    """
    from iaiops.core.discovery.report import render_html
    from iaiops.core.governance.evidence import validate_output_path
    from iaiops.core.sink.scan_store import ScanNotFound, list_scans, load_scan

    # Checked before the id is even looked at. "That id is not here" and "nothing
    # has ever been stored" are different problems, and someone who typed an id
    # from memory against a fresh machine needs the second answer, not a path.
    stored = list_scans(db, 1)
    if not stored:
        raise ScanNotFound(
            "No scan has been stored yet, so there is nothing to report on. "
            "Run `iaiops scan run --targets <cidr-or-host>` first."
        )
    scan_id = scan_id or stored[0].scan_id

    path = validate_output_path(out, suffixes=(".html", ".htm"))
    record = load_scan(scan_id, db)
    html = render_html(record)
    path.write_text(html, encoding="utf-8")
    _emit(
        {
            "path": str(path),
            "scan_id": scan_id,
            "site": record.get("site"),
            "devices": record.get("device_count"),
            "bytes": len(html.encode("utf-8")),
        }
    )


@scan_app.command("prune")
@cli_errors
def prune_cmd(
    keep: int = typer.Option(..., "--keep", help="How many of the newest scans to keep."),
    db: Path = typer.Option(None, "--db", help="Store file (default: the local iaiops store)."),
) -> None:
    """Delete all but the newest --keep stored scans.

    Nothing is ever pruned automatically. An on-box store that silently
    discarded last month's survey would be worse than one that grows.
    """
    from iaiops.core.sink.scan_store import prune_scans

    _emit({"deleted": prune_scans(keep, db), "kept": keep})


__all__ = ["scan_app"]
