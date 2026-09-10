"""
query_generator.py
------------------
Generates a safe SQL SELECT query from natural language + table schema.
"""

import os
import re
import logging
from typing import List

from groq import Groq

logger      = logging.getLogger("query_generator")
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
LLM_MODEL   = "llama-3.3-70b-versatile"

DANGEROUS_KEYWORDS = [
    "DELETE", "DROP", "UPDATE", "INSERT",
    "ALTER", "TRUNCATE", "EXEC", "EXECUTE"
]


# ─────────────────────────────────────────────
# 1. get_table_schema()
# ─────────────────────────────────────────────
def get_table_schema(tables: List[str]) -> str:
    print("\n" + "─"*60)
    print("📐 STEP 5 — SCHEMA FETCH")
    print("─"*60)
    print(f"   Fetching schema for tables: {tables}")

    if not tables:
        print("   ⚠️  No tables provided")
        return ""

    try:
        from database.db import get_connection

        conn   = get_connection()
        cursor = conn.cursor()
        schema_text = ""

        for table in tables:
            print(f"   📂 Fetching columns for: {table}")
            try:
                # Try INFORMATION_SCHEMA first (works for tables)
                cursor.execute("""
                    SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
                    FROM   INFORMATION_SCHEMA.COLUMNS
                    WHERE  TABLE_NAME = ?
                    ORDER  BY ORDINAL_POSITION
                """, (table,))
                columns = cursor.fetchall()

                # If empty, try sys.columns (works for views)
                if not columns:
                    print(f"   🔄 Not found in INFORMATION_SCHEMA — trying sys.columns (view)...")
                    cursor.execute("""
                        SELECT c.name, t.name, 'YES'
                        FROM   sys.columns c
                        JOIN   sys.types   t ON c.user_type_id = t.user_type_id
                        JOIN   sys.objects o ON c.object_id    = o.object_id
                        WHERE  o.name = ?
                        AND    o.type IN ('V', 'U')
                        ORDER  BY c.column_id
                    """, (table,))
                    columns = cursor.fetchall()

                if not columns:
                    print(f"   ⚠️  No columns found for '{table}' — skipping")
                    continue

                print(f"   ✅ {len(columns)} columns found for '{table}'")
                col_defs = "\n".join(
                    f"    - {r[0]} ({r[1]}, nullable={r[2]})"
                    for r in columns
                )

                # Sample data
                try:
                    cursor.execute(f"SELECT TOP 3 * FROM [{table}]")
                    rows      = cursor.fetchall()
                    col_names = [d[0] for d in cursor.description]

                    if rows:
                        lines = [
                            "    " + str({col_names[i]: str(r[i]) for i in range(len(col_names))})
                            for r in rows
                        ]
                        sample_text = "\n".join(lines)
                        print(f"   📊 Sample data fetched ({len(rows)} rows)")
                    else:
                        sample_text = "    (no sample data)"
                        print(f"   ⚠️  No sample data for '{table}'")

                except Exception as se:
                    print(f"   ⚠️  Sample data failed for '{table}': {se}")
                    sample_text = "    (sample data unavailable)"

                schema_text += (
                    f"\nTable: {table}\n"
                    f"Columns:\n{col_defs}\n"
                    f"Sample Data (top 3 rows):\n{sample_text}\n"
                    f"{'-' * 60}\n"
                )

            except Exception as te:
                print(f"   ❌ Error processing table '{table}': {te}")

        cursor.close()
        conn.close()

        print(f"   ✅ Schema built for {len(tables)} table(s)")
        return schema_text.strip()

    except Exception as exc:
        print(f"   ❌ DB connection failed: {exc}")
        return ""


# ─────────────────────────────────────────────
# 2. Helpers
# ─────────────────────────────────────────────
def _extract_sql(text: str) -> str:
    if not text or not text.strip():
        return ""
    m = re.search(r"```sql\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r"```(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    m = re.search(r"(SELECT\s+.+)", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return ""


def _is_safe(sql: str) -> bool:
    if not sql:
        return False
    upper = sql.upper().strip()
    if not upper.startswith("SELECT"):
        print("   ❌ Safety check failed: query does not start with SELECT")
        return False
    for kw in DANGEROUS_KEYWORDS:
        if re.search(rf"\b{kw}\b", upper):
            print(f"   ❌ Safety check failed: blocked keyword '{kw}' found")
            return False
    return True


# ─────────────────────────────────────────────
# 3. generate_sql()
# ─────────────────────────────────────────────
def generate_sql(query: str, tables: List[str]) -> str:
    print("\n" + "─"*60)
    print("✍️  STEP 6 — SQL GENERATION")
    print("─"*60)
    print(f"   Question : {query}")
    print(f"   Tables   : {tables}")

    if not query or not tables:
        print("   ⚠️  Empty query or tables — cannot generate SQL")
        return ""

    schema = get_table_schema(tables)
    if not schema:
        print("   ❌ No schema available — aborting SQL generation")
        return ""

    print("   🤖 Calling LLM to generate SQL...")

    system_prompt = (
        "You are an expert Microsoft SQL Server query writer for Air India Express crew management system.\n\n"
        "YOUR JOB:\n"
        "Write a single correct SQL SELECT query to answer the user's question.\n\n"
        "STRICT RULES:\n"
        "1. Use ONLY table and column names from the schema below.\n"
        "2. Never invent column or table names.\n"
        "3. Generate ONLY a SELECT statement — no INSERT, UPDATE, DELETE, DROP, ALTER.\n"
        "4. Use SQL Server syntax: TOP instead of LIMIT.\n"
        "5. For date comparisons use CONVERT(date, column) — never convert to nvarchar.\n"
        "6. Wrap all table and column names in square brackets [ ].\n"
        "7. Always write: SELECT DISTINCT TOP 100 (in that exact order).\n"
        "8. For date values use 'YYYY-MM-DD' format only.\n"
        "9. Return ONLY the SQL query — no explanation, no markdown.\n"
        "10. If question cannot be answered with schema → return: SELECT 'insufficient schema' AS message\n\n"
        "IMPORTANT JOIN KEYS:\n"
        "- Aix_BaseCrewInfo.ID          = AIX_CrewInfo.StaffNumber (use LTRIM/RTRIM on StaffNumber)\n"
        "- Aix_BaseCrewInfo.ID          = Aix_CrewRoster.ID\n"
        "- Aix_BaseCrewInfo.ID          = AIX_CrewRosterStatistics.ID\n"
        "- Aix_BaseCrewInfo.ID          = PayRoll_Designations.ID\n"
        "- AIX_CrewInfo.StaffNumber     = AIX_CrewFunctions.StaffNumber (use LTRIM/RTRIM)\n"
        "- AIX_CrewInfo.StaffNumber     = AIX_CrewRanks.StaffNumber (use LTRIM/RTRIM)\n\n"
        "IMPORTANT BUSINESS RULES:\n"
        "- Active crew    → employmentEnd = '2099-12-31' OR employmentEnd IS NULL\n"
        "- Resigned crew  → ResignationDate IS NOT NULL\n"
        "- Current rank   → RankEnd = '2099-12-31'\n"
        "- Current function → FunctionEnd = '2099-12-31'\n"
        "- StaffNumber in AIX_CrewFunctions and AIX_CrewRanks has trailing spaces → always use LTRIM(RTRIM([StaffNumber]))\n\n"
        "THINK STEP BY STEP (internally):\n"
        "  1. Identify needed columns.\n"
        "  2. Confirm they exist in schema.\n"
        "  3. Determine if JOIN is needed.\n"
        "  4. Write SQL using only confirmed columns.\n"
        "  5. Double-check syntax.\n"
        "DATE CONVERSION RULES FOR THIS DB:\n"
        "- employmentEnd is nvarchar — compare as string: WHERE [employmentEnd] = '2099-12-31'\n"
        "- employmentStart is nvarchar — compare as string: WHERE [employmentEnd] > '2024-01-01'\n"
        "- NEVER use CONVERT(date, employmentEnd) — it will fail on 'None' values\n"
        "- ResignationDate in AIX_CrewInfo is a proper date column — CONVERT is safe there\n"
        "- DutyDateUtc and DutyDateIst in Aix_CrewRoster are nvarchar — compare as string\n"
        "- Date columns safe for CONVERT: EmploymentDate, RankStart, RankEnd, FunctionStart, FunctionEnd\n"
    )

    user_prompt = (
        f"User question:\n{query.strip()}\n\n"
        f"Selected tables: {', '.join(tables)}\n\n"
        f"Schema:\n{schema}\n\n"
        "Write a SQL Server SELECT query. Return ONLY the SQL."
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
        raw = resp.choices[0].message.content
        print(f"   🤖 LLM raw response (first 200 chars): {raw.strip()[:200]}")
    except Exception as exc:
        print(f"   ❌ Groq API call failed: {exc}")
        return ""

    sql = _extract_sql(raw)

    if not sql:
        print("   ❌ Could not extract SQL from LLM response")
        return ""

    if not _is_safe(sql):
        print("   ❌ SQL failed safety check — blocked")
        return ""

    print(f"   ✅ Generated SQL:\n   {sql[:300]}")
    return sql