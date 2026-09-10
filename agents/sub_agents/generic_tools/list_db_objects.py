"""
list_db_objects.py
------------------
Tool 1 — Agent's EYES.

Job    : Return all table names for a given domain.
Input  : domain (str)
Output : List[str] of table names
Depends: DB connection + table_registry ONLY
No other tool is imported or called.
"""

import logging
from typing import List

logger = logging.getLogger("list_db_objects")

# Domain → tables mapping (single source of truth)
DOMAIN_TABLES = {
    "crew": [
        "Aix_BaseCrewInfo",
        "AIX_CrewInfo",
        "AIX_CrewRanks",
        "AIX_CrewFunctions",
        "Aix_CrewRoster",
        "AIX_CrewRosterStatistics",
        "PayRoll_Designations",
        "PayRollReport"
    ],
    "general": [],
}


def list_db_objects(domain: str) -> List[str]:
    """
    Returns all table names for the given domain.
    Validates each table actually exists in the DB.
    Falls back to registry list if DB check fails.

    Args:
        domain: e.g. "crew", "general"

    Returns:
        List of valid table name strings.
    """
    print("\n" + "─" * 60)
    print("👁️  TOOL: list_db_objects")
    print("─" * 60)
    print(f"   Domain : {domain}")

    domain = domain.lower().strip()

    # Get domain boundary from registry
    tables = DOMAIN_TABLES.get(domain, [])
    if not tables:
        print(f"   ⚠️  No tables defined for domain '{domain}'")
        return []

    print(f"   📋 Registry has {len(tables)} tables for '{domain}'")

    # Validate tables exist in DB
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
        db_tables = {row[0].lower() for row in cursor.fetchall()}

        cursor.close()
        conn.close()

        valid   = [t for t in tables if t.lower() in db_tables]
        invalid = [t for t in tables if t.lower() not in db_tables]

        if invalid:
            print(f"   ⚠️  Tables in registry but NOT in DB: {invalid}")

        print(f"   ✅ Confirmed {len(valid)} valid tables: {valid}")
        return valid

    except Exception as exc:
        print(f"   ❌ DB validation failed: {exc}")
        print(f"   ↩️  Falling back to registry list: {tables}")
        return tables