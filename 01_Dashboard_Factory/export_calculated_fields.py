"""
Export calculated fields from one or more Tableau .twbx workbooks to Excel.

Usage:
    python3 export_calculated_fields.py workbook.twbx [workbook2.twbx ...] [-o output.xlsx]
    python3 export_calculated_fields.py uploads/                           [-o output.xlsx]
"""
import os
import re
import sys
import zipfile
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Dict

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter


# ── Styling constants ────────────────────────────────────────────────────────

HEADER_FILL  = PatternFill("solid", fgColor="1F4E79")
ALT_ROW_FILL = PatternFill("solid", fgColor="DCE6F1")
WHITE_FILL   = PatternFill("solid", fgColor="FFFFFF")
HEADER_FONT  = Font(bold=True, color="FFFFFF", size=11)
BODY_FONT    = Font(size=10)
WRAP_ALIGN   = Alignment(wrap_text=True, vertical="top")
TOP_ALIGN    = Alignment(vertical="top")
THIN         = Side(style="thin", color="B0B0B0")
THIN_BORDER  = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

COLUMNS = [
    ("Workbook",     28),
    ("Datasource",   28),
    ("Field Name",   30),
    ("Formula",      60),
    ("Data Type",    12),
    ("Role",         12),
    ("Hidden",       10),
]


# ── Calculated-field parsing ─────────────────────────────────────────────────

def _resolve_formula(formula: str, name_map: Dict[str, str]) -> str:
    """Replace internal [Calculation_XXX] IDs in formula with human-readable captions."""
    def replacer(m):
        token = m.group(0)
        return f"[{name_map[token]}]" if token in name_map else token
    return re.sub(r'\[[^\]]+\]', replacer, formula)


def _extract_calc_fields(twbx_path: str) -> List[Dict]:
    """
    Parse a .twbx and return all calculated fields across all datasources.

    A calculated field is a <column> element whose direct <calculation> child
    has class="tableau". Parameters datasource is excluded.
    """
    fields = []
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(twbx_path, "r") as z:
            twb_files = [f for f in z.namelist() if f.endswith(".twb")]
            if not twb_files:
                return fields
            z.extract(twb_files[0], tmp)
            twb_path = os.path.join(tmp, twb_files[0])

        with open(twb_path, encoding="utf-8", errors="replace") as f:
            content = f.read()

    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return fields

    ds_container = root.find("datasources")
    if ds_container is None:
        return fields

    for ds in ds_container.findall("datasource"):
        ds_name    = ds.get("name", "")
        ds_caption = ds.get("caption", ds_name)

        if ds_name == "Parameters" or not ds_name:
            continue

        # Build internal-name → caption map for all columns in this datasource
        name_map: Dict[str, str] = {}
        for col in ds.findall("column"):
            col_name = col.get("name", "")
            caption  = col.get("caption", "")
            if col_name and caption:
                name_map[col_name] = caption

        for col in ds.findall("column"):
            calc = col.find("calculation")
            if calc is None or calc.get("class") != "tableau":
                continue

            name    = col.get("name", "")
            caption = col.get("caption", name.strip("[]"))
            formula = _resolve_formula(calc.get("formula", ""), name_map)
            fields.append({
                "datasource": ds_caption or ds_name,
                "caption":    caption,
                "formula":    formula,
                "datatype":   col.get("datatype", ""),
                "role":       col.get("role", ""),
                "hidden":     col.get("hidden", "false").lower() == "true",
            })

    return fields


# ── Excel helpers ────────────────────────────────────────────────────────────

def _write_header(ws) -> None:
    for col_idx, (header, width) in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font      = HEADER_FONT
        cell.fill      = HEADER_FILL
        cell.alignment = TOP_ALIGN
        cell.border    = THIN_BORDER
        ws.column_dimensions[get_column_letter(col_idx)].width = width
    ws.row_dimensions[1].height = 20
    ws.freeze_panes = "A2"


def _write_row(ws, row_num: int, values: list, alt: bool) -> None:
    fill = ALT_ROW_FILL if alt else WHITE_FILL
    for col_idx, val in enumerate(values, start=1):
        cell           = ws.cell(row=row_num, column=col_idx, value=val)
        cell.font      = BODY_FONT
        cell.fill      = fill
        cell.border    = THIN_BORDER
        cell.alignment = WRAP_ALIGN if col_idx == 4 else TOP_ALIGN


# ── Main export ──────────────────────────────────────────────────────────────

def export(twbx_paths: List[Path], output_path: str) -> int:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Calculated Fields"
    _write_header(ws)

    total   = 0
    row_num = 2

    for twbx_path in twbx_paths:
        workbook_name = twbx_path.stem
        try:
            fields = _extract_calc_fields(str(twbx_path))
        except Exception as exc:
            print(f"[ERROR] {twbx_path.name}: {exc}", file=sys.stderr)
            continue

        for field in fields:
            _write_row(ws, row_num, [
                workbook_name,
                field["datasource"],
                field["caption"],
                field["formula"],
                field["datatype"],
                field["role"],
                "Yes" if field["hidden"] else "No",
            ], alt=(row_num % 2 == 0))
            row_num += 1
            total   += 1

    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}1"
    wb.save(output_path)
    return total


def _resolve_paths(inputs: list) -> List[Path]:
    paths = []
    for inp in inputs:
        p = Path(inp)
        if p.is_dir():
            paths.extend(sorted(p.glob("**/*.twbx")))
        elif p.suffix.lower() == ".twbx" and p.exists():
            paths.append(p)
        else:
            print(f"[WARN] Skipping '{inp}' — not a .twbx file or directory", file=sys.stderr)
    return paths


DESKTOP = os.path.join(os.path.expanduser("~"), "Desktop")


def main():
    file_path = input("Enter the path to the .twbx file (or folder): ").strip().strip("'\"")

    paths = _resolve_paths([file_path])
    if not paths:
        print("No .twbx files found at the given path.", file=sys.stderr)
        sys.exit(1)

    print(f"Processing {len(paths)} workbook(s)...")
    grand_total = 0
    for p in paths:
        out = os.path.join(DESKTOP, f"{p.stem}.xlsx")
        total = export([p], out)
        grand_total += total
        print(f"  {p.name} → {out} ({total} field(s))")
    print(f"Done — {grand_total} calculated field(s) exported.")


if __name__ == "__main__":
    main()
