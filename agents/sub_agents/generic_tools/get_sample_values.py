"""
get_sample_values.py
---------------------
Tool 3 — Agent's UNDERSTANDING.

Job    : Get distinct real values from a specific column.
Input  : table_name (str), column_name (str), limit (int)
Output : List of distinct values
Depends: DB connection ONLY.
No other tool is imported or called.
"""

import logging
import re
from typing import Any, List

logger = logging.getLogger("get_sample_values")

BLOCKED_KEYWORDS = [
    "DELETE", "DROP", "UPDATE", "INSERT",
    "ALTER", "TRUNCATE", "EXEC", "EXECUTE"
]


def get_sample_values(
    table_name : str,
    column_name: str,
    limit      : int = 20,
) -> List[Any]:
    """
    Returns distinct non-null values from a column.
    Helps agent understand what data looks like before writing SQL.

    Args:
        table_name : e.g. "Aix_BaseCrewInfo"
        column_name: e.g. "Base"
        limit      : max distinct values to return (default 20)

    Returns:
        List of distinct values e.g. ["Delhi", "Mumbai", "Bangalore"]
    """
    print("\n" + "─" * 60)
    print("🔍 TOOL: get_sample_values")
    print("─" * 60)
    print(f"   Table  : {table_name}")
    print(f"   Column : {column_name}")
    print(f"   Limit  : {limit}")

    # Safety — no injection via table/column names
    if not table_name or not column_name:
        print("   ❌ Empty table or column name")
        return []

    for kw in BLOCKED_KEYWORDS:
        if kw.lower() in table_name.lower() or kw.lower() in column_name.lower():
            print(f"   ❌ Blocked keyword in input: {kw}")
            return []

    # Only allow alphanumeric + underscore in names
    if not re.match(r"^[\w\s]+$", table_name) or not re.match(r"^[\w\s]+$", column_name):
        print("   ❌ Invalid characters in table/column name")
        return []

    try:
        from database.db import get_connection

        conn   = get_connection()
        cursor = conn.cursor()

        sql = (
            f"SELECT DISTINCT TOP {int(limit)} [{column_name}] "
            f"FROM [{table_name}] "
            f"WHERE [{column_name}] IS NOT NULL "
            f"ORDER BY [{column_name}]"
        )

        cursor.execute(sql)
        rows = cursor.fetchall()

        values = []
        for row in rows:
            val = row[0]
            if hasattr(val, "isoformat"):
                values.append(val.isoformat())
            elif isinstance(val, bytes):
                values.append(val.hex())
            else:
                values.append(val)

        cursor.close()
        conn.close()

        print(f"   ✅ {len(values)} distinct values found: {values[:10]}")
        return values

    except Exception as exc:
        print(f"   ❌ get_sample_values failed: {exc}")
        return []