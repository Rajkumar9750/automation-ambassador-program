"""
Azure AI Foundry (claude-sonnet-4-6) powered schema matching.
Parallelises all table-level calls for speed.
"""

import json
import re
import difflib
import httpx
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional

from anthropic import AnthropicFoundry

import os
AZURE_ENDPOINT   = os.environ["AZURE_FOUNDRY_ENDPOINT"]
AZURE_API_KEY    = os.environ["AZURE_FOUNDRY_API_KEY"]
DEPLOYMENT_NAME  = os.getenv("AZURE_DEPLOYMENT_NAME", "claude-sonnet-4-6")

MAX_TGT_TABLES   = 30   # max candidates sent per call
MAX_PARALLEL     = 5    # concurrent LLM calls


def _get_client():
    return AnthropicFoundry(
        api_key=AZURE_API_KEY,
        base_url=AZURE_ENDPOINT,
        http_client=httpx.Client(verify=False),
    )


def _name_sim(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _format_target(tbl: dict) -> str:
    cols = [f"    - {c['name']} ({c['data_type']})" for c in tbl.get("columns", [])]
    col_str = "\n".join(cols) if cols else "    (no columns)"
    return f'  {tbl["schema"]}.{tbl["name"]}  (≈{tbl.get("row_count",0):,} rows)\n{col_str}'


def _preselect(ref_table: dict, target_tables: List[dict]) -> List[dict]:
    if len(target_tables) <= MAX_TGT_TABLES:
        return target_tables
    return sorted(target_tables,
                  key=lambda t: _name_sim(ref_table["table"], t["name"]),
                  reverse=True)[:MAX_TGT_TABLES]


def _build_prompt(ref: dict, candidates: List[dict]) -> str:
    ref_name   = ref["table"]
    ref_schema = ref.get("schema", "")
    is_sql     = ref.get("is_custom_sql", False)
    ref_cols   = ref.get("columns", [])

    if is_sql:
        ref_block = f"  Type: Custom SQL\n  Name: {ref_name}\n  SQL: {ref.get('custom_sql','')[:200]}…"
    else:
        col_str = "\n".join(f"    - {c}" for c in ref_cols[:30]) if ref_cols \
                  else "    (column names not available)"
        ref_block = (f"  Schema: {ref_schema or '(unknown)'}\n"
                     f"  Table:  {ref_name}\n"
                     f"  Columns from workbook:\n{col_str}")

    cands = "\n\n".join(f"Candidate {i+1}:\n{_format_target(t)}"
                        for i, t in enumerate(candidates))

    return f"""You are a database schema mapping expert migrating a Tableau dashboard.

REFERENCE TABLE (from the Tableau workbook):
{ref_block}

TARGET DATABASE CANDIDATES:
{cands}

Find which candidate is the semantic equivalent of the reference table.
Consider name similarity (abbreviations like txn=transaction, cust=customer), column overlap, and data types.

Return ONLY valid JSON, no other text:
{{
  "matched_table":  "<table name or null>",
  "matched_schema": "<schema name or null>",
  "confidence":     "<high|medium|low|none>",
  "reasoning":      "<1-2 sentences>",
  "column_mappings": [
    {{"ref_col":"<workbook col>","ref_type":"<type>","target_col":"<matched col or null>","target_type":"<type or null>","confidence":"<high|medium|low|none>"}}
  ]
}}"""


def _parse(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                pass
    return {"matched_table": None, "matched_schema": None, "confidence": "none",
            "reasoning": "Could not parse response.", "column_mappings": []}


def _match_one(ref: dict, target_tables: List[dict]) -> dict:
    candidates = _preselect(ref, target_tables)
    prompt     = _build_prompt(ref, candidates)
    client     = _get_client()
    try:
        response = client.messages.create(
            model=DEPLOYMENT_NAME,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        text = next((b.text for b in response.content if hasattr(b, "text")), "")
        parsed = _parse(text)
    except Exception as e:
        parsed = {"matched_table": None, "matched_schema": None, "confidence": "none",
                  "reasoning": f"Error: {e}", "column_mappings": []}

    return {
        "ref_schema":    ref.get("schema", ""),
        "ref_table":     ref["table"],
        "is_custom_sql": ref.get("is_custom_sql", False),
        **parsed,
    }


def match_tables(
    workbook_tables: List[dict],
    target_tables:   List[dict],
    api_key:         str = "",          # ignored — Azure key is embedded
    on_progress:     Optional[callable] = None,
) -> List[dict]:
    """Parallel Claude calls — one per workbook table."""
    total   = len(workbook_tables)
    results = [None] * total
    done    = [0]

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as ex:
        futures = {
            ex.submit(_match_one, ref, target_tables): i
            for i, ref in enumerate(workbook_tables)
        }
        for future in as_completed(futures):
            i = futures[future]
            results[i] = future.result()
            done[0] += 1
            if on_progress:
                on_progress(
                    f'Matched "{workbook_tables[i]["table"]}"',
                    done[0], total,
                )

    return results


def to_dashboard_factory_export(results: List[dict], tgt_conn: dict) -> dict:
    mappings = []
    for r in results:
        if not r or r.get("confidence") == "none" or not r.get("matched_table"):
            continue
        mappings.append({
            "old_schema":          r["ref_schema"],
            "old_table":           r["ref_table"],
            "new_schema":          r.get("matched_schema") or "",
            "new_table":           r.get("matched_table") or "",
            "old_connection":      {},
            "is_custom_sql":       r.get("is_custom_sql", False),
            "custom_sql_override": None,
            "original_sql":        None,
        })
    col_index = {r["ref_table"]: {cm["ref_col"]: cm["target_col"]
                                   for cm in (r.get("column_mappings") or [])
                                   if cm.get("target_col")}
                 for r in results if r}
    return {
        "table_mappings":    mappings,
        "column_index":      col_index,
        "target_connection": tgt_conn,
        "mapping_count":     len(mappings),
        "skipped_count":     len(results) - len(mappings),
    }
