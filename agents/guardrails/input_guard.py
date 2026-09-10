"""
guard_input.py
--------------
Location: agents/sub_agents/crew_agent/tools/guard_input.py

Smart context-aware input guardrail.

Rules:
- SQL destructive keywords → only block if used as COMMANDS not nouns/adjectives
- Sensitive data → block specific phrases not single words
- Security credentials → always block
- Numeric patterns → always block (aadhaar, card, mobile)
"""

import re


# ══════════════════════════════════════════════════════════════
# SQL DESTRUCTIVE — block only when used as commands
# Pattern: word must appear as action verb, not noun/adjective
# ══════════════════════════════════════════════════════════════

# These patterns catch the word as a COMMAND (verb form)
# NOT as adjective/noun in normal sentences
SQL_COMMAND_PATTERNS = [
    # "delete crew" / "delete all" / "delete from" / "delete the"
    r"\bdelete\s+(all|from|the|data|records?|rows?|entries|crew|table|payroll)\b",
    r"\bdelete\s+\w+\s+(from|in|of)\b",

    # "drop table" / "drop the" / "drop database"
    r"\bdrop\s+(table|database|db|the|all|index|view|column)\b",

    # "truncate table" / "truncate the"
    r"\btruncate\s+(table|the|all|data|records?)\b",

    # "update set" / "update crew salary" / "update the"
    r"\bupdate\s+(set|the|all|crew|salary|data|record|table|payroll)\b",
    r"\bupdate\s+\w+\s+set\b",

    # "insert into" / "insert new" / "insert record"
    r"\binsert\s+(into|new|record|data|row|entry|crew)\b",

    # "alter table" / "alter column"
    r"\balter\s+(table|column|database|the)\b",

    # "create table" / "create database"
    r"\bcreate\s+(table|database|db|index|view|column)\b",

    # "remove crew" / "remove all" / "remove from"
    r"\bremove\s+(all|from|the|crew|data|records?|entries|duplicate)\b",

    # "replace into" / "replace data"
    r"\breplace\s+(into|data|all|the|records?)\b",
]


# ══════════════════════════════════════════════════════════════
# SENSITIVE DATA — block specific phrases only
# NOT single words like "bank", "contact", "address"
# ══════════════════════════════════════════════════════════════

SENSITIVE_PHRASES = {
    # contact info — phrases only
    "contact": [
        "phone number", "mobile number", "contact number",
        "personal contact", "emergency contact", "contact detail",
        "whatsapp number", "cell number",
    ],

    # personal info
    "personal": [
        "email address", "home address", "residential address",
        "personal address", "private address",
    ],

    # financial
    "financial": [
        "bank account", "account number", "ifsc code", "ifsc",
        "salary slip", "payslip", "pay slip",
    ],

    # identity
    "identity": [
        "aadhaar", "aadhaar number", "pan number", "pan card",
        "passport number", "voter id",
    ],

    # security
    "security": [
        "password", "api key", "secret key", "access token",
        "private key", "auth token", "otp", "pin number",
        "login password", "system password",
    ],
}

# Flat list for quick lookup
ALL_SENSITIVE_PHRASES = [
    phrase
    for phrases in SENSITIVE_PHRASES.values()
    for phrase in phrases
]


# ══════════════════════════════════════════════════════════════
# NUMERIC PATTERNS — always block
# ══════════════════════════════════════════════════════════════

BLOCKED_PATTERNS = [
    r"\b\d{12}\b",        # aadhaar (12 digits)
    r"\b\d{16}\b",        # credit/debit card (16 digits)
    r"\b[6-9]\d{9}\b",    # Indian mobile (starts 6-9, 10 digits)
]


# ══════════════════════════════════════════════════════════════
# MESSAGES — clear user-facing messages
# ══════════════════════════════════════════════════════════════

MESSAGES = {
    "sql"       : "❌ Write operations are not allowed. Only read (SELECT) queries are permitted.",
    "contact"   : "❌ Access to contact details is restricted.",
    "personal"  : "❌ Personal information cannot be shared.",
    "financial" : "❌ Financial account data access is restricted.",
    "identity"  : "❌ Sensitive identity information is not allowed.",
    "security"  : "❌ Security credentials cannot be accessed.",
    "numeric"   : "❌ Sensitive numeric information detected. Request blocked.",
    "default"   : "❌ Request blocked due to restricted content.",
}


# ══════════════════════════════════════════════════════════════
# PUBLIC — guard_input()
# ══════════════════════════════════════════════════════════════

def guard_input(question: str) -> dict:
    """
    Smart context-aware guardrail.

    Args:
        question: raw user question OR generated SQL string

    Returns:
        { "blocked": bool, "message": str, "reason": str }
    """
    if not question:
        return {"blocked": False, "message": "", "reason": ""}

    q = question.lower().strip()

    # ── 1. SQL Command Patterns ───────────────────────────────
    for pattern in SQL_COMMAND_PATTERNS:
        if re.search(pattern, q, re.IGNORECASE):
            print(f"   🚨 SQL command pattern matched: {pattern}")
            return {
                "blocked": True,
                "message": MESSAGES["sql"],
                "reason" : f"SQL command pattern: {pattern}",
            }

    # ── 2. Sensitive Phrases ──────────────────────────────────
    for phrase in ALL_SENSITIVE_PHRASES:
        if phrase in q:
            # find which category
            category = _get_category(phrase)
            print(f"   🚨 Sensitive phrase matched: '{phrase}' → {category}")
            return {
                "blocked": True,
                "message": MESSAGES.get(category, MESSAGES["default"]),
                "reason" : f"Sensitive phrase: {phrase}",
            }

    # ── 3. Numeric Patterns ───────────────────────────────────
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, q):
            print(f"   🚨 Numeric pattern matched: {pattern}")
            return {
                "blocked": True,
                "message": MESSAGES["numeric"],
                "reason" : f"Numeric pattern: {pattern}",
            }

    return {"blocked": False, "message": "", "reason": ""}


# ══════════════════════════════════════════════════════════════
# HELPER
# ══════════════════════════════════════════════════════════════

def _get_category(phrase: str) -> str:
    for category, phrases in SENSITIVE_PHRASES.items():
        if phrase in phrases:
            return category
    return "default"