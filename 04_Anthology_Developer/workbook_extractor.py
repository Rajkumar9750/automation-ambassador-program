"""
Extract tables + actual DB column names from a Tableau workbook (.twbx/.twb).
Uses <remote-name> elements to get the real database column names.
"""

import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Dict


def _read_twb(path: str) -> str:
    p = Path(path)
    if p.suffix.lower() == ".twbx":
        with zipfile.ZipFile(path) as z:
            twb_name = next(f for f in z.namelist() if f.endswith(".twb"))
            return z.read(twb_name).decode("utf-8", errors="replace")
    return p.read_text(encoding="utf-8", errors="replace")


def _strip(s: str) -> str:
    return s.strip("[]") if s else ""


def extract_tables(path: str) -> List[Dict]:
    """
    Returns:
    [{schema, table, columns: [{name, data_type}], is_custom_sql, custom_sql}]
    Deduplicates by (schema, table).
    """
    content = _read_twb(path)
    root    = ET.fromstring(content)

    seen   = set()
    tables = []

    for ds in root.iter("datasource"):
        if ds.get("name") == "Parameters":
            continue

        # ── Collect actual DB column names from metadata-records ──────────
        # Each record: <remote-name>db_col</remote-name>
        #              <parent-name>[TableName]</parent-name>
        #              <local-type>string/integer/…</local-type>
        table_cols: Dict[str, list] = {}   # table_name → [{name, data_type}]
        for mc in ds.iter("metadata-record"):
            if mc.get("class") != "column":
                continue
            remote = mc.find("remote-name")
            parent = mc.find("parent-name")
            dtype  = mc.find("local-type")
            if remote is None or not remote.text:
                continue
            col_name   = remote.text.strip()
            table_name = _strip(parent.text) if parent is not None and parent.text else ""
            col_type   = dtype.text.strip() if dtype is not None and dtype.text else "string"
            if table_name:
                table_cols.setdefault(table_name, []).append(
                    {"name": col_name, "data_type": col_type}
                )

        # ── Extract table relations ──────────────────────────────────────
        for relation in ds.iter("relation"):
            rtype = relation.get("type", "")

            if rtype == "table":
                schema = _strip(relation.get("schema", "") or "")
                table  = _strip(relation.get("table",  "") or "")
                if not table:
                    continue
                key = (schema, table)
                if key in seen:
                    continue
                seen.add(key)
                tables.append({
                    "schema":        schema,
                    "table":         table,
                    "columns":       table_cols.get(table, []),
                    "is_custom_sql": False,
                    "custom_sql":    None,
                })

            elif rtype == "text":
                sql  = (relation.text or "").strip()
                name = _strip(relation.get("name", f"custom_sql_{len(tables)}"))
                key  = ("", name)
                if key in seen:
                    continue
                seen.add(key)
                tables.append({
                    "schema":        "",
                    "table":         name,
                    "columns":       table_cols.get(name, []),
                    "is_custom_sql": True,
                    "custom_sql":    sql,
                })

    return tables
