"""Shared helpers for iaiops CLI sub-modules."""

from __future__ import annotations

import functools
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console

console = Console()

EndpointOption = Annotated[
    str | None, typer.Option("--endpoint", "-e", help="Endpoint name from config")
]


def _cli_error_types() -> tuple[type[BaseException], ...]:
    """Exceptions translated to a one-line teaching error instead of a traceback."""
    from iaiops.core.runtime.connection import OTConnectionError

    return (OTConnectionError, KeyError, OSError, ValueError)


def cli_errors(fn: Callable) -> Callable:
    """Translate known exceptions into one red line + exit code 1."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except (typer.Exit, typer.Abort):
            raise
        except _cli_error_types() as e:
            message = str(e)
            if isinstance(e, KeyError):
                message = f"Missing required key: {message}"
            console.print(f"[red]Error: {message}[/]")
            raise typer.Exit(1) from e

    return wrapper


def get_manager(config_path: Path | None = None):
    """Return a ConnectionManager built from config."""
    from iaiops.core.runtime.config import load_config
    from iaiops.core.runtime.connection import ConnectionManager

    return ConnectionManager(load_config(config_path))


def resolve_target(endpoint: str | None):
    """Resolve an endpoint target by name (or the default endpoint)."""
    return get_manager().target(endpoint)
