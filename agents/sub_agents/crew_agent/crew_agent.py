"""
crew_agent.py
-------------
Crew Specialist — True LangGraph Agent.

This agent autonomously:
  1. Lists available tables (list_db_objects)
  2. Reads schema of relevant tables (read_object_definition)
  3. Checks real column values (get_sample_values)
  4. Discovers stored procedures (execute_sp list mode)
  5. Writes + executes SQL or SP (execute_sql / execute_sp)
  6. Retries/fixes on failure (max 3 attempts)

Tools used (crew_agent ONLY — no mixing):
  - list_db_objects
  - read_object_definition
  - get_sample_values
  - execute_sql
  - execute_sp

Flow:
  explore_node → plan_node → execute_node
                                  │
                            validate_node
                                  │
                            fix_node (retry)
                                  │
                            respond_node → END
"""

from dotenv import load_dotenv
load_dotenv()

import os
import re
import logging
from typing import Any, Dict, List, TypedDict

from langgraph.graph import StateGraph, END
from groq import Groq
from agents.memory.memory_manager import get_short_term
from agents.memory.feedback_manager import load_hints, build_hint_prompt

def load_system_prompt():
    base_dir    = os.path.dirname(__file__)
    prompt_path = os.path.join(base_dir, "prompts", "crew_system_prompt.txt")
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()


# ── Crew Agent Tools ONLY — no mixing ────────────────────────
from agents.sub_agents.crew_agent.tools import (
    list_db_objects,
    read_object_definition,
    get_sample_values,
    execute_sql,
    execute_sp,
)

logger      = logging.getLogger("crew_agent")
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
LLM_MODEL   = "llama-3.3-70b-versatile"

MAX_RETRIES = 3

# ─────────────────────────────────────────────────────────────
# SYSTEM PROMPT — loaded from file
# ─────────────────────────────────────────────────────────────
CREW_SYSTEM_PROMPT = load_system_prompt()


# ─────────────────────────────────────────────────────────────
# STATE
# ─────────────────────────────────────────────────────────────
class CrewAgentState(TypedDict):
    question     : str
    domain       : str
    tables       : List[str]
    schemas      : Dict[str, Any]
    all_schemas  : Dict[str, Any]   # full schema for column validation
    available_sps: Dict[str, Any]
    sql          : str
    result       : Dict[str, Any]
    is_valid     : bool
    error        : str
    retry_count  : int
    answer       : str
    fail_reason  : str              # 🔴 why agent failed: "max_retries" | "no_tables" | "validation_failed" | ""
    short_term   : List[Dict[str, str]]   # 🧠 memory
    hints        : List[Dict[str, Any]]   # 🧠 feedback

# ─────────────────────────────────────────────────────────────
# VALIDATORS (independent, no tool imports)
# ─────────────────────────────────────────────────────────────
def validate_aggregation(sql: str) -> None:
    """Raises if aggregation rules are violated."""
    sql_upper = sql.upper()
    has_group_by = "GROUP BY" in sql_upper
    has_distinct = "DISTINCT" in sql_upper

    # DISTINCT + GROUP BY together is always invalid
    if has_group_by and has_distinct:
        raise Exception("Aggregation error: DISTINCT not allowed with GROUP BY")

    # COUNT without GROUP BY is only invalid when other non-aggregated columns exist
    if "COUNT(" in sql_upper and not has_group_by:
        select_match = re.search(
            r"SELECT\s+(.*?)\s+FROM", sql, re.IGNORECASE | re.DOTALL
        )
        if select_match:
            select_clause = select_match.group(1)
            # Strip out all COUNT(...) and SUM(...) and AVG(...) expressions
            without_agg = re.sub(
                r"(COUNT|SUM|AVG|MIN|MAX)\s*\([^)]*\)\s*(?:AS\s+\w+)?",
                "", select_clause, flags=re.IGNORECASE
            ).strip().strip(",").strip()
            # If other bare columns remain → needs GROUP BY
            if without_agg:
                raise Exception(
                    "Aggregation error: COUNT with other non-aggregated columns requires GROUP BY"
                )

def validate_columns(sql: str, schemas: dict) -> None:
    """Raises if SQL contains columns not present in any known schema."""
    cols         = re.findall(r'\[([^\]]+)\]', sql)
    valid_cols   = set()
    valid_tables = set()

    for table, defn in schemas.items():
        valid_tables.add(table.lower())
        for col in defn.get("columns", []):
            valid_cols.add(col["name"].lower())

    for col in cols:
        col_lower = col.lower()
        if col_lower in valid_tables:
            continue
        if "." in col_lower:
            col_lower = col_lower.split(".")[-1]
        if col_lower not in valid_cols:
            raise Exception(f"Invalid column detected: [{col}]")

# ─────────────────────────────────────────────────────────────
# HELPER — extract WHERE clause from short-term memory
# ─────────────────────────────────────────────────────────────


def extract_where_clause(short_term):
    """
    Extracts WHERE clause from the LAST SQL in short-term memory.
    Only looks at the most recent assistant message with SQL.
    """
    import re
    for msg in reversed(short_term):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            # Only extract if SQL is present in this message
            if "[SQL used:" not in content:
                continue
            # Extract from SQL part only
            sql_match = re.search(r"\[SQL used: (.*?)\]", content, re.DOTALL)
            if sql_match:
                sql = sql_match.group(1)
                where_match = re.search(
                    r"WHERE\s+(.*?)(?:ORDER BY|GROUP BY|$)",
                    sql, re.IGNORECASE | re.DOTALL
                )
                if where_match:
                    return where_match.group(1).strip()
    return ""

# ─────────────────────────────────────────────────────────────
# FAILURE DETECTOR — plug-in, standalone, touch nothing else
# ─────────────────────────────────────────────────────────────

# Semantic entity map — maps user words to expected tables
ENTITY_MAP = {
    "salary"      : "PayRollReport",
    "earnings"    : "PayRollReport",
    "pay"         : "PayRollReport",
    "payroll"     : "PayRollReport",
    "tax"         : "PayRollReport",
    "rank"        : "AIX_CrewRanks",
    "designation" : "PayRoll_Designations",
    "roster"      : "Aix_CrewRoster",
    "schedule"    : "Aix_CrewRoster",
    "statistics"  : "AIX_CrewRosterStatistics",
    "base"        : "Aix_BaseCrewInfo",
    "crew"        : "Aix_BaseCrewInfo",
    "function"    : "AIX_CrewFunctions",
}

# Unsupported question patterns
UNSUPPORTED_PATTERNS = [
    "what is", "what are", "how does", "how do",
    "explain", "define", "tell me about",
    "why is", "why does", "difference between",
    "what does", "describe",
]

def failure_detector(state: CrewAgentState) -> tuple:
    """
    Plug-in failure detector — checks all 8 conditions in order.
    Returns (is_failed: bool, fail_reason: str)
    Call this from validate_node and fix_node only.
    Remove by deleting the call — nothing else changes.
    """
    question    = state.get("question", "").lower()
    sql         = state.get("sql", "").upper()
    error       = state.get("error", "")
    rows        = state.get("result", {}).get("rows", [])
    retry_count = state.get("retry_count", 0)

    # ── Layer 0 — Unsupported question type ──────────────────
    if any(pattern in question for pattern in UNSUPPORTED_PATTERNS):
        # Only fail if NO result came back
        # (some "what" questions still produce valid SQL)
        if not rows:
            print("   🔴 FAILURE DETECTOR: unsupported question type")
            return True, "unsupported_question"

    # ── Layer 2 — Fake / invalid SQL logic ───────────────────
    if "WHERE 1=0" in sql or "WHERE 0=1" in sql:
        print("   🔴 FAILURE DETECTOR: fake SQL logic detected")
        return True, "fake_sql_logic"

    # ── Layer 2 — Table mismatch via entity map ───────────────
    if sql and state.get("tables"):
        tables_used = [t.lower() for t in state.get("tables", [])]
        for keyword, expected_table in ENTITY_MAP.items():
            if keyword in question:
                if expected_table.lower() not in tables_used:
                    # Check if expected table was even available
                    all_tables = [t.lower() for t in state.get("all_schemas", {}).keys()]
                    if expected_table.lower() in all_tables:
                        print(f"   🔴 FAILURE DETECTOR: table mismatch — '{keyword}' expects '{expected_table}'")
                        return True, "table_mismatch"

    # ── Layer 3 — Retry exhausted ─────────────────────────────
    if retry_count >= MAX_RETRIES:
        print("   🔴 FAILURE DETECTOR: max retries exhausted")
        return True, "retry_exhausted"

    # ── Layer 3 — Hybrid empty result check ──────────────────
    if not rows:
        if retry_count > 0:
            # Had retries = something went wrong
            print("   🔴 FAILURE DETECTOR: 0 rows after retries")
            return True, "empty_after_retries"
        # retry_count = 0 + 0 rows = genuinely no data → VALID
        print("   ✅ FAILURE DETECTOR: 0 rows, no retries — valid empty result")
        return False, ""

    # ── Layer 3 — SQL execution error ────────────────────────
    if error and error != "empty_result":
        print(f"   🔴 FAILURE DETECTOR: SQL execution error — {error[:60]}")
        return True, "sql_execution_failure"

    # ── All checks passed ────────────────────────────────────
    print("   ✅ FAILURE DETECTOR: all checks passed")
    return False, ""

# ─────────────────────────────────────────────────────────────
# NODE 1 — EXPLORE
# ─────────────────────────────────────────────────────────────
def explore_node(state: CrewAgentState) -> CrewAgentState:
    print("\n" + "█" * 60)
    print("🔭 CREW NODE 1: EXPLORE")
    print("█" * 60)
    print(f"   Question : {state['question']}")

    # Tool 1: list tables
    all_tables = list_db_objects(state["domain"])
    if not all_tables:
        print("   ❌ No tables found for domain")
        state["error"] = "No tables available for crew domain."
        state["fail_reason"] = "no_tables"
        return state

    # Tool 2: read schemas
    schemas = {}
    for table in all_tables:
        definition = read_object_definition(table)
        if not definition.get("error"):
            schemas[table] = definition
        else:
            print(f"   ⚠️  Skipping '{table}': {definition['error']}")

    state["tables"]     = list(schemas.keys())
    state["schemas"]    = schemas
    state["all_schemas"] = schemas

    # Tool 5: discover SPs
    sp_result              = execute_sp("list", {})
    state["available_sps"] = sp_result.get("available_sps", {})
    print(f"   ✅ SPs discovered: {list(state['available_sps'].keys())}")

    print(f"   ✅ EXPLORE COMPLETE — Tables: {state['tables']}")
    return state


# ─────────────────────────────────────────────────────────────
# NODE 2 — PLAN
# ─────────────────────────────────────────────────────────────
def plan_node(state: CrewAgentState) -> CrewAgentState:
    print("\n" + "█" * 60)
    print("🧠 CREW NODE 2: PLAN")
    print("█" * 60)

    if not state.get("tables"):
        state["error"] = "No tables available to plan SQL."
        return state

    # ── Build schema context ──────────────────────────────────
    schema_context = ""
    for table, defn in state["schemas"].items():
        cols      = defn.get("columns", [])
        col_lines = "\n".join(
            f"    - [{c['name']}] ({c['data_type']}, nullable={c['nullable']})"
            for c in cols
        )
        samples     = defn.get("sample_data", [])
        sample_text = ""
        if samples:
            sample_text = "\n  Sample rows:\n"
            for row in samples[:2]:
                sample_text += f"    {row}\n"

        schema_context += (
            f"\nTable: [{table}]\n"
            f"Columns:\n{col_lines}\n"
            f"{sample_text}"
            f"{'-' * 50}\n"
        )

    # ── Sample value hints ────────────────────────────────────
    question_lower = state["question"].lower()
    sample_hints   = ""
    if "base" in question_lower and "Aix_BaseCrewInfo" in state["schemas"]:
        vals = get_sample_values("Aix_BaseCrewInfo", "Base", limit=15)
        if vals:
            sample_hints += f"\nDistinct values in [Aix_BaseCrewInfo].[Base]: {vals}"

    if any(w in question_lower for w in ["fleet", "a320", "aircraft", "type"]) and "Aix_BaseCrewInfo" in state["schemas"]:
        vals = get_sample_values("Aix_BaseCrewInfo", "Fleet", limit=15)
        if vals:
            sample_hints += f"\nDistinct values in [Aix_BaseCrewInfo].[Fleet]: {vals}"
    if sample_hints:
        schema_context += f"\n\nSAMPLE VALUE HINTS:{sample_hints}\n"

    # ── SP context (built separately, always outside if) ─────
    sp_context = ""
    if state.get("available_sps"):
        sp_context = "\n\nAVAILABLE STORED PROCEDURES:\n"
        for sp_name, sp_info in state["available_sps"].items():
            sp_context += (
                f"- {sp_name}: {sp_info['description']}\n"
                f"  params : {sp_info['params']}\n"
                f"  example: {sp_info['example']}\n"
            )
        sp_context += (
            "\nIF the question is better answered by a stored procedure "
            "(e.g. personal profile, flying summary, roster report by staff ID):\n"
            "→ Return ONLY: USE_SP:<sp_name>:<param_name>=<value>\n"
            "→ Example   : USE_SP:getpersonalprofile:staffid=85005276\n"
            "→ No params : USE_SP:GETPILOTCOMPLETEDATA2:\n"
            "OTHERWISE   : return normal SQL SELECT query\n"
        )

    # ── Inject session context prompt ─────────────────────────
    from agents.memory.memory_manager import get_context_prompt

    # Extract context safely from short_term messages
    _last_base = ""
    _last_rank = ""
    for m in reversed(state.get("short_term", [])):
        content = m.get("content", "")
        if not _last_base and "base=" in content:
            try:
                _last_base = content.split("base=")[1].split(",")[0].split("]")[0].strip()
            except Exception:
                pass
        if not _last_rank and "rank=" in content:
            try:
                _last_rank = content.split("rank=")[1].split(",")[0].split("]")[0].strip()
            except Exception:
                pass

    context_text = get_context_prompt({
        "last_context": {
            "last_base": _last_base,
            "last_rank": _last_rank,
        }
    })

    if context_text:
        print(f"   🧠 Context prompt injected into plan")
    else:
        context_text = ""   # ← always defined, never unbound

    # ── User prompt (always built, outside all if blocks) ────
    user_prompt = (
        f"{context_text}"
        f"User question:\n{state['question'].strip()}\n\n"
        f"Available tables and schemas:\n{schema_context}"
        f"{sp_context}\n\n"
        f"Write a single SQL Server SELECT query OR a USE_SP instruction.\n"
        f"Return ONLY the SQL or USE_SP line — no explanation, no markdown.\n"
        f"RULES:\n"
        f"- If question asks HOW MANY / COUNT / TOTAL → use SELECT COUNT(*) with no other columns, no TOP, no DISTINCT\n"
        f"- If question asks to LIST / SHOW / GET → use SELECT DISTINCT TOP 100\n"
        f"- Never mix COUNT with other columns unless GROUP BY is present\n"
        f"- Rank column is [RankCode] NOT [Rank] NOT [CurrentRank] — always use [RankCode]\n"
        f"- StaffNumber join: LTRIM(RTRIM([Aix_BaseCrewInfo].[ID])) = LTRIM(RTRIM([AIX_CrewInfo].[StaffNumber]))\n"
    )
    


    # ── Inject previous context if continuation query ─────────
    where_clause = extract_where_clause(state.get("short_term", []))
    continuation_words = ["their", "those", "same", "only", "top", "limit", "them"]
    if any(w in question_lower for w in continuation_words) and where_clause:
        user_prompt = (
            f"⚠️ CONTINUATION QUERY — The user is referring to results from the PREVIOUS question.\n"
            f"You MUST apply this exact WHERE clause from the previous query:\n"
            f"WHERE {where_clause}\n\n"
            f"Do NOT invent new filters. Do NOT use Base, CrewType, or any other "
            f"filter unless it was already in the WHERE clause above.\n\n"
        ) + user_prompt
        print(f"   🧠 Continuation detected — injecting WHERE: {where_clause}")

    print("   🤖 Calling LLM...")

    try:
        # ── Build messages ────────────────────────────────────
        short_term = state.get("short_term", [])

        # Load feedback hints
        hints     = load_hints(state["question"], domain=state.get("domain", "crew"))
        hint_text = build_hint_prompt(hints)

        messages = []

        # 1. System prompt
        messages.append({
            "role"   : "system",
            "content": CREW_SYSTEM_PROMPT,
        })

        # 2. Short-term memory (last N messages)
        messages.extend(short_term)

        # 3. Feedback hints (if any)
        if hint_text:
            messages.append({
                "role"   : "system",
                "content": hint_text,
            })

        # 4. Current user question
        messages.append({
            "role"   : "user",
            "content": user_prompt,
        })

        # ── LLM call ─────────────────────────────────────────
        resp = groq_client.chat.completions.create(
            model=LLM_MODEL,
            temperature=0,
            messages=messages,
            max_tokens=500,
        )
        raw = resp.choices[0].message.content.strip()
        print(f"   🤖 LLM raw (first 300): {raw[:300]}")

        # ── SP instruction ────────────────────────────────────
        if raw.upper().startswith("USE_SP:"):
            state["sql"]   = raw.strip()
            state["error"] = ""
            print(f"   ✅ SP instruction: {raw.strip()}")
            return state

        # ── SQL query ─────────────────────────────────────────
        sql = _extract_sql(raw)
        if not sql:
            print("   ❌ Could not extract SQL")
            state["error"] = "SQL generation failed."
            return state

        # Post-process: enforce aggregation + DISTINCT rules
        sql = _clean_sql(sql)

        state["sql"]   = sql
        state["error"] = ""
        print(f"   ✅ SQL planned:\n   {sql[:300]}")

    except Exception as exc:
        print(f"   ❌ LLM call failed: {exc}")
        state["error"] = f"LLM failed: {exc}"

    return state


# ─────────────────────────────────────────────────────────────
# NODE 3 — EXECUTE
# ─────────────────────────────────────────────────────────────
def execute_node(state: CrewAgentState) -> CrewAgentState:
    print("\n" + "█" * 60)
    print("⚡ CREW NODE 3: EXECUTE")
    print("█" * 60)

    if not state.get("sql"):
        print("   ❌ No SQL/SP to execute")
        state["error"] = state.get("error") or "No SQL available."
        return state

    if "all_schemas" not in state:
        print("   ❌ all_schemas missing in state")
        state["error"] = "all_schemas missing"
        return state


    # SP Route
    if state["sql"].upper().startswith("USE_SP:"):
        print("   ⚙️  SP route detected")
        try:
            parts   = state["sql"].strip().split(":", 2)
            sp_name = parts[1].strip() if len(parts) > 1 else ""
            params  = {}

            if len(parts) > 2 and parts[2].strip():
                for pair in parts[2].split(","):
                    if "=" in pair:
                        k, v = pair.strip().split("=", 1)
                        params[k.strip()] = v.strip()

            print(f"   SP: {sp_name} | Params: {params}")

            if not sp_name:
                state["error"] = "SP name missing."
                return state

            result = execute_sp(sp_name, params)

        except Exception as exc:
            print(f"   ❌ SP failed: {exc}")
            state["error"] = f"SP execution failed: {exc}"
            return state

    # SQL Route
    else:
        # Validate aggregation rules
        try:
            validate_aggregation(state["sql"])
        except Exception as e:
            print(f"   ❌ Aggregation validation failed: {e}")
            state["error"] = str(e)
            return state

        # Validate columns exist in schema
        try:
            validate_columns(state["sql"], state["all_schemas"])
        except Exception as e:
            print(f"   ❌ Column validation failed: {e}")
            state["error"] = str(e)
            return state

        result = execute_sql(state["sql"])

    # Handle result (same for both routes)
    if result.get("status") == "success" and result.get("row_count", 0) > 0:
        state["result"]   = result
        state["error"]    = ""
        state["is_valid"] = True
        print(f"   ✅ {result['row_count']} rows returned")

    elif result.get("status") == "success" and result.get("row_count", 0) == 0:
        # Empty result is a VALID outcome — do NOT retry or fix
        state["result"]   = {"columns": result.get("columns", []), "rows": [], "row_count": 0}
        state["error"]    = ""
        state["is_valid"] = True
        print("   ✅ 0 rows returned — valid outcome, no data found for this query")

    else:
        state["error"]    = result.get("error", "Unknown error.")
        state["is_valid"] = False
        print(f"   ❌ Failed: {state['error']}")

    return state


# ─────────────────────────────────────────────────────────────
# NODE 4 — VALIDATE
# ─────────────────────────────────────────────────────────────
def validate_node(state: CrewAgentState) -> CrewAgentState:
    print("\n" + "█" * 60)
    print("✅ CREW NODE 4: VALIDATE")
    print("█" * 60)

    # ── FAILURE DETECTOR plug-in ──────────────────────────────
    failed, reason = failure_detector(state)
    if failed:
        state["is_valid"]    = False
        state["fail_reason"] = reason
        print(f"   🔴 validate_node: failure detected — {reason}")
        return state

    # ERROR → fix
    if state.get("error"):
        state["is_valid"] = False
        return state

    # EMPTY → valid
    if state.get("result", {}).get("row_count", 0) == 0:
        state["is_valid"] = True
        return state

    rows    = state["result"]["rows"]
    columns = state["result"]["columns"]
    print(f"   Rows: {len(rows)} | Columns: {columns}")

    question_lower = state["question"].lower()
    if any(w in question_lower for w in ["maximum", "minimum", "max", "min", "highest", "lowest", "top 1"]):
        if len(rows) > 1:
            state["is_valid"] = False
            state["error"]    = "MAX/MIN query returned multiple rows. Use TOP 1 with ORDER BY."
            return state

    prompt = f"""
You are validating whether a SQL query result correctly answers
the user question.

Question: {state['question']}
SQL used: {state['sql']}
Columns returned: {columns}
Sample data (first 3 rows): {str(rows[:3])}
Total rows: {len(rows)}

CHECK THESE IN ORDER:
1. Do the returned columns match what the question is asking for?
2. Does the SQL have the right filters for the question
   (e.g. if question says 'mumbai', is Base = 'BOM' in SQL)?
3. Is the data logically relevant to the question?
4. If question asks for rank, are rank-related columns present?
5. If question asks for names, are name columns present?

Reply ONLY: CORRECT or WRONG
If WRONG → add brief reason after colon.
Example: WRONG: question asked for rank but only ID returned
"""
    try:
        resp    = groq_client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=30,
        )
        verdict = resp.choices[0].message.content.strip().upper()
        print(f"   🤖 Verdict: {verdict}")

        if verdict.startswith("WRONG"):
            reason            = verdict.split(":", 1)[1].strip() if ":" in verdict else "Data does not match question."
            state["is_valid"] = False
            state["error"]    = reason
            state["fail_reason"] = "validation_failed"
        else:
            state["is_valid"] = True
            print("   ✅ CORRECT")

    except Exception as exc:
        print(f"   ⚠️  Validation failed: {exc} — assuming CORRECT")
        state["is_valid"] = True

    return state


# ─────────────────────────────────────────────────────────────
# NODE 5 — FIX
# ─────────────────────────────────────────────────────────────
def fix_node(state: CrewAgentState) -> CrewAgentState:
    print("\n" + "█" * 60)
    print("🔧 CREW NODE 5: FIX")
    print("█" * 60)

    retry_count = state.get("retry_count", 0)
    print(f"   Retry : {retry_count + 1} / {MAX_RETRIES}")

    if retry_count >= MAX_RETRIES:
        print("   ❌ Max retries reached")
        state["result"] = {}
        # ── FAILURE DETECTOR plug-in ──────────────────────────
        failed, reason = failure_detector(state)
        state["fail_reason"] = reason if failed else "retry_exhausted"
        print(f"   🔴 fix_node: fail_reason = {state['fail_reason']}")
        return state

    state["retry_count"] = retry_count + 1

    # SP failures cannot be fixed by SQL rewrite
    if state.get("sql", "").upper().startswith("USE_SP:"):
        print("   ⚠️  SP failed — cannot fix, exiting")
        state["result"] = {}
        return state

    fix_prompt = f"""
Fix this SQL Server query.

Question: {state['question']}
Current SQL: {state['sql']}
Error / reason: {state.get('error', '')}

CREW RULES:
- Active crew    → employmentEnd = '2099-12-31'
- Current rank   → RankEnd = '2099-12-31'
- LTRIM(RTRIM()) on StaffNumber in joins
- SELECT DISTINCT TOP 100 for non-aggregation queries
- For COUNT/SUM/AVG → remove DISTINCT, keep GROUP BY
- Use [square brackets] on all names
- If empty result → relax WHERE filters
- If MAX/MIN → use TOP 1 with ORDER BY
- NEVER use CONVERT on employmentEnd
- Bridge: Aix_BaseCrewInfo → AIX_CrewInfo → AIX_CrewFunctions

COLUMN NAME RULES (CRITICAL):
- Rank column is [RankCode] NOT [Rank] NOT [CurrentRank] NOT [RankEnd]
- Use [RankCode] in SELECT and WHERE for rank queries
- StaffNumber join: LTRIM(RTRIM([Aix_BaseCrewInfo].[ID])) = LTRIM(RTRIM([AIX_CrewInfo].[StaffNumber]))

Return ONLY the fixed SQL query.
"""
    try:
        resp      = groq_client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": fix_prompt}],
            temperature=0,
            max_tokens=400,
        )
        fixed_sql = resp.choices[0].message.content.strip()

        if "```" in fixed_sql:
            m = re.search(r"```(?:sql)?(.*?)```", fixed_sql, re.DOTALL)
            if m:
                fixed_sql = m.group(1).strip()

        if fixed_sql.lower().startswith("select"):
            # Apply cleanup to fixed SQL too
            fixed_sql      = _clean_sql(fixed_sql)
            state["sql"]   = fixed_sql
            state["error"] = ""
            print("   ✅ SQL fixed")
        else:
            print("   ⚠️  Fix did not return valid SELECT")

    except Exception as exc:
        print(f"   ❌ Fix LLM failed: {exc}")

    return state


# ─────────────────────────────────────────────────────────────
# NODE 6 — RESPOND
# ─────────────────────────────────────────────────────────────
def respond_node(state: CrewAgentState) -> CrewAgentState:
    print("\n" + "█" * 60)
    print("💬 CREW NODE 6: RESPOND")
    print("█" * 60)

    if not state.get("result", {}).get("rows"):
        crew_id = ""
        sql = state.get("sql", "")

        id_match = re.search(r"(?:ID|StaffNumber)\s*=\s*'?(\d+)'?", sql, re.IGNORECASE)
        if id_match:
            crew_id = id_match.group(1)

        if crew_id:
            state["answer"] = f"No data found for crew ID {crew_id}. Please verify the ID is correct."
        else:
            state["answer"] = "No records found for your request."

        return state

    rows    = state["result"]["rows"]
    columns = state["result"]["columns"]

    # ── Clean None values before sending to LLM and frontend ─
    rows = [
        [None if str(v) == "None" else v for v in row]
        for row in rows
    ]
    state["result"]["rows"] = rows

    # ── COUNT result — single number answer, no LLM needed ───
    is_count_result = (
        len(rows) == 1
        and len(columns) == 1
        and str(rows[0][0]).lstrip("-").isdigit()
    )
    if is_count_result:
        count_value     = rows[0][0]
        state["answer"] = f"There are **{count_value}** crew members matching your query."
        print(f"   ✅ Count answer: {count_value}")
        return state

    prompt = f"""
You have real crew data from Air India Express database.

Question asked: {state['question']}
Total rows returned: {len(rows)}
Column names: {columns}
First 5 rows of actual data: {str(rows[:5])}

RULES:
1. Use the actual data values shown above
2. Write 1-2 clear sentences summarizing the key finding
3. If total rows = 100, mention there may be more beyond the limit shown
4. Mention actual values if helpful
5. Do NOT say data is missing — it is right above
6. Do NOT hallucinate — use only what is shown
7. Do NOT say "at least X" — state total rows returned directly
"""
    try:
        resp            = groq_client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=150,
        )
        state["answer"] = resp.choices[0].message.content.strip()
        print(f"   ✅ Answer: {state['answer']}")

    except Exception as exc:
        print(f"   ❌ Responder failed: {exc}")
        state["answer"] = f"Found {len(rows)} records. Please check the data returned."

    return state


# ─────────────────────────────────────────────────────────────
# ROUTERS
# ─────────────────────────────────────────────────────────────
def after_explore(state: CrewAgentState) -> str:
    if state.get("error"):
        print("   ↪️  after_explore → end")
        return "end"
    print("   ↪️  after_explore → plan")
    return "plan"


def after_execute(state: CrewAgentState) -> str:
    if state.get("error"):
        print(f"   ↪️  after_execute → fix")
        return "fix"
    print("   ↪️  after_execute → validate")
    return "validate"


def after_validate(state: CrewAgentState) -> str:
    decision = "respond" if state.get("is_valid") else "fix"
    print(f"   ↪️  after_validate → {decision}")
    return decision


def after_fix(state: CrewAgentState) -> str:
    if state.get("result", {}).get("rows") and state.get("is_valid"):
        print("   ↪️  after_fix → respond")
        return "respond"
    if state.get("retry_count", 0) >= MAX_RETRIES:
        print("   ↪️  after_fix → respond (max retries — carry fail_reason)")
        return "respond"   # ← was "end", now goes through respond so state is returned cleanly
    print("   ↪️  after_fix → execute")
    return "execute"

# ─────────────────────────────────────────────────────────────
# GRAPH ASSEMBLY
# ─────────────────────────────────────────────────────────────
_builder = StateGraph(CrewAgentState)

_builder.add_node("explore" , explore_node)
_builder.add_node("plan"    , plan_node)
_builder.add_node("execute" , execute_node)
_builder.add_node("validate", validate_node)
_builder.add_node("fix"     , fix_node)
_builder.add_node("respond" , respond_node)

_builder.set_entry_point("explore")

_builder.add_conditional_edges("explore" , after_explore,  {"plan": "plan", "end": END})
_builder.add_edge("plan", "execute")
_builder.add_conditional_edges("execute" , after_execute,  {"validate": "validate", "fix": "fix"})
_builder.add_conditional_edges("validate", after_validate, {"respond": "respond", "fix": "fix"})
_builder.add_conditional_edges("fix"     , after_fix,      {"execute": "execute", "respond": "respond", "end": END})
_builder.add_edge("respond", END)

crew_graph = _builder.compile()


# ─────────────────────────────────────────────────────────────
# PUBLIC ENTRY POINT — called by orchestrator ONLY
# ─────────────────────────────────────────────────────────────
def run_crew_agent(question: str, domain: str = "crew", short_term=None) -> dict:
    print("\n" + "█" * 60)
    print("🚀 CREW AGENT START")
    print("█" * 60)
    print(f"   Question : {question}")
    print(f"   Domain   : {domain}")


    result = crew_graph.invoke({
        "question"     : question,
        "domain"       : domain,
        "tables"       : [],
        "schemas"      : {},
        "all_schemas"  : {},        # ← fixed: included in initial state
        "available_sps": {},
        "sql"          : "",
        "result"       : {},
        "is_valid"     : False,
        "error"        : "",
        "retry_count"  : 0,
        "answer"       : "",
        "fail_reason"  : "", # 🔴 reset on every new run
        "short_term"  : short_term or [],
        "hints"       : [],
    })

    print("\n" + "█" * 60)
    print("🏁 CREW AGENT COMPLETE")
    print("█" * 60)
    print(f"   SQL    : {result.get('sql', '')[:150]}")
    print(f"   Rows   : {len(result.get('result', {}).get('rows', []))}")
    print(f"   Answer : {result.get('answer', '')[:100]}")
    print("█" * 60 + "\n")

    rows        = result.get("result", {}).get("rows", [])
    fail_reason = result.get("fail_reason", "")

    # 🔍 DEBUG
    print(f"   🔍 DEBUG: rows={len(rows)} | fail_reason='{fail_reason}'")

    # ❌ REAL FAILURE — fail_reason takes priority over rows
    # Even if rows exist from a previous attempt, if agent failed → fallback
    if fail_reason:
        print(f"   ❌ Agent failed — reason: {fail_reason}")
        return {
            "status"     : "fail",
            "fail_reason": fail_reason,
            "answer"     : result.get("answer", "No data found."),
            "sql"        : result.get("sql", ""),
            "columns"    : [],
            "rows"       : [],
            "domain"     : domain,
        }

    # ✅ REAL SUCCESS — rows returned and no failure
    if rows:
        return {
            "status"     : "success",
            "fail_reason": "",
            "answer"     : result.get("answer", ""),
            "sql"        : result.get("sql", ""),
            "columns"    : result.get("result", {}).get("columns", []),
            "rows"       : rows,
            "domain"     : domain,
        }

    # ✅ VALID 0 ROWS — query worked, DB just has no data
    return {
        "status"     : "success",
        "fail_reason": "",
        "answer"     : result.get("answer", "No records found."),
        "sql"        : result.get("sql", ""),
        "columns"    : [],
        "rows"       : [],
        "domain"     : domain,
    }
# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────
def _clean_sql(sql: str) -> str:
    """
    Post-process SQL to enforce rules:
    1. Remove DISTINCT when GROUP BY is present (aggregation queries)
    2. Keep DISTINCT for non-aggregation queries
    """
    if not sql:
        return sql

    upper = sql.upper()

    has_group_by = "GROUP BY" in upper

    if has_group_by:
        # If it generated DISTINCT TOP 100 or TOP 100, remove the TOP 100 default limit
        sql = re.sub(r"SELECT\s+DISTINCT\s+TOP\s+100\s+", "SELECT ", sql, flags=re.IGNORECASE)
        sql = re.sub(r"SELECT\s+TOP\s+100\s+", "SELECT ", sql, flags=re.IGNORECASE)
        
        if "DISTINCT" in sql.upper():
            # Remove DISTINCT TOP N → TOP N
            sql = re.sub(r"SELECT\s+DISTINCT\s+TOP\s+(\d+)", r"SELECT TOP \1", sql, flags=re.IGNORECASE)
            # Remove leftover DISTINCT
            sql = re.sub(r"SELECT\s+DISTINCT\s+", "SELECT ", sql, flags=re.IGNORECASE)
            print("   🧹 Cleaned: removed DISTINCT from aggregation query")
        
        # Log if we cleaned up TOP 100
        if upper != sql.upper():
            print("   🧹 Cleaned: removed invalid defaults (DISTINCT / TOP 100) from aggregation query")

    print(f"   ✅ SQL after cleanup:\n   {sql[:300]}")
    return sql


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