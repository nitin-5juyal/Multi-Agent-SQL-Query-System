"""
table_registry.py
-----------------
Single source of truth for domain → tables mapping.
"""

import logging
from typing import Dict, List

logger = logging.getLogger("table_registry")

DOMAIN_MAP: Dict[str, List[str]] = {
    "crew": [
    "Aix_BaseCrewInfo",
    "AIX_CrewFunctions",
    "AIX_CrewInfo",
    "AIX_CrewRanks",
    "Aix_CrewRoster",
    "AIX_CrewRosterStatistics",
    "PayRoll_Designations"
],
    "general": [],
}


def get_domain_tables(domain: str) -> List[str]:
    domain = domain.lower().strip()
    if domain not in DOMAIN_MAP:
        logger.warning("Unknown domain '%s' — returning empty list.", domain)
        return []
    tables = DOMAIN_MAP.get(domain, [])
    print(f"   📋 Registry → domain='{domain}' has {len(tables)} tables: {tables}")
    return tables


def get_all_domains() -> List[str]:
    return [d for d in DOMAIN_MAP if d != "general"]


def get_full_registry() -> Dict[str, List[str]]:
    return DOMAIN_MAP


def add_table_to_domain(domain: str, table: str) -> None:
    if domain not in DOMAIN_MAP:
        DOMAIN_MAP[domain] = []
    if table not in DOMAIN_MAP[domain]:
        DOMAIN_MAP[domain].append(table)
        print(f"   ➕ Added '{table}' to domain '{domain}'")


def validate_domain_tables(domain: str) -> List[str]:
    """
    Returns only tables from the domain that actually exist in the DB.
    Falls back to full domain list if DB check fails.
    """
    print(f"   🔎 Validating domain tables for '{domain}' against DB...")
    from agents.fallback_agent.tools.table_selector import get_all_tables

    domain_tables = get_domain_tables(domain)
    if not domain_tables:
        print(f"   ⚠️  No tables defined for domain '{domain}'")
        return []

    try:
        all_db_tables = get_all_tables()
        real_names    = {t.split("[")[0].strip().lower() for t in all_db_tables}
        valid         = [t for t in domain_tables if t.lower() in real_names]
        invalid       = [t for t in domain_tables if t.lower() not in real_names]

        if invalid:
            print(f"   ⚠️  Tables in registry but NOT in DB: {invalid}")
        if valid:
            print(f"   ✅ Valid tables confirmed in DB: {valid}")

        return valid if valid else domain_tables

    except Exception as exc:
        print(f"   ❌ DB validation failed: {exc} → using registry list as fallback")
        return domain_tables
    


    