# CSV / JSON converters

Two dependency-free Python 3.10+ command-line tools:

- `csv_to_json.py`: delimited text to a JSON array or JSON Lines.
- `json_to_csv.py`: a JSON array of flat objects to CSV.
- `test_converters.py`: automated regression tests for both tools.

No installation is required. Run the scripts with Python 3.10 or newer.

## CSV to JSON: quick start

```bash
python3 csv_to_json.py input.csv output.json
python3 csv_to_json.py input.tsv output.json --delimiter tab --indent 4
python3 csv_to_json.py input.csv output.jsonl --json-lines
```

Without `--delimiter`, the script detects comma, semicolon, tab, or pipe. A
single-column CSV is also valid. `--delimiter` accepts one literal character or
one of `comma`, `semicolon`, `tab`, and `pipe`.

The first row is the header. Every later row becomes an object. Empty cells are
empty strings. The parser supports UTF-8 BOM input, Unicode, quoted delimiters,
escaped quotes, and embedded newlines. It rejects empty or duplicate headings,
extra cells, malformed quoting, and invalid delimiters instead of silently
losing data.

Options:

| Option | Meaning |
|---|---|
| `--delimiter VALUE` | Explicit input delimiter; default is detection |
| `--indent N` | JSON indentation; default `2`, must be non-negative |
| `--json-lines` | Write one compact JSON object per line |

Example input:

```csv
name;note
Jérôme;"bonjour; monde"
```

Example output:

```json
[
  {
    "name": "Jérôme",
    "note": "bonjour; monde"
  }
]
```

## JSON to CSV: quick start

```bash
python3 json_to_csv.py input.json output.csv
python3 json_to_csv.py input.json output.tsv --delimiter $'\t'
```

The JSON root must be an array of flat objects. Output columns are the union of
all keys in first-seen order. A missing key or `null` becomes an empty cell;
zero and booleans remain distinguishable as `0`, `true`, and `false`. Standard
CSV quoting protects commas, quotes, and newlines.

Nested arrays and objects are rejected because they have no unambiguous flat
CSV representation. Non-standard JSON constants such as `NaN` and `Infinity`
are also rejected. An empty array produces an empty output file.

## Errors and exit codes

- Exit `0`: conversion completed.
- Exit `2`: invalid input, inaccessible file, or write failure.

Errors are written to standard error with an `error:` prefix. Input is fully
parsed and validated before the output file is opened, so validation failures
do not create a partial result.

## Tests and quality checks

Install `pytest` only for development, then run:

```bash
python3 -m pytest -q
python3 -m py_compile csv_to_json.py json_to_csv.py
```

The 20-test suite covers all supported delimiters, one-column and large-field
inputs, Unicode and BOMs, quoted special characters and newlines, missing cells
and keys, stable columns, JSON Lines, malformed CSV, invalid JSON shapes,
non-standard numbers, CLI round trips, and error exits.

## Specification coverage

| OpenTask requirement | Implementation |
|---|---|
| Read CSV and output JSON | `csv_to_json.py` default mode |
| Different CSV formats | Detection plus explicit comma/semicolon/tab/pipe/custom delimiter |
| Escape special characters | Python's strict CSV parser and `json` serializer |
| Reusable Python script | Importable `convert()` and `read_rows()` plus CLI |
| Custom JSON formatting | `--indent` and `--json-lines` |
| Invalid CSV errors | `ConversionError`, clear stderr message, exit `2` |
| Python 3.10+ JSON-array-to-CSV | `json_to_csv.py`, no third-party runtime package |
| Missing keys become empty | Stable union of keys and empty-string fallback |
| README and pytest | This file and `test_converters.py` |

## Deliberate limits

The JSON-to-CSV tool handles flat objects only. Both converters currently keep
the parsed dataset in memory, which favors correctness and simple validation
over streaming very large files. Inputs and outputs are UTF-8.
