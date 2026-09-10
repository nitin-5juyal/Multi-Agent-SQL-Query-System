"""
validator.py
------------
Validates and executes SQL SELECT queries safely against SQL Server.
"""

import os
import re
import logging
from typing import Any, Dict, List

logger = logging.getLogger("validator")

BLOCKED_KEYWORDS = [
    "DELETE", "DROP", "UPDATE", "INSERT", "ALTER",
    "TRUNCATE", "EXEC", "EXECUTE", "XP_", "SP_",
    "OPENROWSET", "OPENDATASOURCE", "BULK", "SHUTDOWN"
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


def validate_sql(query: str) -> Dict[str, Any]:
    print("\n" + "─"*60)
    print("🛡️  STEP 7 — SQL VALIDATION")
    print("─"*60)
    print(f"   SQL (first 200 chars): {query[:200] if query else 'EMPTY'}")

    if not query or not query.strip():
        print("   ❌ Query is empty")
        return {"valid": False, "reason": "Query is empty."}

    cleaned = query.strip()

    if not re.match(r"^\s*SELECT\b", cleaned, re.IGNORECASE):
        print("   ❌ Query does not start with SELECT")
        return {"valid": False, "reason": "Only SELECT queries are allowed."}

    upper = cleaned.upper()

    for kw in BLOCKED_KEYWORDS:
        if re.search(rf"\b{re.escape(kw)}\b", upper):
            print(f"   ❌ Blocked keyword detected: {kw}")
            return {"valid": False, "reason": f"Blocked keyword detected: {kw}"}

    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, cleaned, re.IGNORECASE | re.DOTALL):
            print(f"   ❌ SQL injection pattern detected: {pattern}")
            return {"valid": False, "reason": "Potential SQL injection pattern detected."}

    if ";" in cleaned.rstrip(";"):
        print("   ❌ Multiple statements detected (semicolon in middle)")
        return {"valid": False, "reason": "Multiple SQL statements are not allowed."}

    if len(cleaned) < 10:
        print("   ❌ Query too short")
        return {"valid": False, "reason": "Query is too short to be valid."}

    print("   ✅ SQL passed all validation checks")
    return {"valid": True}


def execute_sql(query: str) -> Dict[str, Any]:
    print("\n" + "─"*60)
    print("⚡ STEP 8 — SQL EXECUTION")
    print("─"*60)
    print(f"   Executing SQL: {query[:200]}")

    try:
        from database.db import get_connection

        conn   = get_connection()
        cursor = conn.cursor()

        cursor.execute(query)

        columns = [desc[0] for desc in cursor.description]
        rows    = cursor.fetchall()

        print(f"   ✅ Execution successful")
        print(f"   📊 Columns : {columns}")
        print(f"   📊 Row count: {len(rows)}")

        if rows:
            print(f"   📊 First row sample: {dict(zip(columns, [str(v) for v in rows[0]]))}")

        results: List[Dict[str, Any]] = []
        for row in rows:
            row_dict = {}
            for i, col in enumerate(columns):
                val = row[i]
                if hasattr(val, "isoformat"):
                    row_dict[col] = val.isoformat()
                elif isinstance(val, bytes):
                    row_dict[col] = val.hex()
                else:
                    row_dict[col] = val
            results.append(row_dict)

        cursor.close()
        conn.close()

        return {
            "status"   : "success",
            "data"     : results,
            "row_count": len(results),
            "columns"  : columns,
        }

    except Exception as exc:
        print(f"   ❌ SQL execution failed: {exc}")
        return {"status": "error", "error": str(exc)}


def validate_and_execute(query: str) -> Dict[str, Any]:
    result = validate_sql(query)
    if not result.get("valid"):
        reason = result.get("reason", "Unknown validation error.")
        print(f"   ❌ Query rejected at validation: {reason}")
        return {"status": "error", "error": f"Validation failed: {reason}"}
    return execute_sql(query)