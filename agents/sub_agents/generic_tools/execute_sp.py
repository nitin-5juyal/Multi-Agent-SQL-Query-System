"""
execute_sp.py
-------------
Tool 5 — Agent's STORED PROCEDURE EXECUTOR.

Job    : Discover and execute stored procedures safely.
Input  : sp_name (str), params (dict)
Output : dict { status, columns, rows, row_count, error }
Depends: DB connection ONLY.
No other tool is imported or called.

HOW LLM USES THIS TOOL:
    Step 1 → call execute_sp("list", {})        → see all available SPs
    Step 2 → call execute_sp("sp_name", params) → execute the SP

Available SPs:
    getpastflyingsummery  (@staffid)     → past flying summary
    getpersonalprofile    (@staffid)     → personal profile
    getpersonalreport     (@staffid)     → personal report
    GETPILOTCOMPLETEDATA  (@SEARCHNAME)  → pilot data by name
    GETPILOTCOMPLETEDATA2 ()             → all pilots complete data
    getrosterreport       (@staffid)     → roster report
"""

import logging
from typing import Any, Dict, List

logger = logging.getLogger("execute_sp")


# ══════════════════════════════════════════════════════════════
# SP REGISTRY — single source of truth, lives here only
# ══════════════════════════════════════════════════════════════

SP_REGISTRY: Dict[str, Dict[str, Any]] = {
    "getpastflyingsummery": {
        "params"     : ["staffid"],
        "description": "Returns past flying summary for a crew member by staff ID",
        "example"    : {"staffid": "85005276"},
    },
    "getpersonalprofile": {
        "params"     : ["staffid"],
        "description": "Returns complete personal profile of a crew member by staff ID",
        "example"    : {"staffid": "85005276"},
    },
    "getpersonalreport": {
        "params"     : ["staffid"],
        "description": "Returns personal report of a crew member by staff ID",
        "example"    : {"staffid": "85005276"},
    },
    "GETPILOTCOMPLETEDATA": {
        "params"     : ["SEARCHNAME"],
        "description": "Returns complete pilot data by searching name (partial name works)",
        "example"    : {"SEARCHNAME": "SUSHMA"},
    },
    "GETPILOTCOMPLETEDATA2": {
        "params"     : [],
        "description": "Returns complete data for ALL pilots — no parameters needed",
        "example"    : {},
    },
    "getrosterreport": {
        "params"     : ["staffid"],
        "description": "Returns roster report for a crew member by staff ID",
        "example"    : {"staffid": "85005276"},
    },
}


# ══════════════════════════════════════════════════════════════
# INTERNAL VALIDATOR
# ══════════════════════════════════════════════════════════════

def _validate(sp_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Validates SP name and parameters before execution."""

    if sp_name not in SP_REGISTRY:
        return {
            "valid" : False,
            "reason": f"SP '{sp_name}' not found. Available: {list(SP_REGISTRY.keys())}"
        }

    required = SP_REGISTRY[sp_name]["params"]
    for param in required:
        if param not in params:
            return {
                "valid" : False,
                "reason": f"Missing required parameter '{param}'. "
                          f"Example: {SP_REGISTRY[sp_name]['example']}"
            }

    # Injection check
    dangerous = ["'", ";", "--", "/*", "*/", "xp_", "exec", "drop", "delete"]
    for param, value in params.items():
        for d in dangerous:
            if d in str(value).lower():
                return {
                    "valid" : False,
                    "reason": f"Dangerous pattern '{d}' in parameter '{param}'"
                }

    return {"valid": True}


# ══════════════════════════════════════════════════════════════
# PUBLIC TOOL — one function, two modes
# ══════════════════════════════════════════════════════════════

def execute_sp(sp_name: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Single tool for SP discovery and execution.

    MODE 1 — Discovery (call this first):
        execute_sp("list", {})
        → Returns all available SPs with params and descriptions

    MODE 2 — Execution:
        execute_sp("getpersonalprofile", {"staffid": "85005276"})
        → Executes the SP and returns results

    Args:
        sp_name : "list" to discover SPs, or exact SP name to execute
        params  : Dict of params e.g. {"staffid": "85005276"}
                  Use {} for SPs with no parameters

    Returns:
        Discovery mode:
            { "available_sps": { name: { params, description, example } } }
        Execution mode:
            {
                "status"   : "success" | "error",
                "sp_name"  : str,
                "columns"  : List[str],
                "rows"     : List[List[Any]],
                "row_count": int,
                "error"    : str or None
            }
    """
    if params is None:
        params = {}

    print("\n" + "─" * 60)
    print("⚙️  TOOL: execute_sp")
    print("─" * 60)

    # ── MODE 1: Discovery ─────────────────────────────────────
    if sp_name == "list":
        print("   📋 Discovery mode — listing all available SPs")
        result = {}
        for name, info in SP_REGISTRY.items():
            result[name] = {
                "params"     : info["params"],
                "description": info["description"],
                "example"    : info["example"],
            }
            print(f"   ✅ {name} → params: {info['params']}")
        return {"available_sps": result}

    # ── MODE 2: Execution ─────────────────────────────────────
    print(f"   SP Name : {sp_name}")
    print(f"   Params  : {params}")

    # Validate
    check = _validate(sp_name, params)
    if not check["valid"]:
        print(f"   ❌ Validation failed: {check['reason']}")
        return {
            "status"   : "error",
            "sp_name"  : sp_name,
            "columns"  : [],
            "rows"     : [],
            "row_count": 0,
            "error"    : f"Validation failed: {check['reason']}",
        }

    print("   ✅ Validation passed — executing...")

    try:
        from database.db import get_connection

        conn   = get_connection()
        cursor = conn.cursor()

        required = SP_REGISTRY[sp_name]["params"]

        if not required:
            # No params SP
            exec_sql     = f"EXEC dbo.{sp_name}"
            param_values = []
        else:
            # Parameterized SP
            placeholders = ", ".join([f"@{p}=?" for p in required])
            exec_sql     = f"EXEC dbo.{sp_name} {placeholders}"
            param_values = [params[p] for p in required]

        print(f"   📋 Executing: {exec_sql}")
        if param_values:
            print(f"   📋 Values   : {param_values}")

        cursor.execute(exec_sql, param_values)

        # SP returned no result set
        if cursor.description is None:
            print("   ⚠️  SP returned no result set")

            # 🔥 PAYROLL SPECIAL HANDLING
            if "payroll" in sp_name.lower() or "payroll" in str(params).lower():
                print("   🔄 Fetching payroll data after SP execution...")

                crew_id = params.get("CrewID") or params.get("staffid")

                if crew_id:
                    cursor.execute("""
                        SELECT TOP 10 *
                        FROM PayRoll_Designations
                        WHERE ID = ?
                        ORDER BY MonthYear DESC
                    """, (crew_id,))

                    columns  = [desc[0] for desc in cursor.description]
                    raw_rows = cursor.fetchall()

                    rows = []
                    for row in raw_rows:
                        rows.append([
                            val.isoformat() if hasattr(val, "isoformat") else val
                            for val in row
                        ])

                    cursor.close()
                    conn.close()

                    print(f"   ✅ Payroll fetched — {len(rows)} rows")

                    return {
                        "status"   : "success",
                        "sp_name"  : sp_name,
                        "columns"  : columns,
                        "rows"     : rows,
                        "row_count": len(rows),
                        "error"    : None,
                    }

            # fallback (no data)
            cursor.close()
            conn.close()

            return {
                "status"   : "success",
                "sp_name"  : sp_name,
                "columns"  : [],
                "rows"     : [],
                "row_count": 0,
                "error"    : "SP executed but returned no data",
            }

        # Fetch and clean results
        columns  = [desc[0] for desc in cursor.description]
        raw_rows = cursor.fetchall()

        rows: List[List[Any]] = []
        for row in raw_rows:
            clean_row = []
            for val in row:
                if hasattr(val, "isoformat"):
                    clean_row.append(val.isoformat())
                elif isinstance(val, bytes):
                    clean_row.append(val.hex())
                elif val is None:
                    clean_row.append(None)
                else:
                    clean_row.append(val)
            rows.append(clean_row)

        cursor.close()
        conn.close()

        print(f"   ✅ Success — {len(rows)} rows returned")
        print(f"   📊 Columns: {columns}")
        if rows:
            print(f"   📊 First row: {dict(zip(columns, [str(v) for v in rows[0]]))}")

        return {
            "status"   : "success",
            "sp_name"  : sp_name,
            "columns"  : columns,
            "rows"     : rows,
            "row_count": len(rows),
            "error"    : None,
        }

    except Exception as exc:
        print(f"   ❌ SP execution failed: {exc}")
        return {
            "status"   : "error",
            "sp_name"  : sp_name,
            "columns"  : [],
            "rows"     : [],
            "row_count": 0,
            "error"    : str(exc),
        }