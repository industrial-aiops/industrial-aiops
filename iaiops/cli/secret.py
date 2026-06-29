"""``iaiops secret`` — manage the encrypted credential store.

Secrets are stored in ``~/.iaiops/secrets.enc`` (Fernet, key derived from a
master password via scrypt). Nothing here ever prints a secret value.
"""

from __future__ import annotations

import getpass
from typing import Annotated

import typer

from iaiops.cli._common import cli_errors, console
from iaiops.core.runtime.config import SECRET_ENV_PREFIX, SECRET_ENV_SUFFIX
from iaiops.core.runtime.secretstore import (
    SECRETS_FILE,
    SecretStore,
    check_permissions,
    migrate_legacy_env,
    resolve_master_password,
)

secret_app = typer.Typer(
    name="secret",
    help="Manage the encrypted credential store (secrets.enc).",
    no_args_is_help=True,
)

NameArg = Annotated[str, typer.Argument(help="Endpoint name the secret belongs to")]


@secret_app.command("set")
@cli_errors
def secret_set(
    name: NameArg,
    value: Annotated[
        str | None,
        typer.Option("--value", help="Secret value (omit to be prompted, hidden)"),
    ] = None,
) -> None:
    """Store (or replace) a secret for an endpoint — value is read hidden."""
    password = resolve_master_password(confirm_if_new=True)
    if value is None:
        value = getpass.getpass(f"Secret for '{name}' (hidden): ")
    store = SecretStore.unlock(password)
    store.set(name, value)
    console.print(f"[green]✓ Stored encrypted secret for '{name}' in {SECRETS_FILE}[/]")


@secret_app.command("list")
@cli_errors
def secret_list() -> None:
    """List endpoint names that have a stored secret (values never shown)."""
    store = SecretStore.unlock()
    names = store.names()
    if not names:
        console.print("[yellow]No secrets stored yet. Add one: iaiops secret set <name>[/]")
        return
    console.print("[bold]Stored secrets:[/]")
    for n in names:
        console.print(f"  • {n}")
    warning = check_permissions()
    if warning:
        console.print(f"[yellow]! {warning}[/]")


@secret_app.command("rm")
@cli_errors
def secret_rm(name: NameArg) -> None:
    """Delete a stored secret."""
    store = SecretStore.unlock()
    store.delete(name)
    console.print(f"[green]✓ Deleted secret for '{name}'[/]")


@secret_app.command("migrate")
@cli_errors
def secret_migrate() -> None:
    """Import secrets from a legacy plaintext .env into the encrypted store."""
    password = resolve_master_password(confirm_if_new=True)
    imported = migrate_legacy_env(SECRET_ENV_PREFIX, SECRET_ENV_SUFFIX, password)
    if not imported:
        console.print("[yellow]Nothing to migrate (no legacy .env secrets found).[/]")
        return
    console.print(f"[green]✓ Imported {len(imported)} secret(s): {', '.join(imported)}[/]")
    console.print("[dim]The old .env was renamed to .env.migrated — delete it once verified.[/]")


@secret_app.command("rotate-password")
@cli_errors
def secret_rotate_password() -> None:
    """Re-encrypt the whole store under a new master password."""
    console.print("[bold]Unlock with the current master password:[/]")
    store = SecretStore.unlock()
    new_pw = getpass.getpass("New master password: ")
    confirm = getpass.getpass("Confirm new master password: ")
    if new_pw != confirm:
        console.print("[red]Passwords did not match. Aborted.[/]")
        raise typer.Exit(1)
    store.with_password(new_pw)
    console.print("[green]✓ Master password rotated. Update IAIOPS_MASTER_PASSWORD.[/]")
