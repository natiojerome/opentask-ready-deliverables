#!/usr/bin/env python3
"""Convert a JSON array of flat objects to CSV."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, NoReturn


class ConversionError(ValueError):
    """Raised when input cannot be represented as a flat CSV table."""


def validate_delimiter(delimiter: str) -> str:
    if len(delimiter) != 1 or delimiter in {"\r", "\n", '"'}:
        raise ConversionError(
            "Delimiter must be one character and cannot be a newline or quote"
        )
    return delimiter


def load_records(path: Path) -> list[dict[str, Any]]:
    def reject_nonstandard_constant(value: str) -> NoReturn:
        raise ConversionError(f"Invalid non-standard JSON constant: {value}")

    try:
        with path.open("r", encoding="utf-8-sig") as source:
            value = json.load(source, parse_constant=reject_nonstandard_constant)
    except json.JSONDecodeError as exc:
        raise ConversionError(
            f"Invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc

    if not isinstance(value, list):
        raise ConversionError("The JSON root must be an array")
    if any(not isinstance(item, dict) for item in value):
        raise ConversionError("Every array item must be an object")
    for index, item in enumerate(value):
        for key, cell in item.items():
            if not isinstance(key, str):
                raise ConversionError(f"Object {index} contains a non-string key")
            if isinstance(cell, (dict, list)):
                raise ConversionError(
                    f"Object {index}, key {key!r} is nested; only flat objects are supported"
                )
    return value


def ordered_fields(records: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    fields: list[str] = []
    for record in records:
        for key in record:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    return fields


def render_cell(value: Any) -> str:
    if value is None:
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def convert(input_path: Path, output_path: Path, *, delimiter: str = ",") -> None:
    delimiter = validate_delimiter(delimiter)
    records = load_records(input_path)
    fields = ordered_fields(records)
    with output_path.open("w", encoding="utf-8", newline="") as target:
        if not fields:
            return
        writer = csv.DictWriter(
            target, fieldnames=fields, delimiter=delimiter, extrasaction="raise"
        )
        writer.writeheader()
        for record in records:
            writer.writerow({field: render_cell(record.get(field)) for field in fields})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Input JSON file")
    parser.add_argument("output", type=Path, help="Output CSV file")
    parser.add_argument(
        "--delimiter", default=",", help="Single-character output delimiter"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        convert(args.input, args.output, delimiter=args.delimiter)
    except (ConversionError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
