"""Delimited-text parser for potentiostat exports (CSV, TSV, semicolon, whitespace-aligned TXT).

Finds the longest block of consistently-delimited numeric rows, the header (and an optional units
row, as in Gamry exports) directly above it, and key/value metadata before that. Column roles and
units are only *suggested*; the import wizard requires the user to confirm them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

from app.services.electrochemistry.units import FACTORS, ROLE_QUANTITY, factor, normalize_unit

MAX_ROWS = 500_000
DELIMS = {"\t": "tab", ",": "comma", ";": "semicolon", " ": "whitespace"}
_NUM = re.compile(r"^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$")
_NUM_COMMA = re.compile(r"^[-+]?\d+,\d+([eE][-+]?\d+)?$")


class ParseError(ValueError):
    pass


@dataclass
class ParsedTable:
    columns: list[str]
    units_row: list[str] | None
    data: np.ndarray  # float, NaN for missing
    delimiter: str
    encoding: str
    decimal_comma: bool
    metadata: dict[str, str]
    header_line: int | None
    data_start_line: int
    warnings: list[str] = field(default_factory=list)

    def preview_rows(self, n: int = 15) -> list[list[float | None]]:
        return [[None if np.isnan(x) else float(x) for x in row] for row in self.data[:n]]


def decode_bytes(data: bytes) -> tuple[str, str]:
    if not data:
        raise ParseError("File is empty.")
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace"), "utf-8-sig"
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16"), "utf-16"
    if data.count(b"\x00") > len(data) // 4:
        try:
            return data.decode("utf-16-le"), "utf-16-le"
        except UnicodeDecodeError:
            raise ParseError("File appears to be binary, not a text export.") from None
    try:
        text, enc = data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        text, enc = data.decode("cp1252", errors="replace"), "cp1252"
    ctrl = sum(1 for ch in text[:20000] if ord(ch) < 32 and ch not in "\r\n\t")
    if ctrl > 0.01 * min(len(text), 20000):
        raise ParseError("File appears to be binary, not a text export.")
    return text, enc


def _split(line: str, delim: str) -> list[str]:
    if delim == " ":
        return line.split()
    return [t.strip().strip('"') for t in line.rstrip("\r\n").split(delim)]


def _is_num(tok: str, decimal_comma: bool) -> bool:
    return bool(_NUM.match(tok) or (decimal_comma and _NUM_COMMA.match(tok)))


def _to_float(tok: str, decimal_comma: bool) -> float:
    if decimal_comma and "," in tok and "." not in tok:
        tok = tok.replace(",", ".")
    try:
        return float(tok)
    except ValueError:
        return np.nan


def _numeric_line(tokens: list[str], decimal_comma: bool) -> bool:
    nonempty = [t for t in tokens if t]
    if len(tokens) < 2 or not nonempty:
        return False
    return sum(_is_num(t, decimal_comma) for t in nonempty) >= 0.6 * len(nonempty)


def _best_block(lines: list[str]) -> tuple[str, bool, int, int, int]:
    """Return (delimiter, decimal_comma, start, end, n_fields) of the longest consistent numeric block."""
    best = ("", False, 0, 0, 0)
    for delim in DELIMS:
        for dec_comma in ((False, True) if delim != "," else (False,)):
            run_start, run_fields = None, 0
            for i in range(len(lines) + 1):
                tokens = _split(lines[i], delim) if i < len(lines) else None
                ok = tokens is not None and _numeric_line(tokens, dec_comma)
                if ok and run_start is not None and len(tokens) == run_fields:
                    continue
                if run_start is not None and i - run_start > best[3] - best[2]:
                    best = (delim, dec_comma, run_start, i, run_fields)
                run_start, run_fields = (i, len(tokens)) if ok else (None, 0)
    return best


def parse_table(data: bytes) -> ParsedTable:
    text, encoding = decode_bytes(data)
    lines = text.splitlines()
    if not lines:
        raise ParseError("File contains no lines.")
    delim, dec_comma, start, end, n_fields = _best_block(lines)
    if end - start < 3:
        raise ParseError("No block of at least 3 numeric rows with a consistent delimiter was found.")
    warnings: list[str] = []
    if dec_comma:
        warnings.append("Decimal commas detected and converted to decimal points.")

    header_line = units_row = None
    columns = [f"Column {k + 1}" for k in range(n_fields)]
    def text_row(k: int) -> bool:
        return (k >= 0 and not lines[k].startswith("#") and len(_split(lines[k], delim)) == n_fields
                and not _numeric_line(_split(lines[k], delim), dec_comma))

    def looks_like_units(tokens: list[str]) -> bool:
        toks = [t for t in tokens if t and t != "#"]
        return bool(toks) and sum(normalize_unit(t) is not None for t in toks) >= 0.5 * len(toks)

    if text_row(start - 1) and text_row(start - 2) and looks_like_units(_split(lines[start - 1], delim)):
        header_line, units_row = start - 2, _split(lines[start - 1], delim)
    elif text_row(start - 1):
        header_line = start - 1
    if header_line is not None:
        columns = [t or f"Column {k + 1}" for k, t in enumerate(_split(lines[header_line], delim))]
    else:
        warnings.append("No header row found; columns are numbered. Map them manually.")
    seen: dict[str, int] = {}
    for k, c in enumerate(columns):  # make names unique
        if c in seen:
            seen[c] += 1
            columns[k] = f"{c} ({seen[c]})"
        else:
            seen[c] = 0

    rows = [_split(l, delim) for l in lines[start:end][:MAX_ROWS]]
    if end - start > MAX_ROWS:
        warnings.append(f"Only the first {MAX_ROWS} rows were read.")
    arr = np.array([[_to_float(t, dec_comma) for t in r] for r in rows], dtype=float)
    blank = np.all(np.isnan(arr), axis=0) & np.array([c.startswith("Column ") for c in columns])
    if blank.any():  # delimiter artefacts such as Gamry's leading tab: no header and no values
        keep = ~blank
        arr = arr[:, keep]
        columns = [c for c, k in zip(columns, keep) if k]
        units_row = [u for u, k in zip(units_row, keep) if k] if units_row and len(units_row) == len(keep) else units_row
    empty_cols = np.all(np.isnan(arr), axis=0)
    if empty_cols.any():
        warnings.append(f"{int(empty_cols.sum())} column(s) contain no numeric values.")
    missing = int(np.isnan(arr[:, ~empty_cols]).sum())
    if missing:
        warnings.append(f"{missing} missing or non-numeric value(s) inside the data block.")
    dup = len(arr) - len(np.unique(arr, axis=0))
    if dup:
        warnings.append(f"{dup} duplicated row(s) in the data block.")
    trailing = sum(1 for l in lines[end:] if _numeric_line(_split(l, delim), dec_comma))
    if trailing:
        warnings.append(f"{trailing} further numeric row(s) after line {end} were not imported (multiple data blocks?).")

    metadata: dict[str, str] = {}
    for line in lines[: header_line if header_line is not None else start][:400]:
        m = re.match(r"^\s*#?\s*([^:=\t]{1,60}?)\s*(?::|=|\t)\s*(.+?)\s*$", line)
        if m and len(metadata) < 200:
            metadata.setdefault(m.group(1).strip(), m.group(2).strip()[:300])
    return ParsedTable(columns, units_row, arr, DELIMS[delim], encoding, dec_comma, metadata, header_line, start, warnings)


# ---------------- column-role suggestions ----------------

ROLE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("frequency", re.compile(r"(?i)\bfreq|^f\s*[/(]|^f$")),
    ("z_imag", re.compile(r"(?i)z''|z\"|z_?im|im\s*\(?\s*z|zimag|imag|z2")),
    ("z_real", re.compile(r"(?i)z'|z_?re\b|zre|re\s*\(?\s*z|zreal|real|z1")),
    ("z_mod", re.compile(r"(?i)\|z\||zmod|mod\s*\(?z|magnitude|^\s*z\s*[/(]")),
    ("phase", re.compile(r"(?i)phase|zphz|phz|\bphi\b")),
    ("time", re.compile(r"(?i)^\s*t\s*$|time|elapsed|^t\s*[/(]")),
    ("current_density", re.compile(r"(?i)density|\bj\s*[/(]|^j$|/cm|cm-2|cm2|cm²|/m2")),
    ("potential", re.compile(r"(?i)ewe|\bvf\b|potential|voltage|^e\s*[/(]|^e$|^v$|^e\s*\(|\be\s*vs|^we.*potential")),
    ("current", re.compile(r"(?i)current|\bim\b|<i>|^i\s*[/(]|^i$|^i\s*\(")),
]


def _unit_from_header(name: str) -> str | None:
    m = re.search(r"[(\[]([^)\]]+)[)\]]\s*$", name) or re.search(r"/\s*([^/]+(?:/[^/]+)?)\s*$", name)
    return normalize_unit(m.group(1)) if m else None


def suggest_mapping(columns: list[str], units_row: list[str] | None, data: np.ndarray | None = None) -> dict:
    mapping: dict[str, str] = {}
    units: dict[str, str | None] = {}
    for idx, name in enumerate(columns):
        for role, pat in ROLE_PATTERNS:
            if role in mapping:
                continue
            if pat.search(name):
                unit = (_unit_from_header(name) or (normalize_unit(units_row[idx]) if units_row and idx < len(units_row) else None))
                if unit and unit not in FACTORS[ROLE_QUANTITY[role]]:
                    unit = None
                mapping[role], units[role] = name, unit
                break
    imag = mapping.get("z_imag", "")
    convention = "negated" if re.match(r"^\s*-", imag) or "-z''" in imag.lower() or "-im" in imag.lower() else "as_is"
    if "z_real" in mapping and "z_imag" not in mapping:
        convention = "as_is"
    if "current_density" in mapping and "current" in mapping and mapping["current_density"] == mapping["current"]:
        mapping.pop("current")
    method = None
    if "frequency" in mapping and "z_real" in mapping:
        method = "eis"
    elif "potential" in mapping and not ({"current", "current_density"} & mapping.keys()):
        method = "ocp" if "time" in mapping else None
    elif "potential" in mapping and data is not None and units.get("potential"):
        e = data[:, columns.index(mapping["potential"])] * factor("potential", units["potential"])
        span = float(np.nanmax(e) - np.nanmin(e)) if np.isfinite(e).any() else 0.0
        method = "lpr" if span <= 0.06 else "pdp"  # suggestion only: LPR sweeps are typically within +/-30 mV
    return {"mapping": mapping, "units": units, "imag_convention": convention, "suggested_method": method}
