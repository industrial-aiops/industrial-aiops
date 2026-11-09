"""Build the single-layer Margo rc.3 Compose Archive for OCI publishing."""

from __future__ import annotations

import argparse
import gzip
import io
import json
import tarfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "deploy" / "margo" / "package.compose.yaml"
COMPONENT = "iaiops"


def build_archive(version: str, output: Path, annotations: Path) -> None:
    """Write a reproducible archive and ORAS layer-annotation file."""
    with (ROOT / "pyproject.toml").open("rb") as fh:
        declared = tomllib.load(fh)["project"]["version"]
    if version != declared:
        raise ValueError(f"archive version {version!r} differs from pyproject {declared!r}")
    payload = SOURCE.read_bytes()
    output.parent.mkdir(parents=True, exist_ok=True)
    annotations.parent.mkdir(parents=True, exist_ok=True)
    with (
        output.open("wb") as raw,
        gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as gz,
    ):
        with tarfile.open(fileobj=gz, mode="w") as archive:
            directory = tarfile.TarInfo(COMPONENT + "/")
            directory.type = tarfile.DIRTYPE
            directory.mode = 0o755
            directory.mtime = 0
            archive.addfile(directory)
            member = tarfile.TarInfo(COMPONENT + "/compose.yaml")
            member.size = len(payload)
            member.mode = 0o644
            member.mtime = 0
            archive.addfile(member, io.BytesIO(payload))
    annotations.write_text(
        json.dumps(
            {
                output.name: {
                    "org.margo.component.type": "compose",
                    "org.margo.component.version": version,
                    "org.opencontainers.image.version": version,
                    "org.opencontainers.image.authors": "wei <zhouwei008@gmail.com>",
                    "org.opencontainers.image.description": "Governed OT tap Compose component",
                }
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument("output", type=Path)
    parser.add_argument("annotations", type=Path)
    args = parser.parse_args()
    build_archive(args.version, args.output, args.annotations)


if __name__ == "__main__":
    main()
