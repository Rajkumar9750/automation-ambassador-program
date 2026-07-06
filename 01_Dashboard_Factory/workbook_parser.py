"""
Parse Tableau .twbx workbooks to extract Postgres datasource and table info.

Handles all three Tableau relation patterns:
  1. type='collection'  — flat list of tables (classic joins)
  2. type='join'        — nested join tree (newer workbooks)
  3. type='table'       — direct single-table datasource
  4. type='text'        — custom SQL query (schema references replaced at generate time)
"""
import re
import zipfile
import os
import xml.etree.ElementTree as ET
import tempfile
from typing import List, Dict, Any


def parse_twbx(path: str) -> Dict[str, Any]:
    """
    Parse a .twbx file and return structured datasource info.

    Returns:
        {
            datasources: [{name, caption, postgres_connections: [...], tables: [...]}],
            excel_files: [relative paths inside the zip],
            has_extracts: bool,
            twb_filename: str,
        }
    """
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(path, "r") as z:
            z.extractall(tmp)
            all_files = z.namelist()

        twb_files = [f for f in all_files if f.endswith(".twb")]
        excel_files = [f for f in all_files if any(f.lower().endswith(ext) for ext in (".xlsx", ".xls", ".csv"))]
        has_extracts = any(f.endswith(".hyper") for f in all_files)

        if not twb_files:
            raise ValueError("No .twb file found inside the workbook")

        twb_path = os.path.join(tmp, twb_files[0])
        with open(twb_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

    datasources = _parse_datasources(content)
    return {
        "datasources": datasources,
        "excel_files": excel_files,
        "has_extracts": has_extracts,
        "twb_filename": twb_files[0],
    }


# SQL-compatible connector classes the tool can parse and replace.
# All of these use a similar named-connection structure with server/schema/table attributes.
_SQL_CONNECTION_CLASSES = {
    "postgres", "kyvos", "sqlserver", "mysql", "redshift",
    "snowflake", "databricks", "bigquery", "oracle", "teradata",
}


def _parse_datasources(content: str) -> List[Dict]:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        raise ValueError(f"Failed to parse workbook XML: {e}")

    datasources = []
    ds_container = root.find("datasources")
    if ds_container is None:
        return datasources

    for ds in ds_container.findall("datasource"):
        name = ds.get("name", "")
        caption = ds.get("caption", name)

        if name == "Parameters" or not name:
            continue

        # Find the live federated connection (first <connection class='federated'>)
        live_conn = None
        for child in ds:
            if child.tag == "connection" and child.get("class") == "federated":
                live_conn = child
                break

        if live_conn is None:
            continue

        # Collect SQL named-connections (postgres, kyvos, etc.)
        pg_conns: Dict[str, Dict] = {}
        nc_container = live_conn.find("named-connections")
        if nc_container is not None:
            for nc in nc_container.findall("named-connection"):
                nc_name = nc.get("name", "")
                inner = nc.find("connection")
                if inner is not None and inner.get("class") in _SQL_CONNECTION_CLASSES:
                    pg_conns[nc_name] = {
                        "named_connection_name": nc_name,
                        "caption": nc.get("caption", ""),
                        "server": inner.get("server", ""),
                        "dbname": inner.get("dbname", inner.get("schema", "")),
                        "port": inner.get("port", "5432"),
                        "username": inner.get("username", ""),
                        "sslmode": inner.get("sslmode", "require"),
                        "connection_class": inner.get("class", "postgres"),
                    }

        if not pg_conns:
            continue

        # Recursively collect all Postgres table / custom-SQL relations
        pg_tables: List[Dict] = []
        _collect_pg_relations(live_conn, pg_conns, pg_tables)

        # Deduplicate by (schema, table) so joins don't double-count shared tables
        seen = set()
        deduped = []
        for t in pg_tables:
            key = (t["schema"], t["table"], t.get("is_custom_sql", False))
            if key not in seen:
                seen.add(key)
                deduped.append(t)

        datasources.append({
            "name": name,
            "caption": caption,
            "postgres_connections": list(pg_conns.values()),
            "tables": deduped,
            "calculated_fields": _parse_calculated_fields(ds),
        })

    return datasources


def _parse_calculated_fields(ds_elem: ET.Element) -> List[Dict]:
    """Extract calculated field columns from a datasource element."""
    # Build internal-name → caption map for all columns so formula references resolve correctly
    name_map: Dict[str, str] = {}
    for col in ds_elem.findall("column"):
        col_name = col.get("name", "")
        caption  = col.get("caption", "")
        if col_name and caption:
            name_map[col_name] = caption

    fields = []
    for col in ds_elem.findall("column"):
        if col.get("type") != "calc":
            continue
        calc = col.find("calculation")
        if calc is None:
            continue
        name = col.get("name", "")
        caption = col.get("caption", name.strip("[]"))
        raw_formula = calc.get("formula", "")
        formula = re.sub(r'\[[^\]]+\]', lambda m: f"[{name_map[m.group(0)]}]" if m.group(0) in name_map else m.group(0), raw_formula)
        fields.append({
            "name": name,
            "caption": caption,
            "formula": formula,
            "datatype": col.get("datatype", ""),
            "role": col.get("role", ""),
            "hidden": col.get("hidden", "false").lower() == "true",
        })
    return fields


def parse_column_types_from_metadata(content: str) -> Dict[str, Dict[str, str]]:
    """
    Parse column types from metadata-records in the TWB XML.
    Returns {table_name: {remote_col_name: local_type}}
    table_name has brackets stripped (e.g. 'fm_fact_workorder_vw').
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return {}

    result: Dict[str, Dict[str, str]] = {}
    for record in root.iter("metadata-record"):
        if record.get("class") != "column":
            continue
        remote_name_el = record.find("remote-name")
        parent_name_el = record.find("parent-name")
        local_type_el  = record.find("local-type")
        if remote_name_el is None or parent_name_el is None or local_type_el is None:
            continue
        col_name   = (remote_name_el.text or "").strip()
        parent_raw = (parent_name_el.text or "").strip()
        local_type = (local_type_el.text or "").strip()
        if not col_name or not parent_raw or not local_type:
            continue
        # Strip surrounding brackets, e.g. '[fm_fact_workorder_vw]' → 'fm_fact_workorder_vw'
        table_name = parent_raw.strip("[]")
        if table_name not in result:
            result[table_name] = {}
        result[table_name][col_name] = local_type
    return result


def _collect_pg_relations(el: ET.Element, pg_conns: Dict, result: List) -> None:
    """
    Recursively walk XML child <relation> elements and collect all Postgres-connected
    table relations and custom-SQL relations.

    Handles:
      - type='table'      → direct table reference    [schema].[table]
      - type='text'       → custom SQL (schema in SQL text replaced at generate time)
      - type='collection' → flat wrapper; recurse into children
      - type='join'       → nested join tree; recurse into children
      - (direct child)    → single table directly under <connection class='federated'>

    Also handles Tableau FCP-prefixed tags (e.g. _.fcp.ObjectModelEncapsulateLegacy.false...relation)
    which newer workbooks emit instead of plain <relation> elements.
    """
    for child in el:
        if child.tag != "relation" and not child.tag.endswith("...relation"):
            continue

        rel_type = child.get("type", "")
        conn_ref = child.get("connection", "")

        if rel_type == "table" and conn_ref in pg_conns:
            table_str = child.get("table", "")
            if table_str.startswith("[") and "].[" in table_str:
                inner = table_str[1:-1]
                parts = inner.split("].[")
                if len(parts) == 2:
                    result.append({
                        "relation_name":   child.get("name", ""),
                        "connection_ref":  conn_ref,
                        "schema":          parts[0],
                        "table":           parts[1],
                        "is_custom_sql":   False,
                        "custom_sql":      "",
                        "old_connection":  pg_conns[conn_ref],
                    })

        elif rel_type == "text" and conn_ref in pg_conns:
            # Custom SQL — store full query; preview is a separate truncated field for the UI card
            sql_text = (child.text or "").replace("&#13;", "\n").strip()
            result.append({
                "relation_name":    child.get("name", ""),
                "connection_ref":   conn_ref,
                "schema":           pg_conns[conn_ref].get("dbname", ""),
                "table":            child.get("name", "Custom SQL"),
                "is_custom_sql":    True,
                "custom_sql":       sql_text,                                           # full SQL
                "custom_sql_preview": sql_text[:120] + ("…" if len(sql_text) > 120 else ""),  # card display
                "old_connection":   pg_conns[conn_ref],
            })

        else:
            # collection, join, or other wrapper — recurse
            _collect_pg_relations(child, pg_conns, result)


def parse_join_tree(content: str) -> Dict[str, Any]:
    """
    Parse tables and join relationships from a workbook's TWB XML.
    Handles both classic Tableau join trees (relation type='join') and
    the newer object-graph relationship model.
    Returns {datasources: [{name, caption, tables, joins}]}
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return {"datasources": []}

    result = []
    ds_container = root.find("datasources")
    if ds_container is None:
        return {"datasources": []}

    for ds in ds_container.findall("datasource"):
        name = ds.get("name", "")
        caption = ds.get("caption", name)
        if name == "Parameters" or not name:
            continue

        live_conn = None
        for child in ds:
            if child.tag == "connection" and child.get("class") == "federated":
                live_conn = child
                break
        if live_conn is None:
            continue

        pg_conns: set = set()
        nc_container = live_conn.find("named-connections")
        if nc_container is not None:
            for nc in nc_container.findall("named-connection"):
                inner = nc.find("connection")
                if inner is not None and inner.get("class") in _SQL_CONNECTION_CLASSES:
                    pg_conns.add(nc.get("name", ""))

        if not pg_conns:
            continue

        tables: List[Dict] = []
        joins: List[Dict] = []
        seen_tables: set = set()
        seen_join_keys: set = set()

        # Classic join tree: process first relation element only (skip FCP duplicate)
        for child in live_conn:
            if _is_rel_tag(child.tag):
                _collect_classic_joins(child, pg_conns, tables, joins, seen_tables, seen_join_keys)
                break

        # Object-graph relationship model (newer Tableau workbooks)
        _collect_object_graph(ds, tables, joins, seen_tables, seen_join_keys, pg_conns)

        if tables:
            result.append({
                "name": name,
                "caption": caption,
                "tables": tables,
                "joins": joins,
            })

    return {"datasources": result}


def _is_rel_tag(tag: str) -> bool:
    return tag == "relation" or tag.endswith("...relation")


def _collect_classic_joins(
    el: ET.Element,
    pg_conns: set,
    tables: List[Dict],
    joins: List[Dict],
    seen_tables: set,
    seen_join_keys: set,
) -> List[str]:
    """Recursively collect tables and joins from a classic Tableau relation tree."""
    rel_type = el.get("type", "")
    added: List[str] = []

    if rel_type == "table":
        conn_ref = el.get("connection", "")
        if conn_ref not in pg_conns:
            return added
        table_str = el.get("table", "")
        name = el.get("name", "")
        if table_str.startswith("[") and "].[" in table_str and name not in seen_tables:
            inner = table_str[1:-1]
            parts = inner.split("].[")
            if len(parts) == 2:
                seen_tables.add(name)
                tables.append({"name": name, "schema": parts[0], "table": parts[1], "is_custom_sql": False})
                added.append(name)

    elif rel_type == "text":
        conn_ref = el.get("connection", "")
        if conn_ref not in pg_conns:
            return added
        name = el.get("name", "Custom SQL")
        if name not in seen_tables:
            sql_text = (el.text or "").strip()
            seen_tables.add(name)
            tables.append({
                "name": name, "schema": "", "table": name, "is_custom_sql": True,
                "sql_preview": sql_text[:80] + ("…" if len(sql_text) > 80 else ""),
            })
            added.append(name)

    elif rel_type == "join":
        join_type = el.get("join", "inner")
        conditions: List[Dict] = []
        for clause in el:
            if clause.tag == "clause":
                for expr in clause:
                    if expr.tag == "expression":
                        conditions.extend(_parse_join_expr(expr))
                break

        for child in el:
            if _is_rel_tag(child.tag):
                added.extend(_collect_classic_joins(child, pg_conns, tables, joins, seen_tables, seen_join_keys))

        # Record join using condition-derived table pairs
        if conditions:
            grouped: Dict[tuple, Dict] = {}
            for cond in conditions:
                lt, rt = cond.get("left_table", ""), cond.get("right_table", "")
                if lt and rt:
                    key = tuple(sorted([lt, rt]))
                    if key not in grouped:
                        grouped[key] = {"left_table": lt, "right_table": rt, "conditions": []}
                    grouped[key]["conditions"].append(cond)
            for key, info in grouped.items():
                if key not in seen_join_keys:
                    seen_join_keys.add(key)
                    joins.append({
                        "left_table": info["left_table"],
                        "right_table": info["right_table"],
                        "join_type": join_type,
                        "conditions": info["conditions"],
                    })
        elif len(added) >= 2:
            key = tuple(sorted([added[0], added[-1]]))
            if key not in seen_join_keys:
                seen_join_keys.add(key)
                joins.append({"left_table": added[0], "right_table": added[-1], "join_type": join_type, "conditions": []})

    else:
        for child in el:
            if _is_rel_tag(child.tag):
                added.extend(_collect_classic_joins(child, pg_conns, tables, joins, seen_tables, seen_join_keys))

    return added


def _collect_object_graph(
    ds_elem: ET.Element,
    tables: List[Dict],
    joins: List[Dict],
    seen_tables: set,
    seen_join_keys: set,
    pg_conns: set = None,
) -> None:
    """Parse tables and joins from Tableau's newer object-graph relationship model."""
    og_tag = "_.fcp.ObjectModelEncapsulateLegacy.true...object-graph"
    og_elem = None
    for el in ds_elem.iter():
        if el.tag == og_tag:
            og_elem = el
            break
    if og_elem is None:
        return

    obj_map: Dict[str, Dict] = {}
    objects_el = og_elem.find("objects")
    if objects_el is not None:
        for obj in objects_el.findall("object"):
            obj_id  = obj.get("id", "")
            caption = obj.get("caption", "")
            for props in obj.findall("properties"):
                if props.get("context", "") == "":
                    rel = props.find("relation")
                    if rel is not None and rel.get("type") == "table":
                        table_str = rel.get("table", "")
                        name      = rel.get("name", "")
                        if table_str.startswith("[") and "].[" in table_str:
                            inner = table_str[1:-1]
                            parts = inner.split("].[")
                            if len(parts) == 2:
                                obj_map[obj_id] = {
                                    "name": name, "schema": parts[0], "table": parts[1],
                                    "caption": caption, "is_compound": False,
                                }
                    elif rel is not None and rel.get("type") == "join":
                        # Compound object — expand its physical sub-tables so they
                        # appear individually in the mapping UI and can be removed.
                        if pg_conns is not None:
                            _collect_classic_joins(
                                rel, pg_conns, tables, joins, seen_tables, seen_join_keys
                            )
                        # Skip adding the compound wrapper itself — sub-tables are what matter.
                    else:
                        # No live relation (e.g. extract-only object) — still add
                        # to obj_map so relationships can reference it.
                        obj_map[obj_id] = {
                            "name": obj_id, "schema": "", "table": caption or obj_id,
                            "caption": caption, "is_compound": False,
                        }
                    break

    for t in obj_map.values():
        if t["name"] not in seen_tables:
            seen_tables.add(t["name"])
            tables.append({
                "name": t["name"], "schema": t["schema"], "table": t["table"],
                "caption": t.get("caption", ""), "is_compound": t.get("is_compound", False),
                "is_custom_sql": False,
            })

    rels_el = og_elem.find("relationships")
    if rels_el is None:
        return

    for rel in rels_el.findall("relationship"):
        first_ep = rel.find("first-end-point")
        second_ep = rel.find("second-end-point")
        expr = rel.find("expression")
        if first_ep is None or second_ep is None:
            continue
        first_tbl = obj_map.get(first_ep.get("object-id", ""))
        second_tbl = obj_map.get(second_ep.get("object-id", ""))
        if not first_tbl or not second_tbl:
            continue

        conditions: List[Dict] = []
        if expr is not None and expr.get("op") == "=":
            children = list(expr)
            if len(children) == 2:
                col1 = children[0].get("op", "").strip("[]")
                col2 = children[1].get("op", "").strip("[]")
                if col1 and col2:
                    conditions.append({
                        "left_table": first_tbl["name"], "left_col": col1,
                        "right_table": second_tbl["name"], "right_col": col2,
                    })

        key = tuple(sorted([first_tbl["name"], second_tbl["name"]]))
        if key not in seen_join_keys:
            seen_join_keys.add(key)
            joins.append({
                "left_table": first_tbl["name"],
                "right_table": second_tbl["name"],
                "join_type": "relationship",
                "conditions": conditions,
            })


def _parse_join_expr(expr_el: ET.Element) -> List[Dict]:
    """Parse a Tableau join expression element into a list of column-pair conditions."""
    conditions: List[Dict] = []
    op = expr_el.get("op", "")
    if op == "=":
        children = list(expr_el)
        if len(children) == 2:
            left = _parse_join_col_ref(children[0].get("op", ""))
            right = _parse_join_col_ref(children[1].get("op", ""))
            if left and right:
                conditions.append({
                    "left_table": left[0], "left_col": left[1],
                    "right_table": right[0], "right_col": right[1],
                })
    elif op in ("AND", "OR"):
        for child in expr_el:
            conditions.extend(_parse_join_expr(child))
    return conditions


def _parse_join_col_ref(ref: str):
    """Parse '[TableName].[ColumnName]' → (table_name, col_name) or None."""
    if ref.startswith("[") and "].[" in ref and ref.endswith("]"):
        inner = ref[1:-1]
        parts = inner.split("].[")
        if len(parts) == 2:
            return (parts[0], parts[1])
    return None
