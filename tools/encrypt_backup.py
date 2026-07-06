#!/usr/bin/env python3
"""Compress and encrypt plain JSON as a controller 6.2.14.11 backup file."""
from __future__ import annotations

import argparse
import gzip
import json
import os
import tempfile
from pathlib import Path
from typing import BinaryIO

from Crypto.Cipher import ARC4


RC4_KEY = (
    b"KW$K:^kk3;^v2l?2^4^hCdurn5/O&g+;F+Hwk=lRTP$_jH5eiQ&/An//cOH$2lD0x"
    b"YDa_FA#!T51@fiXTdL1?kR-:s~e?_-H2-T$du+nrAHbpgN-ybr4u%9$(~-B@edIzlrd"
    b"pnb^%f%_3YZ1s_gYjge8ucjslvY!E!Rkf@Lu=z(-&KtWcd)?Iw%9+9*E=$*S_:p4v/"
    b"Mp9s98=3lYuCdcky$edqFl%O7/1HrI8N@Uz!c%LK!lnuXrsIPn/va%rYUG"
)
CHUNK_SIZE = 1024 * 1024
GZIP_SPOOL_LIMIT = 8 * CHUNK_SIZE


def _default_output_path(input_path: Path) -> Path:
    return input_path.with_suffix(".cfg")


def _validate_json(input_path: Path) -> None:
    try:
        with input_path.open("r", encoding="utf-8") as stream:
            root = json.load(stream)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"input is not valid UTF-8 JSON: {error}") from error

    if not isinstance(root, dict) or next(iter(root), None) != "mainInfo":
        raise ValueError("input JSON must be an object with mainInfo first")


def _compress_and_encrypt(source: BinaryIO, destination: BinaryIO) -> None:
    with tempfile.SpooledTemporaryFile(
        mode="w+b", max_size=GZIP_SPOOL_LIMIT
    ) as compressed:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=compressed,
            compresslevel=6,
            mtime=0,
        ) as gzip_stream:
            while chunk := source.read(CHUNK_SIZE):
                gzip_stream.write(chunk)

        compressed.seek(0)
        cipher = ARC4.new(RC4_KEY)
        while chunk := compressed.read(CHUNK_SIZE):
            destination.write(cipher.encrypt(chunk))


def encrypt_backup(
    input_path: Path,
    output_path: Path,
    *,
    force: bool = False,
) -> None:
    """Validate, compress, and encrypt JSON atomically as a backup."""
    if not input_path.is_file():
        raise FileNotFoundError(f"JSON file not found: {input_path}")
    if input_path.resolve() == output_path.resolve():
        raise ValueError("input and output paths must be different")
    if output_path.exists() and not force:
        raise FileExistsError(f"output already exists: {output_path} (use --force)")
    if not output_path.parent.is_dir():
        raise FileNotFoundError(f"output directory not found: {output_path.parent}")

    _validate_json(input_path)

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            with input_path.open("rb") as source:
                _compress_and_encrypt(source, temporary_file)

        os.replace(temporary_path, output_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compress and encrypt plain JSON as a controller 6.2.14.11 .cfg backup."
        )
    )
    parser.add_argument(
        "input",
        type=Path,
        help="input plain-text JSON (.json)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="output path (default: replace .json with .cfg)",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="overwrite an existing output file",
    )
    args = parser.parse_args()
    output_path = args.output or _default_output_path(args.input)

    try:
        encrypt_backup(args.input, output_path, force=args.force)
    except (OSError, ValueError) as error:
        parser.exit(1, f"error: {error}\n")

    print(f"Compressed and encrypted {args.input} -> {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())