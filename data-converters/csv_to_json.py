#!/usr/bin/env python3
"""Convert delimited text files to JSON arrays or JSON Lines."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, TextIO

DELIMITERS = {
    "comma": ",",
    "semicolon": ";",
    "tab": "\t",
    "pipe": "|",
}


class ConversionError(ValueError):
    """Raised when input cannot be converted safely."""


def _delimiter(value: str) -> str:
    resolved = DELIMITERS.get(value, value)
    if len(resolved) != 1 or resolved in {"\r", "\n", '"'}:
        raise ConversionError(
            "Delimiter must be one character and cannot be a newline or quote"
        )
    return resolved


def read_rows(stream: TextIO, delimiter: str | None = None) -> list[dict[str, str]]:
    # The converter already materializes all rows before writing. Reading the
    # complete input here also prevents Sniffer from seeing a sample truncated
    # in the middle of a large quoted field.
    sample = stream.read()
    stream.seek(0)
    if not sample.strip():
        return []

    if delimiter is None:
        # A header without a candidate delimiter is a valid one-column CSV.
        # Sniffer raises for that case, so use the standard comma dialect.
        dialect: Any
        header_line = sample.splitlines()[0]
        if not any(candidate in header_line for candidate in ",;\t|"):
            dialect = csv.get_dialect("excel")
        else:
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            except csv.Error as exc:
                raise ConversionError(
                    "Could not detect the delimiter; pass --delimiter explicitly"
                ) from exc
        reader = csv.DictReader(stream, dialect=dialect, strict=True)
    else:
        # Pass formatting directly instead of mutating csv.excel's shared class.
        reader = csv.DictReader(
            stream, dialect="excel", delimiter=_delimiter(delimiter), strict=True
        )

    try:
        if not reader.fieldnames or any(
            name is None or not name.strip() for name in reader.fieldnames
        ):
            raise ConversionError("The input must have a non-empty header row")
        if len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ConversionError("Duplicate column names are not supported")

        rows: list[dict[str, str]] = []
        for line_number, row in enumerate(reader, start=2):
            if None in row:
                raise ConversionError(
                    f"Row {line_number} has more values than the header"
                )
            rows.append(
                {key: value if value is not None else "" for key, value in row.items()}
            )
        return rows
    except csv.Error as exc:
        raise ConversionError(f"Malformed delimited input: {exc}") from exc


def convert(
    input_path: Path,
    output_path: Path,
    *,
    delimiter: str | None = None,
    json_lines: bool = False,
    indent: int | None = 2,
) -> None:
    if indent is not None and indent < 0:
        raise ConversionError("Indent must be zero or greater")
    with input_path.open("r", encoding="utf-8-sig", newline="") as source:
        rows = read_rows(source, delimiter)

    with output_path.open("w", encoding="utf-8", newline="\n") as target:
        if json_lines:
            for row in rows:
                target.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
                target.write("\n")
        else:
            json.dump(rows, target, ensure_ascii=False, indent=indent)
            target.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Input CSV/TSV file")
    parser.add_argument("output", type=Path, help="Output JSON file")
    parser.add_argument(
        "--delimiter",
        help="Delimiter character or one of: comma, semicolon, tab, pipe (default: auto-detect)",
    )
    parser.add_argument(
        "--json-lines", action="store_true", help="Write one JSON object per line"
    )
    parser.add_argument(
        "--indent", type=int, default=2, help="JSON indentation (default: 2)"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        convert(
            args.input,
            args.output,
            delimiter=args.delimiter,
            json_lines=args.json_lines,
            indent=args.indent,
        )
    except (ConversionError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
