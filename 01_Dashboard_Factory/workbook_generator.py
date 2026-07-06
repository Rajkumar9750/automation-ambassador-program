"""
Generate a new .twbx workbook by swapping Postgres connections and table references
from a reference workbook, keeping all dashboards, worksheets, and calculations intact.
"""
import zipfile
import os
import re
import tempfile
from typing import List, Dict, Any, Optional, Tuple

from workbook_parser import parse_column_types_from_metadata


def _pg_to_tableau_type(pg_type: str) -> str:
    """Map PostgreSQL data_type string to Tableau local-type string."""
    pg = pg_type.lower().strip()
    if pg in ("integer", "bigint", "smallint", "int4", "int8", "int2", "serial", "bigserial"):
        return "integer"
    if pg in ("character varying", "varchar", "text", "character", "char", "bpchar", "name", "uuid"):
        return "string"
    if pg in ("numeric", "decimal", "double precision", "real", "float4", "float8", "money"):
        return "real"
    if pg in ("boolean", "bool"):
        return "boolean"
    if "timestamp" in pg or "time" in pg:
        return "datetime"
    if pg == "date":
        return "date"
    return "string"


# Maps PostgreSQL data_type → ODBC SQL type code used in Tableau's <remote-type>
_PG_TO_ODBC_REMOTE_TYPE: Dict[str, str] = {
    # Integer types
    "integer":                     "4",    # SQL_INTEGER
    "int":                         "4",
    "int4":                        "4",
    "serial":                      "4",
    "bigint":                      "-5",   # SQL_BIGINT
    "int8":                        "-5",
    "bigserial":                   "-5",
    "smallint":                    "5",    # SQL_SMALLINT
    "int2":                        "5",
    "smallserial":                 "5",
    # Floating-point types
    "double precision":            "8",    # SQL_DOUBLE
    "float8":                      "8",
    "float":                       "8",
    "real":                        "7",    # SQL_REAL
    "float4":                      "7",
    # Exact numeric
    "numeric":                     "131",  # SQL_DECIMAL
    "decimal":                     "131",
    "money":                       "131",
    # Boolean
    "boolean":                     "16",   # SQL_BIT
    "bool":                        "16",
    # Date/time
    "date":                        "91",   # SQL_TYPE_DATE
    "timestamp without time zone": "93",   # SQL_TYPE_TIMESTAMP
    "timestamp with time zone":    "93",
    "timestamp":                   "93",
    "time without time zone":      "92",   # SQL_TYPE_TIME
    "time with time zone":         "92",
    "time":                        "92",
    "interval":                    "12",   # no ODBC equivalent — treat as varchar
    # Text types
    "character varying":           "12",   # SQL_VARCHAR
    "varchar":                     "12",
    "text":                        "12",
    "character":                   "1",    # SQL_CHAR
    "char":                        "1",
    "bpchar":                      "1",
    "name":                        "12",
    # Other
    "uuid":                        "12",
    "json":                        "12",
    "jsonb":                       "12",
    "bytea":                       "12",
    "xml":                         "12",
    "oid":                         "4",
    "cidr":                        "12",
    "inet":                        "12",
    "macaddr":                     "12",
    "tsvector":                    "12",
    "tsquery":                     "12",
    "point":                       "12",
    "line":                        "12",
    "lseg":                        "12",
    "path":                        "12",
    "polygon":                     "12",
    "circle":                      "12",
    "bit":                         "12",
    "bit varying":                 "12",
    "varbit":                      "12",
}


def _pg_to_odbc_remote_type(pg_type: str) -> Optional[str]:
    """Return the ODBC remote-type code for a given PostgreSQL data_type, or None if unknown."""
    pg = pg_type.lower().strip()
    code = _PG_TO_ODBC_REMOTE_TYPE.get(pg)
    if code:
        return code
    if "timestamp" in pg:
        return "93"
    if "time" in pg:
        return "92"
    if "char" in pg or "text" in pg or "varying" in pg:
        return "12"
    if "int" in pg:
        return "4"
    if "float" in pg or "double" in pg or "real" in pg or "numeric" in pg or "decimal" in pg:
        return "8"
    if pg.startswith("_") or "[]" in pg:  # PostgreSQL array types
        return "12"
    return None


_TABLEAU_TYPE_TO_PG_CAST: Dict[str, str] = {
    "integer":  "bigint",
    "real":     "double precision",
    "boolean":  "boolean",
    "date":     "date",
    "datetime": "timestamp",
}

# Regex patterns used to guard casts — only rows that match get cast, others become NULL.
# This handles any non-castable text value (empty strings, "EDP User", etc.)
_PG_CAST_GUARD: Dict[str, str] = {
    "bigint":           r"^-?[0-9]+$",
    "integer":          r"^-?[0-9]+$",
    "smallint":         r"^-?[0-9]+$",
    "double precision": r"^-?[0-9]*\.?[0-9]+([eE][+-]?[0-9]+)?$",
    "real":             r"^-?[0-9]*\.?[0-9]+([eE][+-]?[0-9]+)?$",
    "numeric":          r"^-?[0-9]*\.?[0-9]+$",
    "boolean":          r"^(?i)(true|false|t|f|yes|no|1|0)$",
    "date":             r"^\d{4}-\d{2}-\d{2}$",
    "timestamp":        r"^\d{4}-\d{2}-\d{2}[ T]",
}


def _safe_cast_expr(col: str, pg_cast: str) -> str:
    """
    Return a PostgreSQL expression that safely casts a text column to pg_cast.
    Uses a regex guard so any non-castable value (empty string, free text, etc.)
    becomes NULL rather than raising "invalid input syntax for type X".
    """
    quoted = f'"{col}"'
    guard  = _PG_CAST_GUARD.get(pg_cast)
    if guard:
        # Escape backslashes for Python f-string, but keep as single-quoted PG string
        pg_pattern = guard.replace("\\", "\\\\")
        return (
            f"CASE WHEN {quoted} ~ '{pg_pattern}' "
            f"THEN {quoted}::{pg_cast} ELSE NULL END AS {quoted}"
        )
    # Fallback for types without a guard (date, timestamp variants not covered above)
    return f"NULLIF({quoted}, '')::{pg_cast} AS {quoted}"


def _inject_nullif_casts(
    content: str,
    client_col_types: Dict[str, Dict[str, str]],
    ref_col_types: Dict[str, Dict[str, str]],
    table_mappings: List[Dict],
) -> Tuple[str, List[Dict]]:
    """
    For each table that has columns where the target DB type is text/varchar but the
    reference workbook declared them as numeric (integer/real), convert the table relation
    from a direct table reference to a custom SQL query that wraps those columns with
    NULLIF(col, '')::target_type.

    This fixes "invalid input syntax for type double precision" at the PostgreSQL level
    instead of relying on Tableau's metadata declarations.
    """
    issues = []
    n_tables = 0

    for mapping in table_mappings:
        if mapping.get("is_custom_sql"):
            continue
        new_table  = mapping.get("new_table", "")
        old_table  = mapping.get("old_table", "")
        new_schema = mapping.get("new_schema", "")
        if not (new_table and new_schema):
            continue

        db_cols  = client_col_types.get(new_table, {})
        ref_cols = ref_col_types.get(old_table, {})
        if not db_cols:
            continue

        # Find columns that are text in DB but numeric in the reference
        cast_cols: Dict[str, str] = {}  # col_name → pg cast type
        for col_name, pg_type in db_cols.items():
            db_tableau = _pg_to_tableau_type(pg_type)
            if db_tableau != "string":
                continue
            ref_type = ref_cols.get(col_name, "string")
            pg_cast  = _TABLEAU_TYPE_TO_PG_CAST.get(ref_type)
            if pg_cast:
                cast_cols[col_name] = pg_cast

        if not cast_cols:
            continue

        # Build SELECT: all columns from DB explicitly — cast mismatched ones, pass rest through.
        # Using the explicit list avoids duplicate column names (no SELECT *).
        col_list = []
        for col_name in db_cols:
            pg_cast = cast_cols.get(col_name)
            col_list.append(
                _safe_cast_expr(col_name, pg_cast) if pg_cast else f'"{col_name}"'
            )
        sql = "SELECT\n  " + ",\n  ".join(col_list) + f'\nFROM "{new_schema}"."{new_table}"'

        # Find cols referenced in workbook that are missing from our SELECT.
        # These are columns the reference workbook expected but which don't exist in
        # the target DB (schema drift). Prune their <cols><map> entries so Tableau
        # doesn't fail with "Invalid field formula" trying to resolve a missing column.
        cols_in_sql = set(db_cols.keys())
        cols_refs   = set(re.findall(
            r"\[" + re.escape(new_table) + r"\]\.\[([^\]]+)\]", content
        ))
        missing_cols = cols_refs - cols_in_sql

        # Replace the table relation in the XML.
        # Handles both self-closing (<relation ... />) and paired (<relation ...></relation>).
        # Preserves the `connection` attribute — Tableau requires it to route the SQL.
        pattern = re.compile(
            r"<relation\b(?=[^>]*\bname='" + re.escape(new_table) + r"')"
            r"(?=[^>]*\btype='table')"
            r"(?:[^>]*/>"
            r"|[^>]*>.*?</relation>)",
            re.DOTALL,
        )

        def _make_replacement(m: "re.Match") -> str:
            conn_m = re.search(r"\bconnection='([^']*)'", m.group(0))
            conn_attr = f" connection='{conn_m.group(1)}'" if conn_m else ""
            return (
                f"<relation name='{new_table}'{conn_attr} type='text'>"
                f"{sql}&#13;&#10;</relation>"
            )

        new_content, n = pattern.subn(_make_replacement, content)
        if n > 0:
            content = new_content
            # Prune <cols><map> entries for columns that don't exist in the target DB.
            # These are schema-drift columns (in reference but not in target); their map
            # entries would cause "Invalid field formula" since the custom SQL doesn't
            # include them (and they don't exist in the DB at all).
            if missing_cols:
                for mc in missing_cols:
                    # Remove <map ... value='[new_table].[mc]' ... /> entries
                    content = re.sub(
                        r"<map\b[^>]*value='\[" + re.escape(new_table) + r"\]\.\["
                        + re.escape(mc) + r"\]'[^/]*/>\s*",
                        "",
                        content,
                    )
            n_tables += 1
            issues.append({
                "type":     "nullif_cast_injected",
                "severity": "fixed",
                "title":    f"NULLIF casts injected for '{new_table}' ({len(cast_cols)} column(s))",
                "description": (
                    f"Converted '{new_table}' from a direct table reference to a custom SQL "
                    f"query. Columns {sorted(cast_cols)!r} are text in the target database "
                    f"but numeric in the reference workbook. NULLIF(..., '') is applied before "
                    f"casting so empty strings become NULL instead of causing a PostgreSQL "
                    f"'invalid input syntax for type double precision' error."
                ),
                "fix": "The datasource now uses a custom SQL query with safe type casts.",
            })

    return content, issues


def _fix_metadata_remote_types(
    content: str,
    client_col_types: Dict[str, Dict[str, str]],
) -> Tuple[str, List[Dict]]:
    """
    Update ONLY <remote-type> in metadata-records to match the target DB's actual column
    types.  This is the minimal safe change:

    - <remote-type> tells the ODBC/native driver what type to use when fetching the column.
      Setting it to 12 (varchar) for text columns prevents the driver from adding an
      explicit SQL CAST (e.g. text::float8) that fails on non-numeric values like "".

    - <local-type>, datatype=, and datatype-customized are intentionally left unchanged.
      Changing local-type or datatype to "string" breaks calculated fields that reference
      the column as a number (e.g. MAKEPOINT, SUM, arithmetic), causing "Invalid field
      formula" errors.  With remote-type=12 alone, Tableau fetches the column as text and
      performs the numeric conversion client-side (silently producing NULL for bad values).
    """
    issues = []
    n_fixed = 0

    # col → {table → remote_code}
    col_table_remote: Dict[str, Dict[str, str]] = {}
    for table_name, cols in client_col_types.items():
        for col_name, pg_type in cols.items():
            code = _pg_to_odbc_remote_type(pg_type)
            if code:
                col_table_remote.setdefault(col_name, {})[table_name] = code

    if not col_table_remote:
        return content, issues

    # Type-family sets: only allow remote-type changes within the same family.
    # Crossing from a numeric family → string family (e.g. real→varchar=12) makes
    # Tableau's query compiler reject arithmetic / MAKEPOINT / aggregation formulas
    # at compile time, producing "Invalid field formula" errors.
    _STRING_REMOTE  = {"1", "12", "129", "130"}   # SQL_CHAR / SQL_VARCHAR variants
    _NUMERIC_REMOTE = {"3", "4", "5", "6", "7", "8", "-5", "20", "131"}  # int/float/decimal
    _DATE_REMOTE    = {"91", "92", "93"}

    _LOCAL_TYPE_FAMILY: Dict[str, str] = {
        "string":   "string",
        "integer":  "numeric",
        "real":     "numeric",
        "boolean":  "boolean",
        "date":     "date",
        "datetime": "date",
    }
    _REMOTE_FAMILY: Dict[str, str] = {}
    for _c in _STRING_REMOTE:  _REMOTE_FAMILY[_c] = "string"
    for _c in _NUMERIC_REMOTE: _REMOTE_FAMILY[_c] = "numeric"
    for _c in _DATE_REMOTE:    _REMOTE_FAMILY[_c] = "date"

    def _patch_record(m: "re.Match") -> str:
        block = m.group(0)
        rn_m  = re.search(r"<remote-name>([^<]*)</remote-name>", block)
        rt_m  = re.search(r"(<remote-type>)(\d+)(</remote-type>)", block)
        lt_m  = re.search(r"<local-type>([^<]*)</local-type>", block)
        pn_m  = re.search(r"<parent-name>\[([^\]]*)\]</parent-name>", block)
        if not (rn_m and rt_m):
            return block

        col_name   = rn_m.group(1).strip()
        table_map  = col_table_remote.get(col_name)
        if not table_map:
            return block

        parent     = pn_m.group(1).strip() if pn_m else ""
        new_remote = table_map.get(parent) or next(iter(table_map.values()))

        if new_remote == rt_m.group(2):
            return block

        # Safety: don't cross type families (e.g. numeric→string).
        # Tableau's compiler rejects arithmetic/spatial formulas on varchar fields,
        # so changing a real/integer column's remote-type to 12 (varchar) causes
        # "Invalid field formula" even though local-type is unchanged.
        local_type  = lt_m.group(1).strip() if lt_m else ""
        local_fam   = _LOCAL_TYPE_FAMILY.get(local_type, "")
        new_fam     = _REMOTE_FAMILY.get(new_remote, "")
        if local_fam and new_fam and local_fam != new_fam:
            return block  # skip — would break formula compilation

        nonlocal n_fixed
        n_fixed += 1
        return (
            block[: rt_m.start()]
            + rt_m.group(1) + new_remote + rt_m.group(3)
            + block[rt_m.end():]
        )

    content = re.sub(
        r"<metadata-record class='column'>.*?</metadata-record>",
        _patch_record,
        content,
        flags=re.DOTALL,
    )

    if n_fixed > 0:
        issues.append({
            "type":        "remote_type_updated",
            "severity":    "fixed",
            "title":       f"Column remote-types updated ({n_fixed} metadata-record(s))",
            "description": (
                f"Updated <remote-type> in {n_fixed} metadata-record(s) to match actual "
                f"PostgreSQL column types. This prevents the ODBC driver from generating "
                f"SQL casts that fail on non-numeric text values."
            ),
            "fix": "Open the workbook and choose Data > Extract Data.",
        })

    return content, issues


def _report_type_preserved(type_fixes: List[Dict]) -> List[Dict]:
    """
    Log columns where the client DB type differs from the reference workbook's declared type.
    The TWB keeps the reference type — it is copied directly from the reference workbook XML.
    """
    issues = []
    for fix in type_fixes:
        if fix["old_type"] == fix["new_type"]:
            continue
        issues.append({
            "type":        "type_mismatch",
            "severity":    "fixed",
            "title":       f"Reference type preserved: [{fix['column']}]",
            "description": (
                f"'{fix['column']}' is declared as {fix['old_type']} in the reference workbook "
                f"but the new database returns it as {fix['new_type']}. "
                f"The generated workbook keeps the reference type ({fix['old_type']}) in the "
                f"datasource declarations — Tableau will cast the DB value automatically."
            ),
            "fix": f"Column datatype matches the reference dashboard ({fix['old_type']}).",
        })
    return issues


def generate_twbx(
    source_twbx: str,
    client_name: str,
    new_connection: Dict[str, Any],
    table_mappings: List[Dict[str, Any]],
    output_path: str,
    calc_overrides: Optional[List[Dict[str, Any]]] = None,
    type_fixes: Optional[List[Dict]] = None,
    removed_tables: Optional[List[str]] = None,
    join_overrides: Optional[List[Dict]] = None,
    client_col_types: Optional[Dict[str, Dict[str, str]]] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Generate a new .twbx with updated Postgres connection and table mappings.

    Returns:
        (output_path, repair_log)
    """
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(source_twbx, "r") as z:
            z.extractall(tmp)
            all_files = z.namelist()

        twb_files = [f for f in all_files if f.endswith(".twb")]
        if not twb_files:
            raise ValueError("No .twb file found in source workbook")

        twb_rel = twb_files[0]
        twb_abs = os.path.join(tmp, twb_rel)

        with open(twb_abs, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        # Parse reference column types from the source TWB BEFORE any modifications.
        # These are used after table renames to enforce matching <local-type> values.
        ref_col_types = parse_column_types_from_metadata(content)

        content, repair_log = _apply_all_modifications(
            content, new_connection, table_mappings, client_name,
            calc_overrides or [], type_fixes or [], ref_col_types,
            removed_tables=removed_tables or [],
            join_overrides=join_overrides or [],
            client_col_types=client_col_types or {},
        )

        # Strip <extract> blocks from the TWB — these define the old hyper extract
        # layer tied to the reference schema. Leaving them causes Tableau error
        # 2F8B7E6C even when the .hyper files are absent, because Tableau tries to
        # create a new extract using the stale extract-layer definitions.
        # Loop because extract blocks can be nested — non-greedy regex only removes
        # the innermost block per pass; repeat until none remain.
        prev = None
        while prev != content:
            prev = content
            content = re.sub(r'<extract\b[^>]*>.*?</extract>', '', content, flags=re.DOTALL)

        with open(twb_abs, "w", encoding="utf-8") as f:
            f.write(content)

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as out_zip:
            for rel_path in all_files:
                # Strip .hyper extract files — they belong to the reference workbook's
                # schema and cause Tableau error 2F8B7E6C when creating a new extract.
                # The generated workbook will open as a live connection; the user can
                # create a fresh extract in Tableau once the connection is confirmed.
                if rel_path.lower().endswith(".hyper"):
                    continue
                abs_path = os.path.join(tmp, rel_path)
                if os.path.isfile(abs_path):
                    out_zip.write(abs_path, rel_path)

        repair_log.append({
            "type":     "hyper_stripped",
            "severity": "info",
            "title":    "Extract files removed — workbook is now live connection",
            "description": (
                "The reference workbook contained .hyper extract file(s) tied to the original "
                "schema. These have been removed from the generated workbook to prevent "
                "Tableau error 2F8B7E6C ('Unable to create extract'). "
                "The workbook will open using a live Postgres connection."
            ),
            "fix": "In Tableau Desktop: Data menu → Extract Data to create a fresh extract from your connection.",
        })
    return output_path, repair_log


def _get_rel_children(join_block: str) -> List[str]:
    """
    Return the direct relation children of a join block string.
    Skips <clause> elements; handles both self-closing and nested relation tags.
    """
    ot_end = join_block.find(">")
    if ot_end == -1:
        return []
    ct_start = join_block.rfind("</relation>")
    if ct_start == -1:
        return []
    body = join_block[ot_end + 1 : ct_start]

    children: List[str] = []
    pos = 0
    rel_tag = re.compile(r"<(?:[\w.]*\.)?relation\b")

    while pos < len(body):
        # skip whitespace
        while pos < len(body) and body[pos] in " \t\n\r":
            pos += 1
        if pos >= len(body):
            break

        # skip <clause>…</clause>
        if body[pos:].startswith("<clause"):
            ce = body.find("</clause>", pos)
            pos = (ce + 9) if ce != -1 else len(body)
            continue

        if body[pos] != "<":
            pos += 1
            continue

        # must be a relation tag to count as a child
        if not rel_tag.match(body[pos:]):
            te = body.find(">", pos)
            pos = (te + 1) if te != -1 else len(body)
            continue

        te = body.find(">", pos)
        if te == -1:
            break

        if body[te - 1] == "/":
            # self-closing
            children.append(body[pos : te + 1])
            pos = te + 1
        else:
            # track depth to find the matching </relation>
            d  = 1
            ip = te + 1
            while d > 0 and ip < len(body):
                no = body.find("<relation", ip)
                nc = body.find("</relation>", ip)
                if nc == -1:
                    break
                if no != -1 and no < nc:
                    ite = body.find(">", no)
                    if ite != -1 and body[ite - 1] != "/":
                        d += 1
                    ip = (ite + 1) if ite != -1 else (no + 9)
                else:
                    d  -= 1
                    ip  = nc + 11
            children.append(body[pos:ip])
            pos = ip

    return children


def _collapse_invalid_joins(content: str) -> str:
    """
    Iteratively collapse any <relation type='join'> that has fewer than two
    direct relation children into its sole surviving child (or nothing if empty).

    A join with only one child is structurally invalid in Tableau and produces
    the F024F6FE 'Bad Connection' error — this fixes that.
    Works for both self-closing and nested surviving children.
    """
    join_re = re.compile(r"<relation\b[^>]*\btype='join'[^>]*>")

    for _ in range(40):          # generous upper bound for deeply nested trees
        changed = False
        for m in join_re.finditer(content):
            j_start = m.start()
            pos     = m.end()
            depth   = 1

            while depth > 0 and pos < len(content):
                no = content.find("<relation", pos)
                nc = content.find("</relation>", pos)
                if nc == -1:
                    break
                if no != -1 and no < nc:
                    te = content.find(">", no)
                    if te != -1 and content[te - 1] != "/":
                        depth += 1
                    pos = (te + 1) if te != -1 else (no + 9)
                else:
                    depth -= 1
                    pos    = nc + 11

            j_end    = pos
            block    = content[j_start:j_end]
            children = _get_rel_children(block)

            if len(children) == 1:
                content = content[:j_start] + children[0] + content[j_end:]
                changed = True
                break                   # restart — positions invalidated
            elif len(children) == 0:
                content = content[:j_start] + content[j_end:]
                changed = True
                break

        if not changed:
            break

    return content


def _remove_orphaned_metadata_records(content: str, table_name: str) -> str:
    """
    Remove <metadata-record> elements whose <parent-name> references the
    deleted table.  Handles both plain [TableName] and the object-model
    style [TableName (schema.table)_hash].
    """
    esc = re.escape(table_name)
    pattern = re.compile(
        r"[ \t]*<metadata-record\b[^>]*>(?:(?!</metadata-record>).)*?"
        rf"<parent-name>\[{esc}(?:\]|[\s(])"
        r"[^<]*</parent-name>(?:(?!</metadata-record>).)*?</metadata-record>\n?",
        re.DOTALL,
    )
    return pattern.sub("", content)


def _remove_cols_map_entries(content: str, table_name: str) -> str:
    """
    Remove <map> entries inside <cols> blocks whose value= attribute
    references the deleted table ([table_name].[col]).

    These dangling map entries are the primary cause of Tableau's
    F024F6FE 'Bad Connection' error after a table is removed.
    """
    esc = re.escape(table_name)
    # Handles both attribute orderings:  value='[T].[c]'  and  key='...' value='[T].[c]'
    pattern = re.compile(
        rf"[ \t]*<map\b(?=[^>]*\bvalue='\[{esc}\]\.[^']*')[^/]*/>\n?",
        re.DOTALL,
    )
    return pattern.sub("", content)


def _remove_object_graph_entries(content: str, table_name: str) -> str:
    """
    Remove all object-graph and extract-layer entries for a deleted table:

    1. <object> elements whose id= starts with table_name (Tableau uses
       "{table} ({schema}.{table})_{hash}" as the object id — the caption
       is a user-facing alias that may not match the table name).
    2. <relationship> elements whose first- or second-end-point references
       one of those object ids.
    3. Extract-layer <relation name="{table_name} ..."> self-closing tags
       that appear inside <relation type='collection'> or <properties
       context='extract'> blocks.
    """
    esc = re.escape(table_name)

    # ── 1. Collect all matching object ids (id starts with table_name) ──
    obj_ids = re.findall(
        rf"<object\b[^>]*\bid='({esc}[^']*)'",
        content,
    )

    # ── 2. Remove each matching <object …>…</object> block ───────────
    for obj_id in obj_ids:
        esc_id = re.escape(obj_id)
        content = re.sub(
            rf"[ \t]*<object\b(?=[^>]*\bid='{esc_id}')[^>]*>.*?</object>\n?",
            "",
            content,
            flags=re.DOTALL,
        )

    # Also remove by caption= in case the id doesn't match but caption does
    content = re.sub(
        rf"[ \t]*<object\b(?=[^>]*\bcaption='{esc}')[^>]*>.*?</object>\n?",
        "",
        content,
        flags=re.DOTALL,
    )

    # ── 3. Remove <relationship> elements referencing any of those ids ─
    all_ids = set(obj_ids)
    # Re-scan in case some objects were already removed — use both caption and id patterns
    all_ids.update(re.findall(rf"'{esc}[^']*'", content))  # broad scan for safety
    for obj_id in list(all_ids):
        if not obj_id.startswith(table_name):
            continue
        esc_id = re.escape(obj_id)
        content = re.sub(
            rf"[ \t]*<relationship\b[^>]*>(?:(?!</relationship>).)*?"
            rf"object-id='{esc_id}'(?:(?!</relationship>).)*?</relationship>\n?",
            "",
            content,
            flags=re.DOTALL,
        )

    # ── 4. Remove extract-layer <relation name="{table_name} …" …/> ──
    # These appear inside <relation type='collection'> and inside
    # <properties context='extract'> blocks inside <object> elements.
    content = re.sub(
        rf"[ \t]*<relation\b(?=[^>]*\bname='{esc}[^']*')[^>]*\btype='table'[^>]*/>\n?",
        "",
        content,
        flags=re.DOTALL,
    )

    return content


def _remove_table_relations(content: str, removed_tables: List[str]) -> Tuple[str, List[Dict]]:
    """
    Remove specified table/custom-SQL relations from all datasource connection
    blocks, clean up orphaned metadata-records, and repair any join nodes that
    are left with fewer than two children (which causes Tableau's F024F6FE error).
    """
    if not removed_tables:
        return content, []

    issues: List[Dict] = []
    for table_name in removed_tables:
        esc      = re.escape(table_name)
        original = content

        # Remove self-closing table relation — attribute order may vary
        for pat in [
            re.compile(rf"[ \t]*<(?:[\w.]*?\.)?relation\b(?=[^>]*\bname='{esc}')[^>]*\btype='table'[^>]*/>\n?", re.DOTALL),
            re.compile(rf"[ \t]*<(?:[\w.]*?\.)?relation\b(?=[^>]*\btype='table')[^>]*\bname='{esc}'[^>]*/>\n?", re.DOTALL),
        ]:
            content = pat.sub("", content)

        # Remove custom-SQL relation (type='text', has body)
        for pat in [
            re.compile(rf"[ \t]*<(?:[\w.]*?\.)?relation\b(?=[^>]*\bname='{esc}')[^>]*\btype='text'[^>]*>.*?</(?:[\w.]*?\.)?relation>\n?", re.DOTALL),
            re.compile(rf"[ \t]*<(?:[\w.]*?\.)?relation\b(?=[^>]*\btype='text')[^>]*\bname='{esc}'[^>]*>.*?</(?:[\w.]*?\.)?relation>\n?", re.DOTALL),
        ]:
            content = pat.sub("", content)

        if content != original:
            # Remove all orphaned references so Tableau can open the workbook
            content = _remove_cols_map_entries(content, table_name)
            content = _remove_object_graph_entries(content, table_name)
            content = _remove_orphaned_metadata_records(content, table_name)
            issues.append({
                "type": "table_removed",
                "severity": "fixed",
                "title": f"Table '{table_name}' removed from data model",
                "description": (
                    f"Removed relation, column mappings, and object-graph entries "
                    f"for '{table_name}' from all datasource connections."
                ),
                "fix": "Worksheets referencing this table's fields will show errors in Tableau Desktop.",
            })

    # Fix any join nodes left with < 2 children (self-closing or nested)
    content = _collapse_invalid_joins(content)

    return content, issues


def _escape_xml_join_expr(expr: str) -> str:
    """Escape a Tableau expression for use in a single-quoted XML attribute."""
    expr = expr.replace("&", "&amp;")
    expr = expr.replace("<", "&lt;")
    expr = expr.replace("'", "&apos;")
    return expr


def _direct_table_names(join_block: str) -> set:
    """
    Return the relation *name* attributes that are DIRECT children of a join block
    (type='table' or type='text'), skipping nested sub-joins/collections.

    This lets us distinguish  JOIN(A, B)  from  JOIN(JOIN(A,B), C) — the outer
    join indirectly references A and B but they are NOT direct children.
    """
    # Strip opening tag
    ot_end = join_block.find(">")
    if ot_end == -1:
        return set()
    # Strip closing </relation>
    ct_start = join_block.rfind("</relation>")
    body = join_block[ot_end + 1 : ct_start if ct_start != -1 else len(join_block)]

    names: set = set()
    pos = 0
    while pos < len(body):
        while pos < len(body) and body[pos] in " \t\n\r":
            pos += 1
        if pos >= len(body):
            break
        # skip <clause>
        if body[pos:].startswith("<clause"):
            ce = body.find("</clause>", pos)
            pos = (ce + 9) if ce != -1 else len(body)
            continue
        if body[pos] != "<":
            pos += 1
            continue
        if not re.match(r"<(?:[\w.]*\.)?relation\b", body[pos:]):
            te = body.find(">", pos)
            pos = (te + 1) if te != -1 else len(body)
            continue
        te = body.find(">", pos)
        if te == -1:
            break
        if body[te - 1] == "/":
            # self-closing direct child — grab its name if it's a table/text
            tag_txt = body[pos : te + 1]
            type_m  = re.search(r"\btype='([^']+)'", tag_txt)
            name_m  = re.search(r"\bname='([^']+)'", tag_txt)
            if type_m and type_m.group(1) in ("table", "text") and name_m:
                names.add(name_m.group(1))
            pos = te + 1
        else:
            # non-self-closing child (nested join/collection) — skip entirely
            d, ip = 1, te + 1
            while d > 0 and ip < len(body):
                no = body.find("<relation", ip)
                nc = body.find("</relation>", ip)
                if nc == -1:
                    break
                if no != -1 and no < nc:
                    ite = body.find(">", no)
                    if ite != -1 and body[ite - 1] != "/":
                        d += 1
                    ip = (ite + 1) if ite != -1 else no + 9
                else:
                    d  -= 1
                    ip  = nc + 11
            pos = ip
    return names


def _find_direct_clause(join_block: str) -> Optional[Tuple[int, int]]:
    """
    Return the (start, end) byte range of the <clause> that is a DIRECT child of
    this join block (i.e. not nested inside an inner sub-join).

    In Tableau's binary join tree the structure is:
        <relation join='...' type='join'>
          <relation .../>          ← left side (table or nested join)
          <relation name='T' ...>  ← right side table
          <clause type='join'>...</clause>  ← the clause we want
        </relation>

    clause_re.search(block) finds the FIRST <clause> in the whole block, which
    may be an inner join's clause. This function walks the body skipping nested
    <relation> children and returns the first <clause> reached at the top level.
    """
    ot_end = join_block.find(">")
    if ot_end == -1:
        return None
    ct_start = join_block.rfind("</relation>")
    body_offset = ot_end + 1
    body = join_block[body_offset : ct_start if ct_start != -1 else len(join_block)]

    pos = 0
    while pos < len(body):
        while pos < len(body) and body[pos] in " \t\n\r":
            pos += 1
        if pos >= len(body):
            break
        if body[pos] != "<":
            pos += 1
            continue
        if body[pos:].startswith("<clause"):
            ce = body.find("</clause>", pos)
            if ce == -1:
                return None
            return (body_offset + pos, body_offset + ce + 9)
        if re.match(r"<(?:[\w.]*\.)?relation\b", body[pos:]):
            te = body.find(">", pos)
            if te == -1:
                break
            if body[te - 1] == "/":
                pos = te + 1
            else:
                d, ip = 1, te + 1
                while d > 0 and ip < len(body):
                    no = body.find("<relation", ip)
                    nc = body.find("</relation>", ip)
                    if nc == -1:
                        break
                    if no != -1 and no < nc:
                        ite = body.find(">", no)
                        if ite != -1 and body[ite - 1] != "/":
                            d += 1
                        ip = (ite + 1) if ite != -1 else no + 9
                    else:
                        d -= 1
                        ip = nc + 11
                pos = ip
        else:
            te = body.find(">", pos)
            pos = (te + 1) if te != -1 else len(body)
    return None


def _replace_clause_in_join(
    content: str, left_table: str, right_table: str, new_clause_tpl: Optional[str],
    join_type: Optional[str] = None,
) -> Tuple[str, int]:
    """
    Replace the <clause> of every join whose DIRECT children include both
    left_table and right_table.

    Fixes three bugs in the previous version:
      1. Previously matched the OUTER join (which indirectly contained both
         tables) instead of the INNER join that directly joins them.
      2. Only replaced the first occurrence; the same join appears in both the
         live connection block and the object-graph — both must be updated.
      3. The new clause stripped the original <clause type='join'> attribute,
         which Tableau requires to parse the workbook correctly.
    """
    esc_lt = re.escape(left_table)
    esc_rt = re.escape(right_table)

    if not (re.search(rf"\bname='{esc_lt}'", content) and
            re.search(rf"\bname='{esc_rt}'", content)):
        return content, 0

    join_open_re = re.compile(r"<relation\b[^>]*\btype='join'[^>]*>")
    clause_re    = re.compile(r"<clause\b([^>]*)>(.*?)</clause>", re.DOTALL)

    # Collect ALL matching join blocks (process in reverse to preserve offsets)
    hits: List[tuple] = []   # (join_start, join_end, open_tag, block)

    for m in join_open_re.finditer(content):
        join_start = m.start()
        pos        = m.end()
        depth      = 1
        while depth > 0 and pos < len(content):
            no = content.find("<relation", pos)
            nc = content.find("</relation>", pos)
            if nc == -1:
                break
            if no != -1 and no < nc:
                te = content.find(">", no)
                if te != -1 and content[te - 1] != "/":
                    depth += 1
                pos = (te + 1) if te != -1 else (no + 9)
            else:
                depth -= 1
                pos    = nc + 11

        join_end = pos
        block    = content[join_start:join_end]

        # Match joins where this node directly joins the two tables.
        # Case 1 (innermost): both tables are direct self-closing children.
        # Case 2 (nested tree): one table is a direct child and the OTHER
        #   appears in the direct (outer-level) clause — e.g. JOIN(JOIN(...), T)
        #   where T is the right direct child and the left side is a sub-join.
        direct = _direct_table_names(block)
        both_direct = left_table in direct and right_table in direct
        direct_clause_range: Optional[Tuple[int, int]] = None
        if not both_direct and (left_table in direct or right_table in direct):
            direct_clause_range = _find_direct_clause(block)
            if direct_clause_range:
                cs, ce = direct_clause_range
                clause_text = block[cs:ce]
                if f"[{left_table}]" in clause_text and f"[{right_table}]" in clause_text:
                    hits.append((join_start, join_end, m.group(0), block, direct_clause_range))
                    continue
        if both_direct:
            hits.append((join_start, join_end, m.group(0), block, None))

    if not hits:
        return content, 0

    # Replace from end to start so earlier offsets stay valid
    for join_start, join_end, open_tag, block, direct_clause_range in reversed(hits):
        if new_clause_tpl is not None:
            if direct_clause_range:
                # Use the direct (outer-level) clause, not the first clause in the block
                cs, ce = direct_clause_range
                tag_end = block.find(">", cs)
                orig_attrs = block[cs + 7 : tag_end]  # after "<clause"
                new_clause = f"<clause{orig_attrs}>{new_clause_tpl}</clause>"
                new_block = block[:cs] + new_clause + block[ce:]
            else:
                cm = clause_re.search(block)
                if not cm:
                    continue
                orig_attrs = cm.group(1)
                new_clause = f"<clause{orig_attrs}>{new_clause_tpl}</clause>"
                new_block = block[: cm.start()] + new_clause + block[cm.end():]
        else:
            new_block = block

        # Update join= attribute on the opening tag if caller requested it
        if join_type:
            jt_norm = join_type.lower().strip()
            # Tableau XML enum: inner | left | right | full
            if jt_norm in ("full outer", "fullouter", "full_outer"):
                jt_norm = "full"
            new_tag   = re.sub(r"\bjoin='[^']*'", f"join='{jt_norm}'", open_tag)
            new_block = new_tag + new_block[len(open_tag):]

        content = content[:join_start] + new_block + content[join_end:]

    return content, len(hits)


def _apply_join_condition_overrides(content: str, join_overrides: List[Dict]) -> Tuple[str, List[Dict]]:
    """
    Apply join condition overrides.  Each override carries a full Tableau
    expression for each side (column reference OR calculation formula).
    """
    if not join_overrides:
        return content, []

    issues: List[Dict] = []
    for override in join_overrides:
        left_table  = override.get("left_table", "")
        right_table = override.get("right_table", "")
        left_expr   = override.get("left_expr", "")
        right_expr  = override.get("right_expr", "")

        # Back-compat: honour old left_col/right_col keys
        if not left_expr and override.get("left_col"):
            left_expr = f"[{left_table}].[{override['left_col']}]"
        if not right_expr and override.get("right_col"):
            right_expr = f"[{right_table}].[{override['right_col']}]"

        join_type = override.get("join_type") or None

        if not (left_table and right_table and left_expr and right_expr):
            # Join-type-only change: update the join= attribute without touching the clause
            if join_type and left_table and right_table:
                content, n = _replace_clause_in_join(content, left_table, right_table, None,
                                                      join_type=join_type)
                if n > 0:
                    issues.append({
                        "type": "join_type_updated",
                        "severity": "fixed",
                        "title": f"Join type updated: {left_table} ↔ {right_table}",
                        "description": f"Join type set to: {join_type}",
                        "fix": "The updated join type has been written into the generated workbook.",
                    })
            continue

        esc_l = _escape_xml_join_expr(left_expr)
        esc_r = _escape_xml_join_expr(right_expr)
        # Inner expression only — _replace_clause_in_join wraps it in
        # <clause{original_attrs}>…</clause> to preserve attributes like type='join'
        inner_expr = (
            f"<expression op='='>"
            f"<expression op='{esc_l}'/>"
            f"<expression op='{esc_r}'/>"
            f"</expression>"
        )

        original  = content

        # Primary: targeted replacement — finds DIRECT-child joins only,
        # replaces ALL occurrences (live + object-graph)
        content, n = _replace_clause_in_join(content, left_table, right_table, inner_expr,
                                              join_type=join_type)

        # Fallback: global pattern replacement (handles flat collection datasources)
        if n == 0:
            content = re.sub(
                rf"op='\[{re.escape(left_table)}\]\.\[[^\]]*\]'",
                f"op='{esc_l}'",
                content,
            )
            content = re.sub(
                rf"op='\[{re.escape(right_table)}\]\.\[[^\]]*\]'",
                f"op='{esc_r}'",
                content,
            )
            n = 0 if content == original else 1

        if n > 0:
            l_lbl = left_expr[:50]  + ("…" if len(left_expr)  > 50 else "")
            r_lbl = right_expr[:50] + ("…" if len(right_expr) > 50 else "")
            issues.append({
                "type": "join_condition_updated",
                "severity": "fixed",
                "title": f"Join condition updated: {left_table} ↔ {right_table}",
                "description": f"Clause set to: {l_lbl} = {r_lbl}",
                "fix": "The updated join condition has been written into the generated workbook.",
            })

    return content, issues


def _apply_all_modifications(
    content: str,
    new_conn: Dict[str, Any],
    table_mappings: List[Dict[str, Any]],
    client_name: str,
    calc_overrides: List[Dict[str, Any]] = [],
    type_fixes: Optional[List[Dict]] = None,
    ref_col_types: Optional[Dict[str, Dict[str, str]]] = None,
    removed_tables: Optional[List[str]] = None,
    join_overrides: Optional[List[Dict]] = None,
    client_col_types: Optional[Dict[str, Dict[str, str]]] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    """Apply all modifications and return (content, repair_log)."""

    repair_log: List[Dict[str, Any]] = []
    replaced_servers: set = set()
    sql_schema_replacements: Dict[str, str] = {}

    for mapping in table_mappings:
        old_conn   = mapping.get("old_connection", {})
        old_server = old_conn.get("server", "")

        if old_server and old_server not in replaced_servers:
            replaced_servers.add(old_server)
            content = _replace_postgres_connections(content, old_conn, new_conn)
            content = content.replace(
                f"caption='{old_server}'",
                f"caption='{new_conn.get('host', old_server)}'",
            )

        is_custom_sql = mapping.get("is_custom_sql", False)
        sql_override  = mapping.get("custom_sql_override", None)

        if is_custom_sql:
            relation_name = mapping.get("old_table", "")
            old_schema    = mapping.get("old_schema", "")
            new_schema    = mapping.get("new_schema", "")

            if sql_override and sql_override.strip():
                content, _sql_issues = _replace_custom_sql_body(content, relation_name, sql_override.strip())
                repair_log.extend(_sql_issues)

            # Always register so the catch-all pass fixes duplicate XML blocks
            # (Tableau stores each custom SQL relation twice: live + extract def)
            if old_schema and new_schema:
                sql_schema_replacements[old_schema] = new_schema
        else:
            old_ref = f"table='[{mapping['old_schema']}].[{mapping['old_table']}]'"
            new_ref = f"table='[{mapping['new_schema']}].[{mapping['new_table']}]'"
            content = content.replace(old_ref, new_ref)

            old_cap = (f"{mapping['old_table']} ({mapping['old_schema']}.{mapping['old_table']})"
                       f" ({mapping['old_schema']})")
            new_cap = (f"{mapping['new_table']} ({mapping['new_schema']}.{mapping['new_table']})"
                       f" ({mapping['new_schema']})")
            content = content.replace(old_cap, new_cap)

            old_cap_plus = (f"{mapping['old_table']} ({mapping['old_schema']}.{mapping['old_table']})"
                            f"+ ({mapping['old_schema']})")
            new_cap_plus = (f"{mapping['new_table']} ({mapping['new_schema']}.{mapping['new_table']})"
                            f"+ ({mapping['new_schema']})")
            content = content.replace(old_cap_plus, new_cap_plus)

    # Catch-all: fix any connections from unmapped datasources
    content, conn_issues = _replace_remaining_postgres_connections(content, replaced_servers, new_conn)
    repair_log.extend(conn_issues)

    # Replace old-schema in custom SQL bodies (catches duplicate XML blocks)
    if sql_schema_replacements:
        content, sql_issues = _replace_schema_in_custom_sql(content, sql_schema_replacements)
        repair_log.extend(sql_issues)

    # Replace old-schema in <object-id> elements and internal column name references
    # (e.g. [__tableau_internal_object_id__].[table (old_schema.table)_hash]).
    # Must cover ALL mappings, not just custom SQL, because these identifiers appear
    # for every table in Object-Model workbooks and a stale schema causes
    # "Invalid field formula" and type-resolution failures.
    all_schema_changes: Dict[str, str] = {}
    for _m in table_mappings:
        _old_s = _m.get("old_schema", "")
        _new_s = _m.get("new_schema", "")
        if _old_s and _new_s and _old_s != _new_s:
            all_schema_changes[_old_s] = _new_s
    oid_schema_map = {**all_schema_changes, **sql_schema_replacements}
    if oid_schema_map:
        content, oid_issues = _replace_schema_in_object_ids(content, oid_schema_map)
        repair_log.extend(oid_issues)

    if calc_overrides:
        content = _apply_calc_formula_overrides(content, calc_overrides)

    content = re.sub(r"xml:base='[^']*'", "xml:base=''", content)
    content = re.sub(r"<repository-location[^/]*/>\s*", "", content, flags=re.DOTALL)

    # Enforce reference column types in metadata-records:
    #   1. Update <parent-name> to use new table names (so Tableau can find the records).
    #   2. Set <local-type> to the reference workbook's declared type for every column.
    # This must happen after all table-rename substitutions above.
    if ref_col_types:
        content, col_type_issues = _enforce_reference_column_types(
            content, ref_col_types, table_mappings
        )
        repair_log.extend(col_type_issues)

        # Mark all physical datasource columns as datatype-customized so Tableau
        # honours the reference-declared datatype instead of overriding it with
        # whatever the live database returns for that column.
        content, n_customized = _mark_datasource_columns_customized(content, ref_col_types)
        if n_customized > 0:
            repair_log.append({
                "type":        "datatype_customized",
                "severity":    "fixed",
                "title":       f"Field types locked to reference workbook ({n_customized} field(s))",
                "description": (
                    f"Added datatype-customized='true' to {n_customized} field declaration(s). "
                    f"Without this attribute Tableau overrides the declared type with the live "
                    f"database type — this fix prevents that override."
                ),
                "fix": "Field datatypes now match the reference workbook regardless of the live DB schema.",
            })

    # Inject NULLIF casts at the SQL level for columns that are text in the target DB
    # but numeric in the reference. This is the primary fix for "invalid input syntax
    # for type double precision" — the cast is handled cleanly by PostgreSQL with
    # NULLIF so empty strings become NULL instead of causing a type error.
    if client_col_types and ref_col_types:
        content, nullif_issues = _inject_nullif_casts(
            content, client_col_types, ref_col_types, table_mappings
        )
        repair_log.extend(nullif_issues)

    # Update remote-type in metadata-records to match the target DB's actual column types.
    # Uses client_col_types (raw DB schema) as ground truth — avoids the intermediate
    # type_fixes chain that was silently failing when XML parsing returned empty dicts.
    if client_col_types:
        content, remote_type_issues = _fix_metadata_remote_types(content, client_col_types)
        repair_log.extend(remote_type_issues)
    if type_fixes:
        type_issues = _report_type_preserved(type_fixes)
        repair_log.extend(type_issues)

    # Strip MAKEPOINT/MAKELINE spatial fields — they cause error 2F8B7E6C on extract.
    # Done before geo-type fix since the columns may be gone after this step.
    content, spatial_issues = _strip_spatial_calc_fields(content)
    repair_log.extend(spatial_issues)

    # Fix remaining lat/lon columns typed as string → real (for any other spatial usage).
    content, geo_issues = _fix_geo_column_types(content)
    repair_log.extend(geo_issues)

    # Remove tables explicitly excluded from the data model
    if removed_tables:
        content, removal_issues = _remove_table_relations(content, removed_tables)
        repair_log.extend(removal_issues)

    # Apply join condition overrides
    if join_overrides:
        content, join_issues = _apply_join_condition_overrides(content, join_overrides)
        repair_log.extend(join_issues)

    # Strip RAWSQL / live-only calculated fields so extract creation succeeds
    content, rawsql_issues, bad_names = _scan_extract_incompatible_fields(content)
    if bad_names:
        content = _strip_columns_by_name(content, bad_names)
    repair_log.extend(rawsql_issues)

    # Post-generation scan: detect anything still wrong and report it
    scan_issues = _scan_for_remaining_issues(content, oid_schema_map, new_conn)
    repair_log.extend(scan_issues)

    return content, repair_log


# ─────────────────────────────────────────────────────────────────────────────
# Connection replacement
# ─────────────────────────────────────────────────────────────────────────────

def _replace_postgres_connections(content: str, old_conn: Dict, new_conn: Dict) -> str:
    old_server = old_conn.get("server", "")

    def replace_attrs(m: re.Match) -> str:
        tag = m.group(0)
        if old_server and f"server='{old_server}'" not in tag:
            return tag
        new_host = new_conn.get("host", "")
        new_db   = new_conn.get("database", "")
        new_user = new_conn.get("username", "")
        new_port = str(new_conn.get("port", 5432))
        new_ssl  = new_conn.get("sslmode", "require")
        if new_host:
            tag = re.sub(r"server='[^']*'",   f"server='{new_host}'",  tag)
        if new_db:
            tag = re.sub(r"dbname='[^']*'",   f"dbname='{new_db}'",    tag)
        if new_user:
            tag = re.sub(r"username='[^']*'", f"username='{new_user}'", tag)
        tag = re.sub(r"port='[^']*'",    f"port='{new_port}'",   tag)
        tag = re.sub(r"sslmode='[^']*'", f"sslmode='{new_ssl}'", tag)
        new_pass = new_conn.get("password", "")
        if new_pass:
            escaped_pass = _escape_conn_attr(new_pass)
            if "password='" in tag:
                tag = re.sub(r"password='[^']*'", f"password='{escaped_pass}'", tag)
            else:
                tag = re.sub(r"\s*/>$", f" password='{escaped_pass}'/>", tag)
        return tag

    # Match any SQL-compatible connector class, not just postgres
    pattern = re.compile(
        r"<connection\s[^>]*class='(?:postgres|kyvos|sqlserver|mysql|redshift|snowflake|databricks|oracle|teradata)'[^>]*/>"
    )
    # Also rewrite the class to postgres for the new connection
    def replace_and_reclass(m: re.Match) -> str:
        tag = replace_attrs(m)
        tag = re.sub(r"class='[^']*'", "class='postgres'", tag)
        # Remove kyvos/non-postgres-specific attributes that don't belong in a postgres tag
        tag = re.sub(r"\s+(?:service|v-krb\w*|authentication-type|odbc-connect-string-extras)='[^']*'", "", tag)
        return tag
    return pattern.sub(replace_and_reclass, content)


def _replace_remaining_postgres_connections(
    content: str, already_replaced: set, new_conn: Dict
) -> Tuple[str, List[Dict]]:
    issues: List[Dict] = []
    new_host = new_conn.get("host", "")
    if not new_host:
        return content, issues

    new_db   = new_conn.get("database", "")
    new_user = new_conn.get("username", "")
    new_port = str(new_conn.get("port", 5432))
    new_ssl  = new_conn.get("sslmode", "require")
    new_pass = new_conn.get("password", "")
    fixed_servers: set = set()

    def replace_attrs(m: re.Match) -> str:
        tag = m.group(0)
        srv_match = re.search(r"server='([^']*)'", tag)
        if not srv_match:
            return tag
        old_server = srv_match.group(1)
        if old_server in already_replaced or old_server == new_host:
            return tag
        fixed_servers.add(old_server)
        tag = re.sub(r"server='[^']*'",   f"server='{new_host}'",  tag)
        if new_db:
            tag = re.sub(r"dbname='[^']*'",   f"dbname='{new_db}'",   tag)
        if new_user:
            tag = re.sub(r"username='[^']*'", f"username='{new_user}'", tag)
        tag = re.sub(r"port='[^']*'",     f"port='{new_port}'",   tag)
        tag = re.sub(r"sslmode='[^']*'",  f"sslmode='{new_ssl}'", tag)
        if new_pass:
            ep = _escape_conn_attr(new_pass)
            if "password='" in tag:
                tag = re.sub(r"password='[^']*'", f"password='{ep}'", tag)
            else:
                tag = re.sub(r"\s*/>$", f" password='{ep}'/>", tag)
        return tag

    pattern = re.compile(
        r"<connection\s[^>]*class='(?:postgres|kyvos|sqlserver|mysql|redshift|snowflake|databricks|oracle|teradata)'[^>]*/>"
    )
    def replace_and_reclass(m: re.Match) -> str:
        tag = replace_attrs(m)
        tag = re.sub(r"class='[^']*'", "class='postgres'", tag)
        tag = re.sub(r"\s+(?:service|v-krb\w*|authentication-type|odbc-connect-string-extras)='[^']*'", "", tag)
        return tag
    content = pattern.sub(replace_and_reclass, content)

    for old_server in fixed_servers:
        content = content.replace(f"caption='{old_server}'", f"caption='{new_host}'")
        issues.append({
            "type":         "connection",
            "severity":     "fixed",
            "title":        "Unmapped datasource connection updated",
            "description":  f"Server '{old_server}' was still referenced by a datasource whose tables were not mapped.",
            "fix":          f"Connection automatically updated to '{new_host}' with database '{new_db}'.",
        })

    return content, issues


# ─────────────────────────────────────────────────────────────────────────────
# Custom SQL replacement
# ─────────────────────────────────────────────────────────────────────────────


def _tableau_operator_escape(sql: str) -> str:
    """
    Convert standard SQL comparison operators to Tableau's double-operator
    escaping (<= → <<=, >= → >>=, < → <<, > → >>) used inside CDATA blocks.
    Tableau's custom SQL scanner treats <word> as a parameter reference, so
    single < must be doubled. Normalise first to avoid double-escaping.
    """
    # Normalise any existing Tableau escaping back to plain operators
    sql = sql.replace("<<=", "\x00LE\x00").replace(">>=", "\x00GE\x00")
    sql = re.sub(r'<<(?!=)', "\x00LT\x00", sql)
    sql = re.sub(r'>>(?!=)', "\x00GT\x00", sql)
    sql = sql.replace("\x00LE\x00", "<=").replace("\x00GE\x00", ">=")
    sql = sql.replace("\x00LT\x00", "<").replace("\x00GT\x00", ">")
    # Apply Tableau escaping: must handle <= before <, and >= before >
    sql = sql.replace("<=", "<<=").replace(">=", ">>=")
    sql = re.sub(r'(?<!<)<(?![<=])', '<<', sql)
    sql = re.sub(r'(?<!>)>(?![>=])', '>>', sql)
    return sql


def _replace_custom_sql_body(content: str, relation_name: str, new_sql: str) -> Tuple[str, List[Dict]]:
    name_pat = re.escape(relation_name)
    pattern  = re.compile(
        rf"(<relation\b[^>]*\bname='{name_pat}'[^>]*\btype='text'[^>]*>)(.*?)(</relation>)",
        re.DOTALL,
    )
    issues: List[Dict] = []

    def _make_body(sql: str) -> str:
        escaped = _tableau_operator_escape(sql)
        safe    = escaped.replace("]]>", "]]]]><![CDATA[>")
        return f"<![CDATA[{safe}]]>"

    orig_body: List[str] = []

    def _replace(m: re.Match) -> str:
        orig_body.append(m.group(2))
        return m.group(1) + _make_body(new_sql) + m.group(3)

    new_content = pattern.sub(_replace, content)

    # Warn when the override is significantly shorter than the original — a common
    # indicator that SELECT columns were accidentally omitted (e.g. e.activity_skey).
    if orig_body:
        orig_fields = set(re.findall(r'\b(\w+)\b', orig_body[0]))
        new_fields  = set(re.findall(r'\b(\w+)\b', new_sql))
        dropped = orig_fields - new_fields - {'SELECT', 'FROM', 'WHERE', 'JOIN', 'ON', 'AS',
                                               'AND', 'OR', 'NOT', 'NULL', 'IS', 'IN',
                                               'LEFT', 'RIGHT', 'INNER', 'FULL', 'OUTER',
                                               'CASE', 'WHEN', 'THEN', 'ELSE', 'END',
                                               'GROUP', 'BY', 'ORDER', 'HAVING', 'DISTINCT'}
        # Only surface drops that look like column names (snake_case identifiers)
        col_drops = sorted(w for w in dropped if '_' in w and len(w) > 4)
        if col_drops:
            issues.append({
                "type": "custom_sql_override",
                "severity": "warning",
                "title": f"Custom SQL override for '{relation_name}' may be missing columns",
                "description": (
                    f"The following identifiers appear in the reference SQL but not in the "
                    f"override: {', '.join(col_drops[:20])}. "
                    f"If these are SELECT columns that should be included, add them to the override."
                ),
                "fix": "Review the custom SQL override and add any missing column references.",
            })

    return new_content, issues


def _replace_schema_in_custom_sql(
    content: str, schema_map: Dict[str, str]
) -> Tuple[str, List[Dict]]:
    issues: List[Dict] = []
    replaced_counts: Dict[str, int] = {k: 0 for k in schema_map}

    def replace_sql_block(m: re.Match) -> str:
        open_tag, sql, close_tag = m.group(1), m.group(2), m.group(3)
        for old_schema, new_schema in schema_map.items():
            new_sql, n = re.subn(rf"\b{re.escape(old_schema)}\.", f"{new_schema}.", sql)
            replaced_counts[old_schema] += n
            sql = new_sql
        return open_tag + sql + close_tag

    pattern = re.compile(
        r"(<relation\b[^>]*\btype='text'[^>]*>)(.*?)(</relation>)",
        re.DOTALL,
    )
    content = pattern.sub(replace_sql_block, content)

    for old_schema, count in replaced_counts.items():
        if count > 0:
            new_schema = schema_map[old_schema]
            issues.append({
                "type":        "custom_sql_schema",
                "severity":    "fixed",
                "title":       "Custom SQL schema references updated",
                "description": f"Found {count} occurrence(s) of schema '{old_schema}' inside custom SQL queries.",
                "fix":         f"All occurrences automatically replaced with '{new_schema}'.",
            })

    return content, issues


# ─────────────────────────────────────────────────────────────────────────────
# Object-ID replacement  (critical: wires calculated fields to datasource cols)
# ─────────────────────────────────────────────────────────────────────────────

def _replace_schema_in_object_ids(
    content: str, schema_map: Dict[str, str]
) -> Tuple[str, List[Dict]]:
    """
    Replace old-schema inside Tableau's internal field identifiers everywhere they appear.

    These identifiers follow the pattern  table_name (schema.table_name)_HASH  and appear in:
      - <object-id>[...]</object-id>          — links calculated fields to datasource cols
      - name='...' attributes on <relation>   — extract table relation names
      - table='[Extract].[...]' attributes    — extract table references
      - value='[...].[col]' on <map>          — column mapping entries

    Stale schema names in any of these locations cause Tableau to report
    "Invalid field formula" or "Unable to create extract" errors.
    """
    issues: List[Dict] = []

    for old_schema, new_schema in schema_map.items():
        # Match  (old_schema.  inside brackets/parens anywhere in the XML.
        # The pattern  (schema.  is unique to these internal identifiers.
        pattern = re.compile(rf"\({re.escape(old_schema)}\.")
        new_content, n = pattern.subn(f"({new_schema}.", content)
        if n > 0:
            content = new_content
            issues.append({
                "type":        "object_id_schema",
                "severity":    "fixed",
                "title":       "Field wiring identifiers updated",
                "description": (
                    f"Found {n} internal field identifier(s) still referencing schema '{old_schema}'. "
                    f"These appear in object-ids, relation names, extract table refs, and column maps — "
                    f"stale values cause 'Invalid field formula' and 'Unable to create extract' errors."
                ),
                "fix":         f"All {n} identifier(s) automatically updated to use schema '{new_schema}'.",
            })

    return content, issues


# ─────────────────────────────────────────────────────────────────────────────
# Post-generation scan  (detect anything still wrong after all fixes)
# ─────────────────────────────────────────────────────────────────────────────

def _scan_for_remaining_issues(
    content: str,
    schema_map: Dict[str, str],
    new_conn: Dict[str, Any],
) -> List[Dict]:
    issues: List[Dict] = []
    new_host = new_conn.get("host", "")
    new_db   = new_conn.get("database", "")

    # Check for old-schema still present anywhere in the XML
    for old_schema in schema_map:
        remaining = content.count(old_schema)
        if remaining > 0:
            # Identify where they still appear
            locations = []
            if f"table='[{old_schema}]." in content:
                locations.append("unmapped table references")
            if f"type='text'>" in content and old_schema in _extract_custom_sql(content):
                locations.append("custom SQL")
            loc_str = ", ".join(locations) if locations else "XML attributes"
            issues.append({
                "type":        "schema_remaining",
                "severity":    "warning",
                "title":       f"Schema '{old_schema}' still referenced ({remaining} occurrence(s))",
                "description": f"After all automatic replacements, '{old_schema}' still appears in: {loc_str}.",
                "fix":         (
                    "Go back to Step 2 and ensure all tables from this datasource are mapped. "
                    "Any unmapped table keeps its original schema reference."
                ),
            })

    # Check for old server still in connections (only if user changed server)
    if new_host:
        srv_pattern = re.compile(r"server='([^']*)'")
        remaining_servers = set()
        for m in srv_pattern.finditer(content):
            srv = m.group(1)
            if srv and srv != new_host:
                remaining_servers.add(srv)
        for srv in remaining_servers:
            issues.append({
                "type":        "server_remaining",
                "severity":    "warning",
                "title":       f"Old server '{srv}' still referenced",
                "description": (
                    f"A connection element still points to '{srv}' instead of '{new_host}'. "
                    f"This datasource may not have had any tables mapped."
                ),
                "fix":         "Map at least one table from this datasource in Step 2 so its connection is updated.",
            })

    return issues


def _strip_spatial_calc_fields(content: str) -> Tuple[str, List[Dict]]:
    """
    Remove MAKEPOINT / MAKELINE / BUFFER / DISTANCE calculated fields.

    These spatial functions fail with Tableau error 2F8B7E6C when creating
    an extract from a PostgreSQL federated datasource.  The fields are logged
    with their full formulas so the user can recreate them manually in Tableau
    Desktop after the extract is built.
    """
    SPATIAL_FNS = ['MAKEPOINT', 'MAKELINE', 'BUFFER', 'DISTANCE', 'MAKECIRCLE']

    col_full    = re.compile(r'<column\b([^>]*)>(.*?)</column>', re.DOTALL)
    calc_pat    = re.compile(r"formula='([^']*)'")
    cap_pat     = re.compile(r"caption='([^']*)'")
    name_pat    = re.compile(r"name='([^']*)'")

    stripped: List[Dict] = []
    bad_names: set = set()

    for m in col_full.finditer(content):
        attrs   = m.group(1)
        body    = m.group(2)
        formula_m = calc_pat.search(body)
        if not formula_m:
            continue
        formula = formula_m.group(1)
        upper   = formula.upper()
        hits    = [fn for fn in SPATIAL_FNS if fn + '(' in upper]
        if not hits:
            continue
        cap  = cap_pat.search(attrs)
        name = name_pat.search(attrs)
        label = (cap.group(1) if cap else None) or (name.group(1) if name else 'Unknown')
        if name:
            bad_names.add(name.group(1))
        stripped.append({
            "field":   label,
            "name":    name.group(1) if name else '',
            "formula": formula,
            "functions": hits,
        })

    if bad_names:
        content = _strip_columns_by_name(content, bad_names)

    issues = []
    if stripped:
        issues.append({
            "type":            "spatial_fields_stripped",
            "severity":        "warning",
            "title":           f"{len(stripped)} spatial calculated field(s) removed to allow extract creation",
            "description":     (
                "The following MAKEPOINT / MAKELINE fields were automatically removed. "
                "They work on a live connection but prevent extract creation (Tableau error 2F8B7E6C). "
                "You can recreate them manually in Tableau Desktop after building the extract."
            ),
            "fix":             "Recreate these fields in Tableau Desktop: Worksheet menu → Analysis → Create Calculated Field.",
            "stripped_fields": stripped,
        })

    return content, issues


def _fix_geo_column_types(content: str) -> Tuple[str, List[Dict]]:
    """
    Force latitude/longitude columns to datatype='real'.

    When a federated datasource carries these columns as datatype='string'
    (common with Custom SQL queries), MAKEPOINT/MAKELINE calculations fail
    and Tableau throws error 2F8B7E6C on extract creation.
    """
    GEO_KEYWORDS = ['latitude', 'longitude', 'longtitude', 'lat_code', 'lon_code', 'lng_code']
    issues: List[Dict] = []
    fixed: List[str] = []

    def _fix_col(m: re.Match) -> str:
        attrs = m.group(1)
        name_m = re.search(r"name='([^']*)'", attrs)
        if not name_m:
            return m.group(0)
        name_lower = name_m.group(1).lower().strip('[]')
        if not any(kw in name_lower for kw in GEO_KEYWORDS):
            return m.group(0)
        # Only fix string-typed geo columns
        if "datatype='string'" not in attrs and 'datatype="string"' not in attrs:
            return m.group(0)
        fixed.append(name_m.group(1))
        new_attrs = re.sub(r"datatype='string'", "datatype='real'", attrs)
        new_attrs = re.sub(r'datatype="string"', 'datatype="real"', new_attrs)
        return m.group(0).replace(attrs, new_attrs)

    # Match both self-closing and open <column> tags
    content = re.sub(r'<column\b([^>]*)/>', _fix_col, content)
    content = re.sub(r'<column\b([^>]*)>', _fix_col, content)

    if fixed:
        unique = sorted(set(fixed))
        issues.append({
            "type":     "geo_column_type_fix",
            "severity": "fixed",
            "title":    f"Fixed {len(unique)} lat/lon column(s) typed as string → real",
            "description": (
                f"The following geographic columns were defined as string in the datasource "
                f"but are required to be real numbers for MAKEPOINT/MAKELINE to work during "
                f"extract creation: {', '.join(unique[:10])}."
            ),
            "fix": "Column types corrected automatically in the generated workbook.",
        })

    return content, issues


def _scan_extract_incompatible_fields(content: str) -> List[Dict]:
    """
    Detect AND REMOVE calculated fields that would cause Tableau error 2F8B7E6C
    ("Invalid field formula due to limitations in the data source / Unable to create extract").

    Returns (cleaned_content, issues).  The cleaned content has the offending
    <column type='calc'> blocks stripped so extract creation succeeds.
    """
    # Functions that cause extract failure in federated Postgres datasources.
    # RAWSQL family: live-only passthrough — never works in extracts.
    # Spatial functions (MAKEPOINT/MAKELINE etc.): fail when lat/lon columns
    # have type conflicts in a federated source, confirmed by Tableau error 2F8B7E6C.
    LIVE_ONLY = [
        "RAWSQL", "RAWSQLAGG", "RAWSQLBOOL", "RAWSQLREAL", "RAWSQLINT",
        "MAKEPOINT", "MAKELINE", "MAKECIRCLE", "BUFFER", "DISTANCE",
    ]

    col_pattern  = re.compile(r"<column\b([^>]*)>(.*?)</column>", re.DOTALL)
    calc_pattern = re.compile(r"<calculation\b[^>]*\bformula='([^']*)'", re.DOTALL)
    cap_pattern  = re.compile(r"\bcaption='([^']*)'")
    name_pattern = re.compile(r"\bname='([^']*)'")

    bad_names  = set()   # internal [name] values to strip
    bad_fields = []

    for col_m in col_pattern.finditer(content):
        attrs = col_m.group(1)
        body  = col_m.group(2)
        if "type='calc'" not in attrs:
            continue
        calc_m = calc_pattern.search(body)
        if not calc_m:
            continue
        formula = calc_m.group(1)
        upper   = formula.upper()
        hits    = [fn for fn in LIVE_ONLY if fn in upper]
        if not hits:
            continue
        cap   = cap_pattern.search(attrs)
        name  = name_pattern.search(attrs)
        label = (cap.group(1) if cap else None) or (name.group(1) if name else "Unknown field")
        if name:
            bad_names.add(name.group(1))
        bad_fields.append({"field": label, "functions": hits, "formula": formula[:120]})

    issues = []
    if bad_fields:
        field_list = ", ".join(f['field'] for f in bad_fields)
        rawsql_fields   = [f for f in bad_fields if any(fn in ["RAWSQL","RAWSQLAGG","RAWSQLBOOL","RAWSQLREAL","RAWSQLINT"] for fn in f['functions'])]
        spatial_fields  = [f for f in bad_fields if any(fn in ["MAKEPOINT","MAKELINE","MAKECIRCLE","BUFFER","DISTANCE"] for fn in f['functions'])]
        issues.append({
            "type":     "removed_calc_fields",
            "severity": "warning",
            "title":    f"Removed {len(bad_fields)} calculated field(s) that block extract creation",
            "description": (
                f"The following calculated fields were automatically removed because they cause "
                f"Tableau error 2F8B7E6C ('Unable to create extract'): {field_list}."
            ),
            "fix": (
                "Recreate these fields in Tableau Desktop after opening the workbook: "
                "Analysis menu → Create Calculated Field. The original formulas are shown below."
            ),
            "affected_fields": bad_fields,
            "rawsql_count":  len(rawsql_fields),
            "spatial_count": len(spatial_fields),
        })

    return content, issues, bad_names


def _strip_columns_by_name(content: str, bad_names: set) -> str:
    """Remove <column> blocks whose name= attribute is in bad_names."""
    if not bad_names:
        return content
    def _remove(m: re.Match) -> str:
        attrs = m.group(1)
        name_m = re.search(r"\bname='([^']*)'", attrs)
        if name_m and name_m.group(1) in bad_names:
            return ""
        return m.group(0)
    return re.sub(r"<column\b([^>]*)>.*?</column>", _remove, content, flags=re.DOTALL)


def _extract_custom_sql(content: str) -> str:
    pattern = re.compile(r"<relation\b[^>]*\btype='text'[^>]*>(.*?)</relation>", re.DOTALL)
    return " ".join(m.group(1) for m in pattern.finditer(content))


# ─────────────────────────────────────────────────────────────────────────────
# Calculated field overrides
# ─────────────────────────────────────────────────────────────────────────────

def _apply_calc_formula_overrides(content: str, overrides: List[Dict[str, Any]]) -> str:
    for override in overrides:
        ds_name    = override.get("ds_name", "")
        field_name = override.get("field_name", "")
        new_formula = override.get("formula", "")
        if not field_name:
            continue
        content = _apply_single_calc_formula(content, ds_name, field_name, new_formula)
    return content


def _apply_single_calc_formula(content: str, ds_name: str, field_name: str, new_formula: str) -> str:
    escaped = _escape_formula_attr(new_formula)

    search_start, search_end = 0, len(content)
    if ds_name:
        ds_marker = f"name='{ds_name}'"
        ds_pos = content.find(ds_marker)
        if ds_pos != -1:
            blk_start = content.rfind("<datasource", 0, ds_pos)
            blk_end   = content.find("</datasource>", ds_pos)
            if blk_start != -1 and blk_end != -1:
                search_start = blk_start
                search_end   = blk_end + len("</datasource>")

    block = content[search_start:search_end]

    field_marker = f"name='{field_name}'"
    fpos = block.find(field_marker)
    if fpos == -1:
        return content

    col_start = block.rfind("<column", 0, fpos)
    if col_start == -1:
        return content

    col_end = block.find("</column>", fpos)
    if col_end == -1:
        return content
    col_end += len("</column>")

    col_block = block[col_start:col_end]
    if "type='calc'" not in col_block:
        return content

    calc_pat = re.compile(r"(<calculation\b[^>]*\bformula=')([^']*?)(')")
    new_col_block = calc_pat.sub(
        lambda m: m.group(1) + escaped + m.group(3),
        col_block,
        count=1,
    )

    new_block = block[:col_start] + new_col_block + block[col_end:]
    return content[:search_start] + new_block + content[search_end:]


# ─────────────────────────────────────────────────────────────────────────────
# Datasource column datatype-customized enforcement
# ─────────────────────────────────────────────────────────────────────────────

def _mark_datasource_columns_customized(
    content: str,
    ref_col_types: Dict[str, Dict[str, str]],
) -> Tuple[str, int]:
    """
    Add datatype-customized='true' to every datasource-level <column> element
    whose name matches a physical column in ref_col_types.

    Without this attribute Tableau ignores the declared datatype and re-infers
    the type from the live database connection, overriding the reference type
    even when <local-type> and <cast-to-local-type> in metadata-records are
    already correct.
    """
    flat_types: Dict[str, str] = {}
    for table_cols in ref_col_types.values():
        for col_name, col_type in table_cols.items():
            if col_name not in flat_types:
                flat_types[col_name] = col_type

    if not flat_types:
        return content, 0

    changed = 0

    def mark_tag(m: re.Match) -> str:
        nonlocal changed
        tag = m.group(0)
        name_m = re.search(r"\bname='\[([^\]]+)\]'", tag)
        if not name_m:
            return tag
        col_name = name_m.group(1)
        if col_name not in flat_types:
            return tag
        if "datatype-customized=" in tag:
            return tag
        new_tag = re.sub(
            r"(\bdatatype='[^']*')",
            r"\1 datatype-customized='true'",
            tag,
            count=1,
        )
        if new_tag != tag:
            changed += 1
        return new_tag

    pattern = re.compile(r"<column\b[^>]*\bdatatype='[^']*'[^>]*>")
    content = pattern.sub(mark_tag, content)
    return content, changed


# ─────────────────────────────────────────────────────────────────────────────
# Reference column-type enforcement
# ─────────────────────────────────────────────────────────────────────────────

def _enforce_reference_column_types(
    content: str,
    ref_col_types: Dict[str, Dict[str, str]],
    table_mappings: List[Dict],
) -> Tuple[str, List[Dict]]:
    """
    For every non-SQL table mapping ensure that metadata-records in the generated
    TWB XML have:
      1. <parent-name> updated from [old_table] to [new_table]  (so Tableau can
         resolve the records after a table rename instead of re-querying the DB).
      2. <local-type> set to the value declared in the reference workbook  (so
         field datatypes in the generated workbook exactly match the reference).
    """
    issues: List[Dict] = []
    total_parent_fixes = 0
    total_type_fixes = 0

    for mapping in table_mappings:
        if mapping.get("is_custom_sql"):
            continue
        old_table = mapping.get("old_table", "")
        new_table = mapping.get("new_table", "")
        if not old_table:
            continue

        ref_cols = ref_col_types.get(old_table, {})

        # Step 1 — update <parent-name> from old_table to new_table
        if old_table != new_table:
            old_pname = f"<parent-name>[{old_table}]</parent-name>"
            new_pname = f"<parent-name>[{new_table}]</parent-name>"
            n = content.count(old_pname)
            if n > 0:
                content = content.replace(old_pname, new_pname)
                total_parent_fixes += n

        # Step 2 — enforce <local-type> for every column we have a reference type for
        if ref_cols:
            content, n = _set_metadata_local_types(content, new_table, ref_cols)
            total_type_fixes += n

    if total_parent_fixes > 0:
        issues.append({
            "type":        "metadata_parent_updated",
            "severity":    "fixed",
            "title":       f"Metadata parent references updated ({total_parent_fixes})",
            "description": (
                f"Updated {total_parent_fixes} metadata-record <parent-name> element(s) from "
                f"old table names to new table names so Tableau can resolve column definitions "
                f"without re-querying the live database."
            ),
            "fix": "Metadata parent references now match the new table names.",
        })

    if total_type_fixes > 0:
        issues.append({
            "type":        "metadata_types_enforced",
            "severity":    "fixed",
            "title":       f"Field datatypes aligned with reference workbook ({total_type_fixes} column(s))",
            "description": (
                f"Enforced reference workbook <local-type> for {total_type_fixes} column(s) in "
                f"the generated workbook's metadata declarations. Field datatypes now exactly "
                f"match the reference workbook."
            ),
            "fix": "All field datatypes match the reference workbook.",
        })

    return content, issues


def _set_metadata_local_types(
    content: str,
    table_name: str,
    col_types: Dict[str, str],
) -> Tuple[str, int]:
    """
    For every <metadata-record class='column'> whose <parent-name> is [table_name],
    replace <local-type>…</local-type> with the reference workbook's declared type.
    Returns (updated_content, number_of_substitutions).
    """
    changed = 0

    def fix_record(m: re.Match) -> str:
        nonlocal changed
        block = m.group(0)

        pname_m = re.search(r"<parent-name>\[([^\]]*)\]</parent-name>", block)
        if not pname_m:
            return block
        pname_inner = pname_m.group(1)
        # Match both plain [table_name] and object-model [table_name (schema.table_name)_HASH]
        if pname_inner != table_name and not pname_inner.startswith(table_name + " ("):
            return block

        rname_m = re.search(r"<remote-name>([^<]*)</remote-name>", block)
        if not rname_m:
            return block

        col_name = rname_m.group(1).strip()
        ref_type = col_types.get(col_name)
        if ref_type is None:
            return block

        new_block, n = re.subn(
            r"<local-type>[^<]*</local-type>",
            f"<local-type>{ref_type}</local-type>",
            block,
        )
        changed += n

        # Ensure <cast-to-local-type>true</cast-to-local-type> is present so
        # Tableau casts the DB value to the reference-declared type instead of
        # overriding it with whatever the live database returns.
        if "<cast-to-local-type>" not in new_block:
            indent_m = re.search(r"(\s+)<local-type>", new_block)
            indent = indent_m.group(1) if indent_m else "            "
            new_block = re.sub(
                r"(<local-type>[^<]*</local-type>)",
                rf"\1\n{indent}<cast-to-local-type>true</cast-to-local-type>",
                new_block,
                count=1,
            )

        return new_block

    pattern = re.compile(
        r"<metadata-record[^>]*class='column'[^>]*>.*?</metadata-record>",
        re.DOTALL,
    )
    return pattern.sub(fix_record, content), changed


# ─────────────────────────────────────────────────────────────────────────────
# Escape helpers
# ─────────────────────────────────────────────────────────────────────────────

def _escape_formula_attr(formula: str) -> str:
    formula = formula.replace("&", "&amp;")
    formula = formula.replace("<", "&lt;")
    formula = formula.replace(">", "&gt;")
    formula = formula.replace("'", "&apos;")
    formula = formula.replace('"', "&quot;")
    formula = formula.replace("\n", "&#10;")
    formula = formula.replace("\r", "&#13;")
    return formula


def _escape_conn_attr(val: str) -> str:
    val = val.replace("&", "&amp;")
    val = val.replace("<", "&lt;")
    val = val.replace(">", "&gt;")
    val = val.replace("'", "&apos;")
    val = val.replace('"', "&quot;")
    return val
