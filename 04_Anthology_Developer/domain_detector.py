"""
Detects dashboard domain using Azure AI Foundry (claude-sonnet-4-6).
Suggests the alias prefix to filter target DB tables.
"""

import json
import re
import httpx
from typing import List, Dict, Optional

from anthropic import AnthropicFoundry

AZURE_ENDPOINT  = "https://admv-mogidbp0-eastus2.services.ai.azure.com/anthropic/"
AZURE_API_KEY   = "${AZURE_FOUNDRY_API_KEY}"
DEPLOYMENT_NAME = "claude-sonnet-4-6"

DOMAIN_RULES = [
    (["fm", "facilities", "facility", "maintenance"],          "fm_",    "Facilities Management"),
    (["fin", "finance", "financial", "accounting", "payroll"], "fin_",   "Finance"),
    (["hr", "human resources", "workforce", "people"],         "hr_",    "Human Resources"),
    (["ops", "operations", "operational"],                     "ops_",   "Operations"),
    (["sales", "revenue", "crm", "pipeline"],                  "sales_", "Sales"),
    (["mkt", "marketing", "campaign"],                         "mkt_",   "Marketing"),
    (["it", "technology", "tech", "infra"],                    "it_",    "IT"),
    (["proj", "project", "portfolio"],                         "proj_",  "Project Management"),
    (["inv", "inventory", "warehouse", "supply"],              "inv_",   "Inventory"),
    (["cust", "customer", "client", "account"],                "cust_",  "Customer"),
]


def _rule_based(name: str, tables: List[str], ds: List[str]) -> Optional[dict]:
    combined = " ".join([name] + tables + ds).lower()
    for keywords, prefix, label in DOMAIN_RULES:
        for kw in keywords:
            if kw in combined:
                return {"domain": label, "alias_prefix": prefix,
                        "confidence": "medium",
                        "reasoning": f'Keyword "{kw}" found in workbook metadata.'}
    # infer from consistent table prefix
    prefixes = [t.split("_")[0].lower() for t in tables if "_" in t]
    if prefixes:
        top = max(set(prefixes), key=prefixes.count)
        if prefixes.count(top) >= max(1, len(prefixes) // 2):
            return {"domain": top.upper(), "alias_prefix": f"{top}_",
                    "confidence": "medium",
                    "reasoning": f'Most tables share prefix "{top}_".'}
    return None


def detect_domain(
    workbook_name: str,
    table_names:   List[str],
    ds_names:      List[str],
    api_key:       str = "",    # ignored — Azure key embedded
) -> dict:
    result = _rule_based(workbook_name, table_names, ds_names)
    if result:
        return result

    # LLM fallback
    try:
        client = AnthropicFoundry(
            api_key=AZURE_API_KEY,
            base_url=AZURE_ENDPOINT,
            http_client=httpx.Client(verify=False),
        )
        prompt = f"""Identify the business domain of this Tableau workbook.

Filename: {workbook_name}
Tables:   {', '.join(table_names[:20]) or '(none)'}
Sources:  {', '.join(ds_names[:10])   or '(none)'}

Common CBRE alias prefixes:
FM / Facilities → fm_   |  Finance → fin_   |  HR → hr_
Operations → ops_       |  Sales → sales_   |  IT → it_

Return ONLY JSON:
{{"domain":"<label>","alias_prefix":"<prefix_>","confidence":"<high|medium|low|none>","reasoning":"<one sentence>"}}"""

        response = client.messages.create(
            model=DEPLOYMENT_NAME,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = next((b.text for b in response.content if hasattr(b, "text")), "")
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            return json.loads(m.group())
    except Exception:
        pass

    return {"domain": "Unknown", "alias_prefix": "", "confidence": "none",
            "reasoning": "Could not detect domain automatically."}


def filter_target_tables(target_tables: List[Dict], alias_prefix: str) -> List[Dict]:
    if not alias_prefix:
        return target_tables
    pfx = alias_prefix.lower()
    filtered = [t for t in target_tables
                if t.get("schema", "").lower().startswith(pfx)
                or t.get("name",   "").lower().startswith(pfx)]
    return filtered if filtered else target_tables
