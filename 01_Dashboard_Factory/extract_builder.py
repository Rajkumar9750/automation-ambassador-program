"""
Build Tableau .hyper extract files for generated workbooks.

Connects to the new client's PostgreSQL, queries each relation, and writes
the results into .hyper files so the workbook opens with data already loaded.

Two extract patterns are handled:
  - Multi-table: each live relation (table/custom-SQL) gets its own hyper table
  - Single-table: the full join tree is materialised into a single Extract.Extract table
"""
import html
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
from tableauhyperapi import (
    Connection as HyperConnection,
    CreateMode,
    HyperProcess,
    Inserter,
    NULLABLE,
    SchemaName,
    SqlType,
    TableDefinition,
    TableName,
    Telemetry,
)

# ── PostgreSQL → Hyper type map ───────────────────────────────────────────────

_PG_TO_HYPER: Dict[str, SqlType] = {
    "integer":                     SqlType.int(),
    "bigint":                      SqlType.big_int(),
    "smallint":                    SqlType.small_int(),
    "double precision":            SqlType.double(),
    "real":                        SqlType.double(),
    "numeric":                     SqlType.double(),
    "decimal":                     SqlType.double(),
    "text":                        SqlType.text(),
    "character varying":           SqlType.text(),
    "character":                   SqlType.text(),
    "boolean":                     SqlType.bool(),
    "date":                        SqlType.date(),
    "timestamp without time zone": SqlType.timestamp(),
    "timestamp with time zone":    SqlType.timestamp_tz(),
    "uuid":                        SqlType.text(),
    "json":                        SqlType.text(),
    "jsonb":                       SqlType.text(),
    "name":                        SqlType.text(),
    "bytea":                       SqlType.text(),
}

# ── Tableau local-type → Hyper type map ──────────────────────────────────────
# Used to match extract column types to what the reference workbook declares,
# so the .hyper schema is consistent with the TWB's <column datatype=...> declarations.

_TABLEAU_TO_HYPER: Dict[str, SqlType] = {
    "integer":  SqlType.big_int(),
    "real":     SqlType.double(),
    "string":   SqlType.text(),
    "boolean":  SqlType.bool(),
    "date":     SqlType.date(),
    "datetime": SqlType.timestamp(),
}


def _pg_to_hyper_type(pg_type: str) -> SqlType:
    return _PG_TO_HYPER.get(pg_type.lower().strip(), SqlType.text())


def _tableau_to_hyper_type(tableau_type: str) -> SqlType:
    return _TABLEAU_TO_HYPER.get(tableau_type.lower().strip(), SqlType.text())


def _parse_ref_col_types(twb_content: str) -> Dict[str, str]:
    """
    Parse {remote_col_name: tableau_local_type} from the TWB's metadata-records.
    Used to align Hyper extract column types with the reference workbook's declarations.
    """
    result: Dict[str, str] = {}
    try:
        root = ET.fromstring(twb_content)
    except ET.ParseError:
        return result
    for record in root.iter("metadata-record"):
        if record.get("class") != "column":
            continue
        rn = record.find("remote-name")
        lt = record.find("local-type")
        if rn is not None and lt is not None:
            col = (rn.text or "").strip()
            typ = (lt.text or "").strip()
            if col and typ:
                result[col] = typ
    return result


# ── PG connection helper ──────────────────────────────────────────────────────

def _pg_conn(params: Dict[str, Any]):
    ssl = params.get("sslmode", "require")
    if ssl in ("none", "disable"):
        ssl = "disable"
    return psycopg2.connect(
        host=params["host"],
        port=int(params.get("port", 5432)),
        dbname=params["database"],
        user=params["username"],
        password=params["password"],
        sslmode=ssl,
        connect_timeout=30,
    )


# ── Public API ────────────────────────────────────────────────────────────────

def build_extracts(
    twb_content: str,
    pg_params: Dict[str, Any],
    extracts_dir: str,
) -> Tuple[str, List[Dict]]:
    """
    Create fresh .hyper extract files for every federated datasource that has an extract.
    Returns (modified_twb_content, repair_log).
    """
    repair_log: List[Dict] = []
    ds_list = _parse_datasource_extracts(twb_content)
    if not ds_list:
        repair_log.append({
            "type": "extract", "severity": "warning",
            "title": "No extracts detected in workbook",
            "description": "The reference workbook has no embedded extracts — nothing to build.",
            "fix": "If you need an extract, open the workbook in Tableau Desktop and choose Data > Extract Data.",
        })
        return twb_content, repair_log

    # Parse reference column types from the TWB so Hyper schemas match declarations
    ref_col_types = _parse_ref_col_types(twb_content)

    os.makedirs(extracts_dir, exist_ok=True)

    with HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hyper:
        for ds in ds_list:
            hyper_path = os.path.join(extracts_dir, ds["hyper_filename"])
            try:
                issues, total_rows = _build_single_extract(hyper, hyper_path, ds, pg_params, ref_col_types)
                repair_log.extend(issues)
                twb_content = _update_extract_timestamp(twb_content, ds["hyper_dbname"])
                # Remove <cols> mappings for columns that don't exist in the hyper so
                # Tableau computes formula fields locally instead of falling back to the
                # live DB (which would fail with type-cast errors like INT("2-Poor")).
                twb_content = _prune_cols_mappings(twb_content, hyper, hyper_path, ds["hyper_dbname"])
                repair_log.append({
                    "type": "extract", "severity": "fixed",
                    "title": f"Extract created: {ds['caption']}",
                    "description": (
                        f"Loaded {total_rows:,} rows across {len(ds['extract_tables'])} "
                        f"table(s) into {ds['hyper_filename']}."
                    ),
                    "fix": "Extract is embedded — no manual refresh needed to open the workbook.",
                })
            except Exception as exc:
                repair_log.append({
                    "type": "extract_error", "severity": "error",
                    "title": f"Extract creation failed: {ds['caption']}",
                    "description": str(exc),
                    "fix": (
                        "Open in Tableau Desktop and create the extract manually via "
                        "Data > Extract Data. Check the error above to diagnose root cause."
                    ),
                })

    return twb_content, repair_log


def _prune_cols_mappings(
    twb_content: str,
    hyper: HyperProcess,
    hyper_path: str,
    hyper_dbname: str,
) -> str:
    """
    Remove <cols><map> entries that reference columns absent from the hyper file.

    The reference workbook's <cols> section often maps Tableau formula columns
    (Calculation_XXXX) that were materialised in the original extract.  Our
    extract only contains physical DB columns, so those mappings are stale.
    When Tableau can't find a mapped column in the hyper it falls back to the
    live DB connection; formula evaluation there (e.g. INT("2-Poor")) triggers
    PostgreSQL type-cast errors.  Removing the stale mappings lets Tableau
    evaluate the formulas locally from the extract's physical columns instead.
    """
    # ── 1. Read actual columns from the hyper file ────────────────────────────
    hyper_cols: Dict[str, set] = {}   # lower-case table name → set of col name strings
    try:
        with HyperConnection(hyper.endpoint, hyper_path) as conn:
            for schema in conn.catalog.get_schema_names():
                for tbl in conn.catalog.get_table_names(schema):
                    td  = conn.catalog.get_table_definition(tbl)
                    key = str(tbl.name).strip('"').lower()
                    hyper_cols[key] = {str(c.name).strip('"') for c in td.columns}
    except Exception:
        return twb_content   # can't read hyper — leave TWB unchanged

    def _col_exists(value: str) -> bool:
        """
        Return True if the value side of a <map> entry points to a real hyper column.
        Formats:
          single-table: [col]
          multi-table:  [table_name].[col]
        """
        parts = re.findall(r'\[([^\]]+)\]', value)
        if not parts:
            return True   # unparseable — keep
        col = parts[-1]
        if len(parts) == 1:
            # single-table — check every table
            return any(col in cols for cols in hyper_cols.values())
        tbl = parts[-2].lower()
        cols = hyper_cols.get(tbl) or hyper_cols.get(parts[-2]) or set()
        return col in cols

    def _filter_cols_section(cols_match: "re.Match") -> str:
        return re.sub(
            r"<map\b[^/]*/>\s*",
            lambda m: m.group(0) if _col_exists(
                (re.search(r"value='([^']*)'", m.group(0)) or type("", (), {"group": lambda *a: ""})()).group(1)
            ) else "",
            cols_match.group(0),
        )

    def _filter_extract_block(ext_match: "re.Match") -> str:
        return re.sub(
            r"<cols>.*?</cols>",
            _filter_cols_section,
            ext_match.group(0),
            flags=re.DOTALL,
        )

    # ── 2. Find the extract block for this specific hyper file and filter it ──
    pattern = re.compile(
        r"<extract\b[^>]*>(?:(?!</extract>).)*?"
        + re.escape(hyper_dbname)
        + r"(?:(?!</extract>).)*?</extract>",
        re.DOTALL,
    )
    return pattern.sub(_filter_extract_block, twb_content)


# ── Parse extract definitions from TWB XML ───────────────────────────────────

def _parse_datasource_extracts(twb_content: str) -> List[Dict]:
    results: List[Dict] = []
    for ds_m in re.finditer(r"<datasource\b([^>]*)>", twb_content):
        attrs = ds_m.group(1)
        if "federated." not in attrs:
            continue
        ds_start = ds_m.start()
        ds_end = twb_content.find("</datasource>", ds_start)
        if ds_end == -1:
            continue
        ds_end += len("</datasource>")
        block = twb_content[ds_start:ds_end]

        if "<extract " not in block:
            continue

        name_m = re.search(r"name='([^']*)'", attrs)
        cap_m  = re.search(r"caption='([^']*)'", attrs)
        ds_name    = name_m.group(1) if name_m else ""
        ds_caption = cap_m.group(1)  if cap_m  else ds_name

        hyper_m = re.search(r"class='hyper'[^>]*dbname='([^']*\.hyper)'", block)
        if not hyper_m:
            continue
        hyper_dbname   = hyper_m.group(1)
        hyper_filename = os.path.basename(hyper_dbname)

        extract_tables: List[Dict] = []
        for m in re.finditer(
            r"<relation\b[^>]*name='([^']*)'\s+table='\[Extract\]\.\[([^\]]*)\]'\s+type='table'\s*/>",
            block,
        ):
            entry = {"name": m.group(1), "hyper_table": m.group(2)}
            if entry not in extract_tables:
                extract_tables.append(entry)

        live_relations = _parse_live_relations(block)

        results.append({
            "ds_name":       ds_name,
            "caption":       ds_caption,
            "hyper_filename": hyper_filename,
            "hyper_dbname":  hyper_dbname,
            "extract_tables": extract_tables,
            "live_relations": live_relations,
            "block":         block,
        })

    return results


def _parse_live_relations(ds_block: str) -> List[Dict]:
    """Return leaf relations from the live (postgres) federated connection only."""
    # Restrict to just the <connection class='federated'>...</connection> block
    # so we don't pick up the extract's hyper-relation entries.
    conn_start = ds_block.find("<connection class='federated'>")
    if conn_start == -1:
        return []
    conn_end = ds_block.find("</connection>", conn_start)
    if conn_end == -1:
        search_block = ds_block[conn_start:]
    else:
        search_block = ds_block[conn_start:conn_end + len("</connection>")]

    relations: List[Dict] = []
    seen_names: set = set()

    # Regular table relations  (attribute order varies)
    for m in re.finditer(r"<relation\b([^>]*)/>", search_block):
        a = m.group(1)
        if "type='table'" not in a:
            continue
        name_m   = re.search(r"name='([^']*)'",  a)
        table_m  = re.search(r"table='\[([^\]]+)\]\.\[([^\]]+)\]'", a)
        if not (name_m and table_m):
            continue
        rel_name = name_m.group(1)
        if rel_name in seen_names:
            continue
        seen_names.add(rel_name)
        relations.append({
            "name":   rel_name,
            "type":   "table",
            "schema": table_m.group(1),
            "table":  table_m.group(2),
        })

    # Custom SQL relations
    for m in re.finditer(
        r"(<relation\b[^>]*type='text'[^>]*>)(.*?)(</relation>)", search_block, re.DOTALL
    ):
        name_m = re.search(r"name='([^']*)'", m.group(1))
        rel_name = name_m.group(1) if name_m else "Custom SQL"
        if rel_name in seen_names:
            continue
        seen_names.add(rel_name)
        sql_text = html.unescape(m.group(2).replace("&#13;", "\n").replace("&#10;", "\n"))
        relations.append({"name": rel_name, "type": "custom_sql", "sql": sql_text})

    return relations


# ── Build one hyper file ──────────────────────────────────────────────────────

def _build_single_extract(
    hyper: HyperProcess,
    hyper_path: str,
    ds: Dict,
    pg_params: Dict[str, Any],
    ref_col_types: Optional[Dict[str, str]] = None,
) -> Tuple[List[Dict], int]:
    issues: List[Dict] = []
    total_rows = 0

    extract_tables = ds["extract_tables"]
    live_relations = ds["live_relations"]

    is_single_table = (
        len(extract_tables) == 1
        and extract_tables[0]["name"] == "Extract"
        and extract_tables[0]["hyper_table"] == "Extract"
    )

    with HyperConnection(hyper.endpoint, hyper_path, CreateMode.CREATE_AND_REPLACE) as conn:
        conn.catalog.create_schema_if_not_exists(SchemaName("Extract"))

        if is_single_table:
            rows, tbl_issues = _build_materialised_extract(conn, ds, pg_params, ref_col_types)
            issues.extend(tbl_issues)
            total_rows += rows
        else:
            for ext_tbl in extract_tables:
                rows, tbl_issues = _build_multitable_extract_table(
                    conn, ext_tbl, live_relations, pg_params, ref_col_types
                )
                issues.extend(tbl_issues)
                total_rows += rows

    return issues, total_rows


# ── Multi-table extract ───────────────────────────────────────────────────────

def _build_multitable_extract_table(
    conn: HyperConnection,
    ext_tbl: Dict,
    live_relations: List[Dict],
    pg_params: Dict[str, Any],
    ref_col_types: Optional[Dict[str, str]] = None,
) -> Tuple[int, List[Dict]]:
    """Query one source relation and write it as an Extract-schema table."""
    issues: List[Dict] = []
    hyper_table_name = ext_tbl["hyper_table"]

    source = _match_extract_table_to_relation(hyper_table_name, live_relations)
    if source is None:
        issues.append({
            "type": "extract_warning", "severity": "warning",
            "title": f"No source found for extract table '{hyper_table_name[:60]}'",
            "description": "Could not match the extract table to a live relation.",
            "fix": "This table will be empty in the extract. Verify table mappings.",
        })
        return 0, issues

    if source["type"] == "table":
        sql = f'SELECT * FROM "{source["schema"]}"."{source["table"]}"'
    else:
        sql = source["sql"]

    try:
        rows = _execute_and_write(conn, sql, pg_params, hyper_table_name, ref_col_types=ref_col_types)
        return rows, issues
    except Exception as exc:
        issues.append({
            "type": "extract_error", "severity": "error",
            "title": f"Failed to extract table '{hyper_table_name[:60]}'",
            "description": str(exc),
            "fix": "Check that the table/query is accessible and returns valid data.",
        })
        # Create an empty table with the correct schema so <cols> mappings are
        # satisfied and Tableau never falls back to the live connection for these
        # columns (which would trigger MAKEPOINT / spatial limitation errors).
        try:
            _create_empty_hyper_table(conn, sql, pg_params, hyper_table_name, ref_col_types)
            issues.append({
                "type": "extract_warning", "severity": "warning",
                "title": f"Empty schema stub created for '{hyper_table_name[:60]}'",
                "description": (
                    "The data query failed but an empty table was created so Tableau "
                    "can still open the workbook using the extract."
                ),
                "fix": "Fix the source table/query access and regenerate to populate this table.",
            })
        except Exception:
            pass  # best-effort — if schema stub also fails, log nothing extra
        return 0, issues


def _create_empty_hyper_table(
    conn: HyperConnection,
    sql: str,
    pg_params: Dict[str, Any],
    hyper_table_name: str,
    ref_col_types: Optional[Dict[str, str]] = None,
) -> None:
    """
    Run SELECT … LIMIT 0 to get column metadata only, then create an empty
    Hyper table.  Used as a fallback when the data fetch fails so that the
    extract's <cols> mappings are satisfied and Tableau never tries to fall
    back to the live connection for these columns.
    """
    pg = _pg_conn(pg_params)
    try:
        with pg.cursor() as cur:
            limit_sql = f"SELECT * FROM ({sql.rstrip().rstrip(';')}) _q LIMIT 0"
            cur.execute(limit_sql)
            if cur.description is None:
                return
            col_names  = _deduplicate_names([d[0] for d in cur.description])
            pg_types   = _infer_pg_types(cur.description)
            columns = []
            for name, pg_type in zip(col_names, pg_types):
                ref_tableau = (ref_col_types or {}).get(name)
                hyper_type  = (_tableau_to_hyper_type(ref_tableau)
                               if ref_tableau else _pg_to_hyper_type(pg_type))
                columns.append(TableDefinition.Column(name, hyper_type, NULLABLE))
            table_def = TableDefinition(TableName("Extract", hyper_table_name), columns)
            conn.catalog.create_table_if_not_exists(table_def)
    finally:
        pg.close()


def _match_extract_table_to_relation(
    hyper_table: str, live_relations: List[Dict]
) -> Optional[Dict]:
    """
    Extract table names follow the pattern:
      - "{rel_name} ({schema}.{rel_name})_{HASH}"  → regular table relation
      - "_{HASH}"                                   → custom SQL (no descriptive name)
    """
    # Try to parse "name (schema.name)_HASH"
    m = re.match(r"^(.+?)\s+\([^)]+\)_[A-F0-9]+$", hyper_table, re.IGNORECASE)
    if m:
        rel_name = m.group(1)
        for rel in live_relations:
            if rel["name"] == rel_name:
                return rel
        # Fallback: match by table name
        for rel in live_relations:
            if rel.get("table", "") == rel_name:
                return rel

    # Hash-only name → custom SQL
    if re.match(r"^_[A-F0-9]+$", hyper_table, re.IGNORECASE):
        for rel in live_relations:
            if rel["type"] == "custom_sql":
                return rel

    return None


# ── Single-table materialised extract ────────────────────────────────────────

def _build_materialised_extract(
    conn: HyperConnection,
    ds: Dict,
    pg_params: Dict[str, Any],
    ref_col_types: Optional[Dict[str, str]] = None,
) -> Tuple[int, List[Dict]]:
    """
    For single-table extracts Tableau materialises the full federated join.
    We reconstruct the join SQL from the live connection's relation tree.
    """
    issues: List[Dict] = []
    sql = _generate_join_sql(ds["block"], ds["live_relations"])

    if not sql:
        issues.append({
            "type": "extract_warning", "severity": "warning",
            "title": f"Could not generate join SQL for '{ds['caption']}'",
            "description": "The join tree could not be parsed — extract will be empty.",
            "fix": "Create the extract manually in Tableau Desktop.",
        })
        return 0, issues

    try:
        rows = _execute_and_write(conn, sql, pg_params, "Extract", add_row_id_col=True, ref_col_types=ref_col_types)
        return rows, issues
    except Exception as exc:
        fallback_sql, fallback_src = _fallback_query(ds["live_relations"])
        if fallback_sql:
            try:
                rows = _execute_and_write(conn, fallback_sql, pg_params, "Extract", ref_col_types=ref_col_types)
                issues.append({
                    "type": "extract_warning", "severity": "warning",
                    "title": f"Full join failed — used fallback query: {fallback_src}",
                    "description": f"Original error: {exc}",
                    "fix": "The extract uses the primary relation only. Refresh in Tableau Desktop for the full joined dataset.",
                })
                return rows, issues
            except Exception as exc2:
                issues.append({
                    "type": "extract_error", "severity": "error",
                    "title": "Fallback query also failed",
                    "description": str(exc2),
                    "fix": "Create the extract manually in Tableau Desktop.",
                })
        else:
            issues.append({
                "type": "extract_error", "severity": "error",
                "title": f"Extract query failed for '{ds['caption']}'",
                "description": str(exc),
                "fix": "Create the extract manually in Tableau Desktop.",
            })
        return 0, issues


def _fallback_query(live_relations: List[Dict]) -> Tuple[Optional[str], str]:
    """Return a simple fallback query using the biggest relation."""
    for rel in live_relations:
        if rel["type"] == "custom_sql":
            return rel["sql"], rel["name"]
    for rel in live_relations:
        if rel["type"] == "table":
            return f'SELECT * FROM "{rel["schema"]}"."{rel["table"]}"', rel["name"]
    return None, ""


# ── Join SQL generation ───────────────────────────────────────────────────────

def _generate_join_sql(ds_block: str, live_relations: List[Dict]) -> Optional[str]:
    """
    Parse the live federated connection's relation tree and produce a SQL query
    that replicates the join Tableau would materialise for the extract.
    """
    try:
        # Isolate ONLY the <connection class='federated'>...</connection> element.
        # The inner <connection class='postgres'> elements are self-closing, so
        # the first </connection> after the opening tag closes the federated block.
        conn_start = ds_block.find("<connection class='federated'>")
        if conn_start == -1:
            return None
        conn_end = ds_block.find("</connection>", conn_start)
        if conn_end == -1:
            return None
        conn_end += len("</connection>")
        live_xml = ds_block[conn_start:conn_end]

        # Strip Tableau namespace prefixes (user:*, _.fcp.*) that break ET
        live_xml = re.sub(r'\s+(?:user|_\w+):[a-zA-Z0-9_-]+=\'[^\']*\'', '', live_xml)
        live_xml = re.sub(r'\s+(?:user|_\w+):[a-zA-Z0-9_-]+="[^"]*"', '', live_xml)

        root = ET.fromstring(f"<root>{live_xml}</root>")
        conn_el = root.find("connection")
        if conn_el is None:
            return None

        top_rel = None
        for child in conn_el:
            if child.tag == "relation":
                top_rel = child
                break
        if top_rel is None:
            return None

        # Build CTE map: relation_name → (cte_alias, cte_sql)
        ctes: List[str] = []
        alias_map: Dict[str, str] = {}  # relation name → CTE alias

        def collect_ctes(el: ET.Element) -> None:
            rel_type = el.get("type", "")
            if rel_type == "table":
                tbl_m = re.match(r"\[([^\]]+)\]\.\[([^\]]+)\]", el.get("table", ""))
                if not tbl_m:
                    return
                schema, table = tbl_m.group(1), tbl_m.group(2)
                name = el.get("name", table)
                alias = f"_t{len(ctes)}"
                ctes.append(f'"{alias}" AS (SELECT * FROM "{schema}"."{table}")')
                alias_map[name] = alias
            elif rel_type == "text":
                sql_text = (el.text or "").replace("&#13;", "\n").replace("&#10;", "\n")
                name = el.get("name", f"custom_{len(ctes)}")
                alias = f"_t{len(ctes)}"
                ctes.append(f'"{alias}" AS ({sql_text})')
                alias_map[name] = alias
            else:
                for child in el:
                    if child.tag == "relation":
                        collect_ctes(child)

        collect_ctes(top_rel)

        join_sql = _rel_to_join_sql(top_rel, alias_map)
        if not join_sql:
            return None

        cte_clause = "WITH\n" + ",\n".join(ctes) if ctes else ""
        return f"{cte_clause}\nSELECT * FROM {join_sql}"
    except Exception:
        return None


def _rel_to_join_sql(el: ET.Element, alias_map: Dict[str, str]) -> Optional[str]:
    rel_type = el.get("type", "")

    if rel_type in ("table", "text"):
        name = el.get("name", "")
        alias = alias_map.get(name)
        if alias:
            return f'"{alias}"'
        return None

    elif rel_type == "join":
        join_kw_map = {
            "left": "LEFT JOIN", "right": "RIGHT JOIN",
            "inner": "INNER JOIN", "full": "FULL JOIN",
        }
        join_kw = join_kw_map.get(el.get("join", "inner"), "INNER JOIN")
        children = [c for c in el if c.tag == "relation"]
        if len(children) < 2:
            return None
        left_sql  = _rel_to_join_sql(children[0], alias_map)
        right_sql = _rel_to_join_sql(children[1], alias_map)
        if not (left_sql and right_sql):
            return None

        clause = el.find("clause")
        on_clause = _clause_to_sql(clause, alias_map)
        return f"{left_sql} {join_kw} {right_sql} ON {on_clause}"

    elif rel_type == "collection":
        children = [c for c in el if c.tag == "relation"]
        if not children:
            return None
        sql = _rel_to_join_sql(children[0], alias_map)
        for child in children[1:]:
            right = _rel_to_join_sql(child, alias_map)
            if right:
                sql = f"{sql} CROSS JOIN {right}"
        return sql

    return None


def _clause_to_sql(clause: Optional[ET.Element], alias_map: Dict[str, str]) -> str:
    if clause is None:
        return "TRUE"
    expr = clause.find("expression")
    if expr is None:
        return "TRUE"
    return _expr_to_sql(expr, alias_map)


def _expr_to_sql(expr: ET.Element, alias_map: Dict[str, str]) -> str:
    op = expr.get("op", "")
    children = list(expr)

    if op in ("=", "<", ">", "!=", "<=", ">="):
        parts = [_expr_to_sql(c, alias_map) for c in children]
        return f" {op} ".join(parts)

    if op in ("AND", "OR"):
        parts = [_expr_to_sql(c, alias_map) for c in children]
        return f" {op} ".join(f"({p})" for p in parts)

    if op.startswith("[") and "].[" in op:
        inner = op[1:-1]
        tbl, col = inner.split("].[", 1)
        alias = alias_map.get(tbl, tbl)
        return f'"{alias}"."{col}"'

    return op or "TRUE"


# ── Execute query → write to hyper ────────────────────────────────────────────

def _execute_and_write(
    conn: HyperConnection,
    sql: str,
    pg_params: Dict[str, Any],
    hyper_table_name: str,
    add_row_id_col: bool = False,
    ref_col_types: Optional[Dict[str, str]] = None,
) -> int:
    pg = _pg_conn(pg_params)
    try:
        with pg.cursor() as cur:
            clean_sql = sql.rstrip().rstrip(";")
            cur.execute(clean_sql)
            if cur.description is None:
                return 0

            raw_cols = [d[0] for d in cur.description]
            col_names = _deduplicate_names(raw_cols)
            pg_types = _infer_pg_types(cur.description)

            # Build Hyper columns: use reference workbook's declared Tableau type when
            # available so the extract schema matches the TWB declarations exactly.
            columns = []
            effective_ref_types: List[Optional[str]] = []
            for name, pg_type in zip(col_names, pg_types):
                ref_tableau = (ref_col_types or {}).get(name)
                effective_ref_types.append(ref_tableau)
                if ref_tableau:
                    hyper_type = _tableau_to_hyper_type(ref_tableau)
                else:
                    hyper_type = _pg_to_hyper_type(pg_type)
                columns.append(TableDefinition.Column(name, hyper_type, NULLABLE))

            table_def = TableDefinition(TableName("Extract", hyper_table_name), columns)
            conn.catalog.create_table_if_not_exists(table_def)

            rows_written = 0
            with Inserter(conn, table_def) as inserter:
                batch: List[tuple] = []
                for row in cur:
                    safe_row = _safe_row(row, pg_types, effective_ref_types)
                    batch.append(safe_row)
                    if len(batch) >= 5000:
                        inserter.add_rows(batch)
                        rows_written += len(batch)
                        batch = []
                if batch:
                    inserter.add_rows(batch)
                    rows_written += len(batch)
                inserter.execute()

            return rows_written
    finally:
        pg.close()


def _deduplicate_names(names: List[str]) -> List[str]:
    seen: Dict[str, int] = {}
    result: List[str] = []
    for n in names:
        if n in seen:
            seen[n] += 1
            result.append(f"{n}_{seen[n]}")
        else:
            seen[n] = 0
            result.append(n)
    return result


def _infer_pg_types(description) -> List[str]:
    """
    Map psycopg2 type OIDs to a loose PG type name.
    We use a conservative mapping that maps all numeric OIDs to types that
    Hyper can handle without strict casting.
    """
    import psycopg2.extensions as ext
    oid_map = {
        16:   "boolean",
        17:   "bytea",
        20:   "bigint",
        21:   "smallint",
        23:   "integer",
        25:   "text",
        700:  "real",
        701:  "double precision",
        1082: "date",
        1114: "timestamp without time zone",
        1184: "timestamp with time zone",
        1043: "character varying",
        1700: "numeric",
        2950: "uuid",
        114:  "json",
        3802: "jsonb",
    }
    return [oid_map.get(col.type_code, "text") for col in description]


def _safe_row(
    row: tuple,
    pg_types: List[str],
    ref_types: Optional[List[Optional[str]]] = None,
) -> tuple:
    """Cast row values to be safe for Hyper insertion, coercing to reference types when known."""
    out = []
    for i, (val, pg_type) in enumerate(zip(row, pg_types)):
        ref_type = ref_types[i] if ref_types and i < len(ref_types) else None
        if val is None:
            out.append(None)
            continue
        if isinstance(val, memoryview):
            out.append(bytes(val).decode("utf-8", errors="replace"))
            continue
        if pg_type in ("json", "jsonb"):
            out.append(str(val))
            continue
        # Coerce to reference type so Hyper schema matches TWB declarations
        if ref_type == "integer":
            try:
                out.append(int(val) if isinstance(val, bool) else int(float(val)))
            except (ValueError, TypeError):
                out.append(None)
        elif ref_type == "real":
            try:
                out.append(float(val))
            except (ValueError, TypeError):
                out.append(None)
        elif ref_type == "string":
            out.append(val if isinstance(val, str) else str(val))
        elif ref_type == "boolean":
            if isinstance(val, bool):
                out.append(val)
            elif isinstance(val, (int, float)):
                out.append(bool(val))
            elif isinstance(val, str):
                out.append(val.strip().lower() in ("true", "1", "yes", "t", "on"))
            else:
                out.append(None)
        elif isinstance(val, Decimal):
            out.append(float(val))
        else:
            out.append(val)
    return tuple(out)


# ── TWB timestamp update ──────────────────────────────────────────────────────

def _update_extract_timestamp(twb_content: str, hyper_dbname: str) -> str:
    now_str = datetime.now().strftime("%m/%d/%Y %I:%M:%S %p")
    pattern = re.compile(
        rf"(class='hyper'\s+dbname='{re.escape(hyper_dbname)}'[^>]*update-time=')[^']*(')"
    )
    new_content, n = pattern.subn(rf"\g<1>{now_str}\g<2>", twb_content)
    if n == 0:
        # Attribute order may differ — do a broader match
        pattern2 = re.compile(
            rf"(dbname='{re.escape(hyper_dbname)}'[^>]*?)(\bupdate-time=')[^']*(')"
        )
        new_content, _ = pattern2.subn(rf"\g<1>\g<2>{now_str}\g<3>", twb_content)
    return new_content
