"""
table_selector.py
-----------------
Selects relevant DB tables for a user query using LLM.
Respects domain boundary passed from registry.
"""

import os
import re
import json
import logging
from typing import List

from groq import Groq

logger      = logging.getLogger("table_selector")
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
LLM_MODEL   = "llama-3.3-70b-versatile"

# Remove all old views:
ACTIVE_VIEWS = []  # CrewMachIN has no views

BACKUP_KEYWORDS = ["_bkp", "_backup", "_org", "_archive", "_Archive", "(1)"]

_TABLE_CACHE = None


# ─────────────────────────────────────────────
# 1. get_all_tables()
# ─────────────────────────────────────────────
def get_all_tables() -> List[str]:
    global _TABLE_CACHE

    if _TABLE_CACHE:
        print(f"   💾 Table cache hit → {len(_TABLE_CACHE)} tables/views loaded")
        return _TABLE_CACHE

    print("   🔌 Connecting to DB to fetch all tables and views...")

    try:
        from database.db import get_connection

        conn   = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT TABLE_NAME
            FROM   INFORMATION_SCHEMA.TABLES
            WHERE  TABLE_TYPE = 'BASE TABLE'
            ORDER  BY TABLE_NAME
        """)
        base_tables = [(row[0], "TABLE") for row in cursor.fetchall()]
        print(f"   📦 Base tables found in DB: {len(base_tables)}")

        views = [(name, "VIEW") for name in ACTIVE_VIEWS]
        print(f"   👁️  Active views added: {len(views)}")

        all_objects = base_tables + views
        table_hints = []

        for name, obj_type in all_objects:
            try:
                # FIXED: use 'name' not 'table'
                cursor.execute("""
                    SELECT TOP 5 COLUMN_NAME
                    FROM   INFORMATION_SCHEMA.COLUMNS
                    WHERE  TABLE_NAME = ?
                    ORDER  BY ORDINAL_POSITION
                """, (name,))

                cols     = [row[0] for row in cursor.fetchall()]
                cols_str = ", ".join(cols) if cols else "no columns"
                table_hints.append(f"{name} [{obj_type}] ({cols_str})")

            except Exception as col_exc:
                logger.warning("Could not fetch columns for %s: %s", name, col_exc)
                table_hints.append(f"{name} [{obj_type}]")

        cursor.close()
        conn.close()

        _TABLE_CACHE = table_hints
        print(f"   ✅ Cached {len(_TABLE_CACHE)} tables/views with column hints")
        return _TABLE_CACHE

    except Exception as exc:
        print(f"   ❌ Failed to fetch tables from DB: {exc}")
        return []


# ─────────────────────────────────────────────
# 2. Helpers
# ─────────────────────────────────────────────
def _extract_name(hint: str) -> str:
    return hint.split("[")[0].strip()


def _extract_json_array(raw: str) -> List[str]:
    if not raw or not raw.strip():
        return []
    try:
        parsed = json.loads(raw.strip())
        if isinstance(parsed, list):
            return [str(i) for i in parsed]
    except json.JSONDecodeError:
        pass
    match = re.search(r"\[.*?\]", raw, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group())
            if isinstance(parsed, list):
                return [str(i) for i in parsed]
        except json.JSONDecodeError:
            pass
    print("   ⚠️  Could not parse JSON array from LLM response")
    return []


def _filter_backup_tables(tables: List[str]) -> List[str]:
    filtered = [t for t in tables if not any(k.lower() in t.lower() for k in BACKUP_KEYWORDS)]
    if len(filtered) < len(tables):
        removed = [t for t in tables if t not in filtered]
        print(f"   🗑️  Backup tables removed: {removed}")
    return filtered if filtered else tables


# ─────────────────────────────────────────────
# 3. select_tables()
# ─────────────────────────────────────────────
def select_tables(query: str, allowed_tables: List[str] = None) -> List[str]:
    print("\n" + "─"*60)
    print("📌 STEP 4 — TABLE SELECTION")
    print("─"*60)
    print(f"   Question : {query}")

    if not query or not query.strip():
        print("   ⚠️  Empty query — returning []")
        return []

    all_tables = get_all_tables()

    # Apply domain boundary
    if allowed_tables:
        before = len(all_tables)
        all_tables = [
            t for t in all_tables
            if _extract_name(t) in allowed_tables
        ]
        print(f"   🔒 Domain boundary applied: {before} → {len(all_tables)} tables in scope")
        print(f"   📋 Allowed tables: {allowed_tables}")
    else:
        print(f"   🌐 No domain boundary → all {len(all_tables)} tables in scope")

    if not all_tables:
        print("   ❌ No tables in scope after boundary applied")
        return []

    tables_str = "\n".join(f"- {t}" for t in all_tables)

    print(f"   🤖 Calling LLM to pick relevant tables (max 3)...")

    system_prompt = (
    "You are an expert SQL analyst for Air India Express crew management system.\n\n"
    "Identify which database tables are needed to answer the user's question.\n\n"
    "STRICT RULES:\n"
    "1. Respond with ONLY a valid JSON array of table name strings.\n"
    "2. Every table MUST appear in the provided list.\n"
    "3. Do NOT invent table names.\n"
    "4. Return [] if no table is relevant.\n"
    "5. No explanation, no markdown — JSON array ONLY.\n"
    "6. Return MAXIMUM 3 tables.\n\n"
    "IMPORTANT HINTS:\n"
    "- For crew name/rank/base/status/fleet     → prefer 'Aix_BaseCrewInfo'\n"
    "- For personal info/gender/birthdate        → prefer 'AIX_CrewInfo'\n"
    "- For rank history queries                  → prefer 'AIX_CrewRanks'\n"
    "- For function/role history                 → prefer 'AIX_CrewFunctions'\n"
    "- For flight duty/roster/block hours        → prefer 'Aix_CrewRoster'\n"
    "- For statistics/daily hours                → prefer 'AIX_CrewRosterStatistics'\n"
    "- For payroll/designation queries           → prefer 'PayRoll_Designations'\n"
    "- JOIN key across all tables                → Aix_BaseCrewInfo.ID = AIX_CrewInfo.StaffNumber = Aix_CrewRoster.ID\n"
    "- NEVER use Aix_CrewRoster for personal crew info\n"
)

    user_prompt = (
        f"User question:\n{query.strip()}\n\n"
        f"Available tables:\n{tables_str}\n\n"
        "Return ONLY a JSON array of the table names required (max 3)."
    )

    try:
        resp = groq_client.chat.completions.create(
            model=LLM_MODEL,
            temperature=0,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
        )
        raw_output = resp.choices[0].message.content
        print(f"   🤖 LLM raw response: {raw_output.strip()}")
    except Exception as exc:
        print(f"   ❌ Groq API call failed: {exc}")
        return []

    selected = _extract_json_array(raw_output)
    print(f"   📥 LLM suggested tables: {selected}")

    # Validate against real table names
    name_map = {
        _extract_name(t).lower(): _extract_name(t)
        for t in all_tables
    }

    validated = []
    for t in selected:
        canonical = name_map.get(t.lower())
        if canonical:
            validated.append(canonical)
        else:
            print(f"   ⚠️  '{t}' not found in DB — skipped")

    # Deduplicate
    seen, unique = set(), []
    for t in validated:
        if t not in seen:
            seen.add(t)
            unique.append(t)

    final = _filter_backup_tables(unique)[:3]
    print(f"   ✅ Final selected tables: {final}")
    return final