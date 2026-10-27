import csv
import json
import subprocess
import sys
from io import StringIO
from pathlib import Path

import pytest

from csv_to_json import ConversionError as CsvError
from csv_to_json import convert as csv_to_json
from csv_to_json import read_rows
from json_to_csv import ConversionError as JsonError
from json_to_csv import convert as json_to_csv


def test_csv_auto_detects_semicolon_and_preserves_unicode(tmp_path: Path) -> None:
    source = tmp_path / "people.csv"
    target = tmp_path / "people.json"
    source.write_text(
        'name;note\nJérôme;"bonjour; monde"\nZoë;"line 1\nline 2"\n', encoding="utf-8"
    )
    csv_to_json(source, target)
    assert json.loads(target.read_text(encoding="utf-8")) == [
        {"name": "Jérôme", "note": "bonjour; monde"},
        {"name": "Zoë", "note": "line 1\nline 2"},
    ]


def test_csv_supports_json_lines_and_missing_cells(tmp_path: Path) -> None:
    source = tmp_path / "data.csv"
    target = tmp_path / "data.jsonl"
    source.write_text("a,b\n1,\n2,3\n", encoding="utf-8")
    csv_to_json(source, target, delimiter="comma", json_lines=True)
    assert [json.loads(line) for line in target.read_text().splitlines()] == [
        {"a": "1", "b": ""},
        {"a": "2", "b": "3"},
    ]


def test_csv_rejects_extra_values() -> None:
    with pytest.raises(CsvError, match="more values"):
        read_rows(StringIO("a,b\n1,2,3\n"), ",")


def test_csv_explicit_tab_and_utf8_bom(tmp_path: Path) -> None:
    source = tmp_path / "data.tsv"
    target = tmp_path / "data.json"
    source.write_text("\ufeffname\tvalue\nα\tβ\n", encoding="utf-8")
    csv_to_json(source, target, delimiter="tab")
    assert json.loads(target.read_text(encoding="utf-8")) == [
        {"name": "α", "value": "β"}
    ]


def test_csv_auto_detect_accepts_single_column(tmp_path: Path) -> None:
    source = tmp_path / "single.csv"
    target = tmp_path / "single.json"
    source.write_text("name\nAlice\nBob\n", encoding="utf-8")
    csv_to_json(source, target)
    assert json.loads(target.read_text(encoding="utf-8")) == [
        {"name": "Alice"},
        {"name": "Bob"},
    ]


def test_csv_detection_handles_a_large_quoted_field(tmp_path: Path) -> None:
    source = tmp_path / "large.csv"
    target = tmp_path / "large.json"
    note = "x" * 10_000
    source.write_text(f'name;note\nAlice;"{note}"\n', encoding="utf-8")
    csv_to_json(source, target)
    assert json.loads(target.read_text(encoding="utf-8")) == [
        {"name": "Alice", "note": note}
    ]


def test_csv_rejects_duplicate_headers_and_invalid_delimiter() -> None:
    with pytest.raises(CsvError, match="Duplicate"):
        read_rows(StringIO("a,a\n1,2\n"), ",")
    with pytest.raises(CsvError, match="Delimiter"):
        read_rows(StringIO("a,b\n1,2\n"), "too-long")


def test_csv_rejects_unclosed_quote() -> None:
    with pytest.raises(CsvError, match="Malformed"):
        read_rows(StringIO('a,b\n1,"unterminated\n'), ",")


def test_csv_rejects_negative_indent_before_writing(tmp_path: Path) -> None:
    source = tmp_path / "data.csv"
    target = tmp_path / "data.json"
    source.write_text("a\n1\n", encoding="utf-8")
    with pytest.raises(CsvError, match="Indent"):
        csv_to_json(source, target, indent=-1)
    assert not target.exists()


def test_json_uses_stable_union_of_keys_and_escapes_csv(tmp_path: Path) -> None:
    source = tmp_path / "data.json"
    target = tmp_path / "data.csv"
    source.write_text(
        json.dumps(
            [
                {"name": "A, Inc.", "active": False, "count": 0},
                {"note": 'He said "hi"', "name": "B\nCorp", "active": True},
            ]
        ),
        encoding="utf-8",
    )
    json_to_csv(source, target)
    with target.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert list(rows[0]) == ["name", "active", "count", "note"]
    assert rows == [
        {"name": "A, Inc.", "active": "false", "count": "0", "note": ""},
        {"name": "B\nCorp", "active": "true", "count": "", "note": 'He said "hi"'},
    ]


def test_json_empty_array_produces_empty_file(tmp_path: Path) -> None:
    source = tmp_path / "empty.json"
    target = tmp_path / "empty.csv"
    source.write_text("[]", encoding="utf-8")
    json_to_csv(source, target)
    assert target.read_text(encoding="utf-8") == ""


def test_json_rejects_nested_values(tmp_path: Path) -> None:
    source = tmp_path / "nested.json"
    target = tmp_path / "nested.csv"
    source.write_text('[{"a": [1, 2]}]', encoding="utf-8")
    with pytest.raises(JsonError, match="nested"):
        json_to_csv(source, target)


@pytest.mark.parametrize(
    "payload, message",
    [
        ("not json", "Invalid JSON"),
        ('{"a": 1}', "root must be an array"),
        ("[1, 2]", "Every array item"),
    ],
)
def test_json_rejects_invalid_shapes(
    tmp_path: Path, payload: str, message: str
) -> None:
    source = tmp_path / "bad.json"
    target = tmp_path / "bad.csv"
    source.write_text(payload, encoding="utf-8")
    with pytest.raises(JsonError, match=message):
        json_to_csv(source, target)


def test_json_rejects_invalid_delimiter_before_writing(tmp_path: Path) -> None:
    source = tmp_path / "data.json"
    target = tmp_path / "data.csv"
    source.write_text('[{"a": 1}]', encoding="utf-8")
    with pytest.raises(JsonError, match="Delimiter"):
        json_to_csv(source, target, delimiter="||")
    assert not target.exists()


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_json_rejects_nonstandard_numeric_constants(
    tmp_path: Path, constant: str
) -> None:
    source = tmp_path / "nonstandard.json"
    target = tmp_path / "data.csv"
    source.write_text(f'[{{"value": {constant}}}]', encoding="utf-8")
    with pytest.raises(JsonError, match="non-standard JSON constant"):
        json_to_csv(source, target)
    assert not target.exists()


def test_cli_round_trip_and_error_exit(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    intermediate = tmp_path / "data.json"
    target = tmp_path / "roundtrip.csv"
    source.write_text('name,note\nJérôme,"hello, world"\n', encoding="utf-8")

    csv_result = subprocess.run(
        [sys.executable, "csv_to_json.py", str(source), str(intermediate)],
        cwd=Path(__file__).parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert csv_result.returncode == 0, csv_result.stderr

    json_result = subprocess.run(
        [sys.executable, "json_to_csv.py", str(intermediate), str(target)],
        cwd=Path(__file__).parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert json_result.returncode == 0, json_result.stderr
    with target.open(newline="", encoding="utf-8") as stream:
        assert list(csv.DictReader(stream)) == [
            {"name": "Jérôme", "note": "hello, world"}
        ]

    missing_result = subprocess.run(
        [
            sys.executable,
            "csv_to_json.py",
            str(tmp_path / "missing.csv"),
            str(intermediate),
        ],
        cwd=Path(__file__).parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing_result.returncode == 2
    assert missing_result.stderr.startswith("error:")
