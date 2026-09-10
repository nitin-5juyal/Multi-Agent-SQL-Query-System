"""
execute_sql.py
--------------
Tool 4 — Agent's HANDS.

Job    : Validate and execute a SQL SELECT query safely.
Input  : sql (str)
Output : dict { status, columns, rows, row_count, error }
Depends: DB connection ONLY.
No other tool is imported or called.
"""

import re
import logging
from typing import Any, Dict, List

logger = logging.getLogger("execute_sql")

# ── Safety Rules ─────────────────────────────────────────────
BLOCKED_KEYWORDS = [
    "DELETE", "DROP", "UPDATE", "INSERT", "ALTER",
    "TRUNCATE", "EXEC", "EXECUTE", "XP_", "SP_",
    "OPENROWSET", "OPENDATASOURCE", "BULK", "SHUTDOWN",
]

INJECTION_PATTERNS = [
    r"(--)",
    r"(/\*.*?\*/)",
    r"(;.+)",
    r"(\bOR\b\s+\d+\s*=\s*\d+)",
    r"(\bAND\b\s+\d+\s*=\s*\d+)",
    r"(UNION\s+SELECT)",
    r"(CHAR\s*\()",
    r"(CAST\s*\(.*EXEC)",
    r"(CONVERT\s*\(.*EXEC)",
]


# ── Internal Validator ────────────────────────────────────────
def _validate(sql: str) -> Dict[str, Any]:
    if not sql or not sql.strip():
        return {"valid": False, "reason": "Query is empty."}

    cleaned = sql.strip()

    if not re.match(r"^\s*SELECT\b", cleaned, re.IGNORECASE):
        return {"valid": False, "reason": "Only SELECT queries are allowed."}

    upper = cleaned.upper()

    for kw in BLOCKED_KEYWORDS:
        if re.search(rf"\b{re.escape(kw)}\b", upper):
            return {"valid": False, "reason": f"Blocked keyword: {kw}"}

    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, cleaned, re.IGNORECASE | re.DOTALL):
            return {"valid": False, "reason": "SQL injection pattern detected."}

    if ";" in cleaned.rstrip(";"):
        return {"valid": False, "reason": "Multiple SQL statements not allowed."}

    if len(cleaned) < 10:
        return {"valid": False, "reason": "Query too short."}

    return {"valid": True}


# ── Public Tool ───────────────────────────────────────────────
def execute_sql(sql: str) -> Dict[str, Any]:
    """
    Validates then executes a SQL SELECT query.

    Args:
        sql: SQL SELECT string to execute

    Returns:
        {
            "status"   : "success" | "error",
            "columns"  : List[str],
            "rows"     : List[List[Any]],
            "row_count": int,
            "error"    : str or None
        }
    """
    print("\n" + "─" * 60)
    print("🤝 TOOL: execute_sql")
    print("─" * 60)
    print(f"   SQL (first 200): {sql[:200] if sql else 'EMPTY'}")

    # Step 1: Validate
    validation = _validate(sql)
    if not validation["valid"]:
        reason = validation["reason"]
        print(f"   ❌ Validation failed: {reason}")
        return {
            "status"   : "error",
            "columns"  : [],
            "rows"     : [],
            "row_count": 0,
            "error"    : f"Validation failed: {reason}",
        }

    print("   ✅ Validation passed — executing...")

    # Step 2: Execute
    try:
        from database.db import get_connection

        conn   = get_connection()
        cursor = conn.cursor()
        cursor.execute(sql)

        columns = [desc[0] for desc in cursor.description]
        raw_rows = cursor.fetchall()

        rows: List[List[Any]] = []
        for row in raw_rows:
            clean_row = []
            for val in row:
                if hasattr(val, "isoformat"):
                    clean_row.append(val.isoformat())
                elif isinstance(val, bytes):
                    clean_row.append(val.hex())
                else:
                    clean_row.append(val)
            rows.append(clean_row)

        cursor.close()
        conn.close()

        print(f"   ✅ Execution success — {len(rows)} rows returned")
        print(f"   📊 Columns: {columns}")
        if rows:
            print(f"   📊 First row sample: {dict(zip(columns, [str(v) for v in rows[0]]))}")

        return {
            "status"   : "success",
            "columns"  : columns,
            "rows"     : rows,
            "row_count": len(rows),
            "error"    : None,
        }

    except Exception as exc:
        print(f"   ❌ Execution failed: {exc}")
        return {
            "status"   : "error",
            "columns"  : [],
            "rows"     : [],
            "row_count": 0,
            "error"    : str(exc),
        }