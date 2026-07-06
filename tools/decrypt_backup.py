#!/usr/bin/env python3
"""Decrypt a controller 6.2.14.11 backup to plain-text JSON."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import zlib
from pathlib import Path
from typing import BinaryIO

from Crypto.Cipher import ARC4


RC4_KEY = (
    b"KW$K:^kk3;^v2l?2^4^hCdurn5/O&g+;F+Hwk=lRTP$_jH5eiQ&/An//cOH$2lD0x"
    b"YDa_FA#!T51@fiXTdL1?kR-:s~e?_-H2-T$du+nrAHbpgN-ybr4u%9$(~-B@edIzlrd"
    b"pnb^%f%_3YZ1s_gYjge8ucjslvY!E!Rkf@Lu=z(-&KtWcd)?Iw%9+9*E=$*S_:p4v/"
    b"Mp9s98=3lYuCdcky$edqFl%O7/1HrI8N@Uz!c%LK!lnuXrsIPn/va%rYUG"
)
GZIP_HEADER = b"\x1f\x8b\x08"
CHUNK_SIZE = 1024 * 1024


def _default_output_path(input_path: Path) -> Path:
    if input_path.suffix.lower() == ".cfg":
        return input_path.with_suffix(".json")
    return input_path.with_name(f"{input_path.name}.json")


def _decrypt_and_decompress(source: BinaryIO, destination: BinaryIO) -> None:
    cipher = ARC4.new(RC4_KEY)
    decompressor = zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)

    first_chunk = source.read(CHUNK_SIZE)
    decrypted = cipher.decrypt(first_chunk)
    if not decrypted.startswith(GZIP_HEADER):
        raise ValueError(
            "decrypted data is not a GZIP/DEFLATE stream; "
            "the file or controller key may not match 6.2.14.11"
        )

    try:
        destination.write(decompressor.decompress(decrypted))
        while chunk := source.read(CHUNK_SIZE):
            destination.write(decompressor.decompress(cipher.decrypt(chunk)))
        destination.write(decompressor.flush())
    except zlib.error as error:
        raise ValueError(f"decrypted data has an invalid GZIP stream: {error}") from error

    if not decompressor.eof:
        raise ValueError("decrypted GZIP stream is truncated")
    if decompressor.unused_data:
        raise ValueError("decrypted GZIP stream has trailing data")


def _validate_json(json_path: Path) -> None:
    try:
        with json_path.open("r", encoding="utf-8") as stream:
            root = json.load(stream)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"decrypted content is not valid UTF-8 JSON: {error}") from error

    if not isinstance(root, dict) or next(iter(root), None) != "mainInfo":
        raise ValueError("decrypted JSON must be an object with mainInfo first")


def decrypt_backup(
    input_path: Path,
    output_path: Path,
    *,
    force: bool = False,
) -> None:
    """Decrypt and decompress *input_path* atomically as plain JSON."""
    if not input_path.is_file():
        raise FileNotFoundError(f"backup file not found: {input_path}")
    if input_path.resolve() == output_path.resolve():
        raise ValueError("input and output paths must be different")
    if output_path.exists() and not force:
        raise FileExistsError(f"output already exists: {output_path} (use --force)")
    if not output_path.parent.is_dir():
        raise FileNotFoundError(f"output directory not found: {output_path.parent}")

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
                _decrypt_and_decompress(source, temporary_file)

        _validate_json(temporary_path)
        os.replace(temporary_path, output_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Decrypt a controller 6.2.14.11 .cfg backup to plain JSON."
    )
    parser.add_argument("input", type=Path, help="input controller backup (.cfg)")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="output path (default: replace .cfg with .json)",
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
        decrypt_backup(args.input, output_path, force=args.force)
    except (OSError, ValueError) as error:
        parser.exit(1, f"error: {error}\n")

    print(f"Decrypted and decompressed {args.input} -> {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())