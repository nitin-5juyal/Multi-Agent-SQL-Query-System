"""
read_object_definition.py
--------------------------
Tool 2 — Agent's BRAIN.

Job    : Read full schema (columns + data types + sample rows) for a table.
Input  : table_name (str)
Output : dict { table, columns, sample_data }
Depends: DB connection ONLY.
No other tool is imported or called.
"""

import logging
from typing import Any, Dict, List

logger = logging.getLogger("read_object_definition")


def read_object_definition(table_name: str) -> Dict[str, Any]:
    """
    Reads schema and sample data for a single table.

    Args:
        table_name: Exact table name e.g. "Aix_BaseCrewInfo"

    Returns:
        {
            "table"      : str,
            "columns"    : [ { name, data_type, nullable } ],
            "sample_data": [ { col: val, ... } ],   # top 3 rows
            "error"      : str or None
        }
    """
    print("\n" + "─" * 60)
    print("🧠 TOOL: read_object_definition")
    print("─" * 60)
    print(f"   Table : {table_name}")

    if not table_name or not table_name.strip():
        return {"table": table_name, "columns": [], "sample_data": [], "error": "Empty table name."}

    try:
        from database.db import get_connection

        conn   = get_connection()
        cursor = conn.cursor()

        # ── Columns ──────────────────────────────────────────
        cursor.execute("""
            SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
            FROM   INFORMATION_SCHEMA.COLUMNS
            WHERE  TABLE_NAME = ?
            ORDER  BY ORDINAL_POSITION
        """, (table_name,))
        rows = cursor.fetchall()

        # Fallback: try sys.columns for views
        if not rows:
            print(f"   🔄 Not in INFORMATION_SCHEMA — trying sys.columns...")
            cursor.execute("""
                SELECT c.name, t.name, 'YES'
                FROM   sys.columns c
                JOIN   sys.types   t ON c.user_type_id = t.user_type_id
                JOIN   sys.objects o ON c.object_id    = o.object_id
                WHERE  o.name = ?
                AND    o.type IN ('V', 'U')
                ORDER  BY c.column_id
            """, (table_name,))
            rows = cursor.fetchall()

        if not rows:
            print(f"   ❌ No columns found for '{table_name}'")
            cursor.close()
            conn.close()
            return {
                "table"      : table_name,
                "columns"    : [],
                "sample_data": [],
                "error"      : f"Table '{table_name}' not found or has no columns."
            }

        columns = [
            {"name": r[0], "data_type": r[1], "nullable": r[2]}
            for r in rows
        ]
        print(f"   ✅ {len(columns)} columns found")

        # ── Sample Data ───────────────────────────────────────
        sample_data = []
        try:
            cursor.execute(f"SELECT TOP 3 * FROM [{table_name}]")
            col_names = [d[0] for d in cursor.description]
            for row in cursor.fetchall():
                row_dict = {}
                for i, col in enumerate(col_names):
                    val = row[i]
                    if hasattr(val, "isoformat"):
                        row_dict[col] = val.isoformat()
                    elif isinstance(val, bytes):
                        row_dict[col] = val.hex()
                    else:
                        row_dict[col] = val
                sample_data.append(row_dict)
            print(f"   📊 {len(sample_data)} sample rows fetched")

        except Exception as se:
            print(f"   ⚠️  Sample data failed: {se}")

        cursor.close()
        conn.close()

        return {
            "table"      : table_name,
            "columns"    : columns,
            "sample_data": sample_data,
            "error"      : None,
        }

    except Exception as exc:
        print(f"   ❌ read_object_definition failed: {exc}")
        return {
            "table"      : table_name,
            "columns"    : [],
            "sample_data": [],
            "error"      : str(exc),
        }