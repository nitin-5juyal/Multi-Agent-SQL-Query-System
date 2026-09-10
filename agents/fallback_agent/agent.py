"""
agent.py
--------
LangGraph SQL Agent — fully autonomous LLM decision making.

Flow:
    router_node → agent_node → schema_node → executor_node
                                                   │
                                             validator_node
                                                   │
                                             error_fix_node
                                                   │
                                             responder_node → END
"""

from dotenv import load_dotenv
load_dotenv()

import os
import re
import logging
from typing import TypedDict, List

from langgraph.graph import StateGraph, END
from groq import Groq

from agents.router                import classify_intent, classify_domain
from agents.fallback_agent.tools.table_registry  import get_domain_tables
from agents.fallback_agent.tools.table_selector  import select_tables
from agents.fallback_agent.tools.query_generator import generate_sql
from agents.fallback_agent.tools.validator       import validate_and_execute
from agents.general_agent         import handle_general

logger      = logging.getLogger("agent")
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
LLM_MODEL   = "llama-3.3-70b-versatile"


# ═══════════════════════════════════════════════
# STATE
# ═══════════════════════════════════════════════
class AgentState(TypedDict):
    messages   : List
    question   : str
    intent     : str
    domain     : str
    schema     : str
    sql        : str
    tables     : List[str]
    result     : dict
    is_valid   : bool
    error      : str
    retry_count: int


# ═══════════════════════════════════════════════
# 1. ROUTER NODE
# ═══════════════════════════════════════════════
def router_node(state: AgentState) -> AgentState:
    intent = classify_intent(state["question"])
    state["intent"] = intent
    if intent == "SQL":
        # use pre-classified domain if passed in
        state["domain"] = state.get("domain") or classify_domain(state["question"])
    else:
        state["domain"] = "general"
    return state


# ═══════════════════════════════════════════════
# 2. AGENT NODE
# ═══════════════════════════════════════════════
def agent_node(state: AgentState) -> AgentState:
    print("\n" + "█"*60)
    print("🧠 NODE: AGENT (LLM Brain)")
    print("█"*60)
    print("   LLM deciding next action...")
    print(f"   Messages in context: {len(state['messages'])}")

    response = groq_client.chat.completions.create(
        model=LLM_MODEL,
        messages=state["messages"][-6:],
        temperature=0,
        max_tokens=50,
    )
    reply = response.choices[0].message.content.strip()
    print(f"   🤖 LLM output: '{reply}'")

    if "get_schema" not in reply.lower():
        print("   ⚠️  LLM tried to answer directly — BLOCKED, forcing get_schema")
        state["messages"].append({
            "role": "system",
            "content": "You MUST output only: get_schema"
        })
        return state

    print("   ✅ LLM correctly said get_schema → proceeding to schema_node")
    state["messages"].append({"role": "assistant", "content": reply})
    return state


# ═══════════════════════════════════════════════
# 3. SCHEMA NODE
# ═══════════════════════════════════════════════
def schema_node(state: AgentState) -> AgentState:
    print("\n" + "█"*60)
    print("📋 NODE: SCHEMA (Domain Boundary + Table Select + SQL Gen)")
    print("█"*60)
    print(f"   Question : {state['question']}")
    print(f"   Domain   : {state['domain']}")

    # Step 1: get domain boundary from registry
    print("\n" + "─"*60)
    print("🗄️  STEP 3 — REGISTRY LOOKUP")
    print("─"*60)
    allowed_tables = get_domain_tables(state["domain"])

    if allowed_tables:
        print(f"   ✅ Domain boundary set: {len(allowed_tables)} tables allowed")
    else:
        print("   🌐 Domain is 'general' — no boundary, all tables in scope")

    # Step 2: LLM picks relevant tables within boundary
    tables = select_tables(
        query          = state["question"],
        allowed_tables = allowed_tables if allowed_tables else None,
    )
    state["tables"] = tables

    if not tables:
        print("   ❌ No tables selected — cannot generate SQL")
        state["error"] = "No relevant tables found for this question."
        return state

    # Step 3: LLM generates SQL
    sql = generate_sql(state["question"], tables)
    state["sql"] = sql

    if not sql:
        print("   ❌ SQL generation failed")
        state["error"] = "SQL generation failed."
        return state

    state["messages"].append({
        "role": "user",
        "content": f"SQL generated: {sql}"
    })

    print(f"\n   ✅ SCHEMA NODE COMPLETE")
    print(f"   Tables : {tables}")
    print(f"   SQL    : {sql[:150]}")
    return state


# ═══════════════════════════════════════════════
# 4. EXECUTOR NODE
# ═══════════════════════════════════════════════
# def executor_node(state: AgentState) -> AgentState:
#     print("\n" + "█"*60)
#     print("⚡ NODE: EXECUTOR")
#     print("█"*60)

#     if not state.get("sql"):
#         print("   ❌ No SQL in state — cannot execute")
#         state["error"] = state.get("error") or "No SQL to execute."
#         return state

#     print(f"   SQL: {state['sql'][:200]}")

#     result = validate_and_execute(state["sql"])

#     if result["status"] == "success" and result["row_count"] > 0:
#         state["result"] = {
#             "columns": result["columns"],
#             "rows"   : [list(r.values()) for r in result["data"]],
#         }
#         state["error"] = ""
#         print(f"\n   ✅ EXECUTOR SUCCESS: {result['row_count']} rows returned")
#         print(f"   Columns: {result['columns']}")

#     elif result["status"] == "success" and result["row_count"] == 0:
#         state["error"]    = "empty_result"
#         state["is_valid"] = False
#         print("   ⚠️  SQL ran successfully but returned 0 rows")

#     else:
#         state["error"] = result.get("error", "Unknown SQL error.")
#         print(f"   ❌ EXECUTOR FAILED: {state['error']}")

#     return state

def executor_node(state: AgentState) -> AgentState:
    print("\n" + "█"*60)
    print("⚡ NODE: EXECUTOR")
    print("█"*60)

    if not state.get("sql"):
        print("   ❌ No SQL in state — cannot execute")
        state["error"] = state.get("error") or "No SQL to execute."
        return state

    print(f"   SQL: {state['sql'][:200]}")

    result = validate_and_execute(state["sql"])

    # 🟢 SUCCESS WITH DATA
    if result["status"] == "success" and result["row_count"] > 0:
        state["result"] = {
            "columns": result["columns"],
            "rows": [list(r.values()) for r in result["data"]],
        }
        state["error"] = ""
        state["is_valid"] = True
        print(f"\n   ✅ EXECUTOR SUCCESS: {result['row_count']} rows returned")
        print(f"   Columns: {result['columns']}")

    # 🟢 SUCCESS BUT NO DATA (IMPORTANT FIX)
    elif result["status"] == "success" and result["row_count"] == 0:
        state["error"] = "empty_result"
        state["result"] = {
            "columns": result.get("columns", []),
            "rows": []
        }
        state["is_valid"] = True   # ✅ FIXED
        print("   ⚠️  SQL ran successfully but returned 0 rows")

    # 🔴 REAL ERROR
    else:
        state["error"] = result.get("error", "Unknown SQL error.")
        state["is_valid"] = False
        print(f"   ❌ EXECUTOR FAILED: {state['error']}")

    return state
# ═══════════════════════════════════════════════
# 5. VALIDATOR NODE
# ═══════════════════════════════════════════════
# def validator_node(state: AgentState) -> AgentState:
#     print("\n" + "█"*60)
#     print("✅ NODE: VALIDATOR (LLM checks result quality)")
#     print("█"*60)

#     # Early exit for empty result
#     if state.get("error") == "empty_result":
#         print("   ⚠️  Empty result detected — marking invalid, routing to error_fix")
#         state["is_valid"] = False
#         return state

#     # Skip if error or no data
#     if state.get("error") or not state.get("result", {}).get("rows"):
#         print("   ⚠️  No data to validate — marking invalid")
#         state["is_valid"] = False
#         return state

#     rows     = state["result"]["rows"]
#     columns  = state["result"]["columns"]
#     question = state["question"].lower()

#     print(f"   Rows to validate: {len(rows)}")
#     print(f"   Columns: {columns}")

#     # MAX/MIN rule
#     if any(w in question for w in ["maximum", "minimum", "max", "min", "highest", "lowest", "top 1"]):
#         if len(rows) > 1:
#             print(f"   ❌ MAX/MIN question but got {len(rows)} rows → invalid")
#             state["is_valid"] = False
#             state["error"]    = "MAX/MIN query returned multiple rows. Use TOP 1 with ORDER BY."
#             return state

#     print("   🤖 Calling LLM to validate result quality...")

#     prompt = f"""
# Question: {state['question']}
# Columns returned: {columns}
# Sample data (first 3 rows): {str(rows[:3])}
# Total rows: {len(rows)}

# VALIDATION RULES:
# 1. If data has columns relevant to the question → CORRECT
# 2. If filter was applied (rank, base, etc.) → check WHERE was likely applied
# 3. Only say WRONG if data is completely unrelated to the question
# 4. Do NOT require columns that were not asked for

# Reply ONLY: CORRECT or WRONG
# If WRONG → add brief reason after colon.
# """
#     try:
#         resp    = groq_client.chat.completions.create(
#             model=LLM_MODEL,
#             messages=[{"role": "user", "content": prompt}],
#             temperature=0,
#             max_tokens=30,
#         )
#         verdict = resp.choices[0].message.content.strip().upper()
#         print(f"   🤖 LLM verdict: {verdict}")

#         if verdict.startswith("WRONG"):
#             reason            = verdict.split(":", 1)[1].strip() if ":" in verdict else "Data does not match question."
#             state["is_valid"] = False
#             state["error"]    = reason
#             print(f"   ❌ VALIDATOR: data is WRONG — reason: {reason}")
#         else:
#             state["is_valid"] = True
#             print("   ✅ VALIDATOR: data is CORRECT")

#     except Exception as exc:
#         print(f"   ⚠️  LLM validation failed: {exc} — assuming CORRECT")
#         state["is_valid"] = True

#     return state

def validator_node(state: AgentState) -> AgentState:
    print("\n" + "█"*60)
    print("✅ NODE: VALIDATOR (LLM checks result quality)")
    print("█"*60)

    # 🟢 EMPTY RESULT → VALID (IMPORTANT FIX)
    if state.get("error") == "empty_result":
        print("   ⚠️  Empty result detected — VALID case, skipping validation")
        state["is_valid"] = True
        return state

    # 🔴 REAL ERROR → INVALID
    if state.get("error"):
        print("   ❌ Error present — marking invalid")
        state["is_valid"] = False
        return state

    # ── Clear stale rows if result is invalid ────────────────
    if not state.get("is_valid") and state.get("result", {}).get("rows"):
        print("   🧹 Clearing stale rows — result marked invalid")
        state["result"] = {}

    # 🔴 NO DATA STRUCTURE
    if not state.get("result", {}).get("rows"):
        print("   ⚠️  No rows found — marking valid (safe fallback)")
        state["is_valid"] = True
        return state

    rows     = state["result"]["rows"]
    columns  = state["result"]["columns"]
    question = state["question"].lower()

    print(f"   Rows to validate: {len(rows)}")
    print(f"   Columns: {columns}")

    # 🟢 MAX/MIN rule
    if any(w in question for w in ["maximum", "minimum", "max", "min", "highest", "lowest", "top 1"]):
        if len(rows) > 1:
            print(f"   ❌ MAX/MIN question but got {len(rows)} rows → invalid")
            state["is_valid"] = False
            state["error"]    = "MAX/MIN query returned multiple rows. Use TOP 1 with ORDER BY."
            return state

    print("   🤖 Calling LLM to validate result quality...")

    prompt = f"""
Question: {state['question']}
Columns returned: {columns}
Sample data (first 3 rows): {str(rows[:3])}
Total rows: {len(rows)}

VALIDATION RULES:
1. If data has columns relevant to the question → CORRECT
2. If filter was applied (rank, base, etc.) → check WHERE was likely applied
3. Only say WRONG if data is completely unrelated to the question
4. Do NOT require columns that were not asked for

Reply ONLY: CORRECT or WRONG
If WRONG → add brief reason after colon.
"""

    try:
        resp = groq_client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=30,
        )

        verdict = resp.choices[0].message.content.strip().upper()
        print(f"   🤖 LLM verdict: {verdict}")

        if verdict.startswith("WRONG"):
            reason = verdict.split(":", 1)[1].strip() if ":" in verdict else "Data does not match question."
            state["is_valid"] = False
            state["error"]    = reason
            print(f"   ❌ VALIDATOR: data is WRONG — reason: {reason}")
        else:
            state["is_valid"] = True
            print("   ✅ VALIDATOR: data is CORRECT")

    except Exception as exc:
        print(f"   ⚠️  LLM validation failed: {exc} — assuming CORRECT")
        state["is_valid"] = True

    return state
# ═══════════════════════════════════════════════
# 6. ERROR FIX NODE
# ═══════════════════════════════════════════════
def error_fix_node(state: AgentState) -> AgentState:
    print("\n" + "█"*60)
    print("🔧 NODE: ERROR FIX (LLM fixes SQL)")
    print("█"*60)

    retry_count = state.get("retry_count", 0)
    print(f"   Retry attempt : {retry_count + 1} / 2")
    print(f"   Error         : {state.get('error', 'none')}")
    print(f"   Current SQL   : {state.get('sql', '')[:150]}")

    if retry_count >= 2:
        print("   ❌ Max retries (2) reached — giving up")
        state["result"] = {}
        return state

    state["retry_count"] = retry_count + 1
    error = state.get("error", "")

    # LLM fix attempt
    print("   🤖 Calling LLM to fix SQL...")
    fix_prompt = f"""
Fix this SQL query.

Question: {state['question']}
Current SQL: {state['sql']}
Error / reason: {error}

RULES:
- Use only valid columns (no guessing)
- Keep same tables if possible
- Fix JOIN conditions if needed
- If empty result → relax WHERE filters
- If MAX/MIN → use TOP 1 + ORDER BY
- Return ONLY the fixed SQL query
"""
    try:
        resp      = groq_client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": fix_prompt}],
            temperature=0,
            max_tokens=300,
        )
        fixed_sql = resp.choices[0].message.content.strip()
        print(f"   🤖 LLM fix response (first 200): {fixed_sql[:200]}")

        if "```" in fixed_sql:
            m = re.search(r"```(?:sql)?(.*?)```", fixed_sql, re.DOTALL)
            if m:
                fixed_sql = m.group(1).strip()

        if fixed_sql.lower().startswith("select"):
            state["sql"] = fixed_sql
            print(f"   ✅ SQL fixed successfully")
            state["messages"].append({"role": "user", "content": f"Fixed SQL: {fixed_sql}"})
            return state
        else:
            print("   ⚠️  LLM fix did not return a valid SELECT — trying per-table fallback")

    except Exception as exc:
        print(f"   ❌ LLM fix failed: {exc}")

    # Per-table fallback
    print("   🔄 Trying per-table fallback...")
    for table in state.get("tables", []):
        print(f"   🔄 Trying single table: {table}")
        try:
            fb_sql = generate_sql(state["question"], [table])
            if not fb_sql:
                print(f"   ⚠️  No SQL generated for '{table}'")
                continue

            fb_result = validate_and_execute(fb_sql)
            if fb_result["status"] == "success" and fb_result["row_count"] > 0:
                state["sql"]      = fb_sql
                state["result"]   = {
                    "columns": fb_result["columns"],
                    "rows"   : [list(r.values()) for r in fb_result["data"]],
                }
                state["error"]    = ""
                state["is_valid"] = True
                print(f"   ✅ Fallback succeeded with table: {table} ({fb_result['row_count']} rows)")
                return state
            else:
                print(f"   ⚠️  Table '{table}' returned no data or error")

        except Exception as e:
            print(f"   ❌ Fallback failed for '{table}': {e}")
            continue

    print("   ❌ All fix attempts exhausted")
    return state


# ═══════════════════════════════════════════════
# 7. RESPONDER NODE
# ═══════════════════════════════════════════════
def responder_node(state: AgentState) -> AgentState:
    print("\n" + "█"*60)
    print("💬 NODE: RESPONDER (LLM writes final answer)")
    print("█"*60)

    if not state.get("result", {}).get("rows"):
        print("   ⚠️  No result data — generating clean contextual answer")
        # ── Clean LLM answer — plug-in ────────────────────────
        try:
            resp = groq_client.chat.completions.create(
                model=LLM_MODEL,
                messages=[{"role": "user", "content": (
                    f"The user asked: '{state['question']}'\n"
                    f"We searched the database thoroughly but could not find relevant data.\n"
                    f"Error encountered: {state.get('error', 'No matching data found.')}\n\n"
                    f"RULES:\n"
                    f"1. Write exactly 1 polite sentence\n"
                    f"2. Tell user what was not found\n"
                    f"3. Suggest they rephrase or verify the data exists\n"
                    f"4. Do NOT mention SQL, tables, or technical terms\n"
                    f"5. Sound helpful, not apologetic\n"
                    f"Example: 'I couldn't find biometric data in the system "
                    f"— you may want to check if this information is available "
                    f"or try rephrasing your request.'"
                )}],
                temperature=0,
                max_tokens=80,
            )
            answer = resp.choices[0].message.content.strip()
        except Exception:
            answer = (
                f"I couldn't find relevant data for '{state['question']}'. "
                f"Please verify the information exists or try rephrasing your request."
            )
        print(f"   ✅ Clean answer: {answer}")
        state["messages"].append({"role": "assistant", "content": answer})
        return state

    rows     = state["result"]["rows"]
    columns  = state["result"]["columns"]
    question = state["question"]

    print(f"   Summarizing {len(rows)} rows across {len(columns)} columns...")
    print("   🤖 Calling LLM to write natural language answer...")

    prompt = f"""
You have executed a SQL query and got real data back.

Question asked: {question}
Total rows returned: {len(rows)}
Column names: {columns}
First 5 rows of actual data: {str(rows[:5])}    

RULES:
1. Use the actual data values shown above to answer
2. Write 1-2 clear sentences summarizing the key finding
3. Mention actual values if helpful
4. Do NOT say data is missing — it is right above
5. Do NOT hallucinate — use only what is shown
"""
    try:
        resp   = groq_client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=100,
        )
        answer = resp.choices[0].message.content.strip()
        print(f"   ✅ Final answer: {answer}")
        state["messages"].append({"role": "assistant", "content": answer})

    except Exception as exc:
        print(f"   ❌ Responder failed: {exc}")

    return state


# ═══════════════════════════════════════════════
# GENERAL AGENT NODE
# ═══════════════════════════════════════════════
def general_agent_node(state: AgentState) -> AgentState:
    print("\n" + "█"*60)
    print("💬 NODE: GENERAL AGENT")
    print("█"*60)
    answer = handle_general(state["question"])
    state["messages"].append({"role": "assistant", "content": answer})
    return state


# ═══════════════════════════════════════════════
# ROUTERS
# ═══════════════════════════════════════════════
def intent_router(state: AgentState) -> str:
    decision = "general" if state.get("intent") == "GENERAL" else "sql"
    print(f"\n   ↪️  intent_router → {decision}")
    return decision


def agent_router(state: AgentState) -> str:
    if len(state["messages"]) > 12:
        print("   ↪️  agent_router → end (message limit reached)")
        return "end"
    last = state["messages"][-1]["content"].strip().lower()
    decision = "get_schema" if "get_schema" in last else "end"
    print(f"   ↪️  agent_router → {decision}")
    return decision


# def executor_router(state: AgentState) -> str:
#     error = state.get("error")

#     # 🟢 EMPTY RESULT → NOT ERROR
#     if error == "empty_result":
#         print("   ↪️  executor_router → validate (empty result)")
#         return "validate"

#     # 🔴 REAL ERROR → FIX
#     if error:
#         print(f"   ↪️  executor_router → error_fix (error: {error[:60]})")
#         return "error_fix"

#     # 🟢 DATA FOUND → VALIDATE
#     if state.get("result", {}).get("rows"):
#         print("   ↪️  executor_router → validate")
#         return "validate"

#     # 🟢 SAFETY (no rows but no error set)
#     print("   ↪️  executor_router → validate (no rows)")
#     return "validate"

def executor_router(state: AgentState) -> str:
    error = state.get("error")

    # 🟢 EMPTY RESULT → VALIDATE (NOT end)
    if error == "empty_result":
        print("   ↪️  executor_router → validate (empty result)")
        return "validate"

    # 🔴 REAL ERROR → FIX
    if error:
        print(f"   ↪️  executor_router → error_fix (error: {error[:60]})")
        return "error_fix"

    # 🟢 DATA FOUND → VALIDATE
    if state.get("result", {}).get("rows"):
        print("   ↪️  executor_router → validate")
        return "validate"

    # 🟢 SAFETY
    print("   ↪️  executor_router → validate (no rows)")
    return "validate"


def executor_node(state: AgentState) -> AgentState:
    print("\n" + "█"*60)
    print("⚡ NODE: EXECUTOR")
    print("█"*60)

    if not state.get("sql"):
        print("   ❌ No SQL in state — cannot execute")
        state["error"] = state.get("error") or "No SQL to execute."
        return state

    print(f"   SQL: {state['sql'][:200]}")

    result = validate_and_execute(state["sql"])

    if result["status"] == "success" and result["row_count"] > 0:
        state["result"] = {
            "columns": result["columns"],
            "rows"   : [list(r.values()) for r in result["data"]],
        }
        state["error"] = ""
        print(f"\n   ✅ EXECUTOR SUCCESS: {result['row_count']} rows returned")
        print(f"   Columns: {result['columns']}")

    elif result["status"] == "success" and result["row_count"] == 0:
        state["error"]    = "empty_result"
        state["is_valid"] = False
        print("   ⚠️  SQL ran successfully but returned 0 rows")

    else:
        state["error"] = result.get("error", "Unknown SQL error.")
        print(f"   ❌ EXECUTOR FAILED: {state['error']}")

    return state



def validator_router(state: AgentState) -> str:
    decision = "respond" if state.get("is_valid") else "error_fix"
    print(f"   ↪️  validator_router → {decision}")
    return decision


def error_fix_router(state: AgentState) -> str:
    if state.get("result", {}).get("rows") and state.get("is_valid"):
        print("   ↪️  error_fix_router → respond (fallback succeeded)")
        return "respond"
    if state.get("retry_count", 0) >= 2:
        print("   ↪️  error_fix_router → respond (max retries — clean answer)")
        return "respond"    # ← was "end", now always goes to responder
    print("   ↪️  error_fix_router → executor (retry with fixed SQL)")
    return "executor"


# ═══════════════════════════════════════════════
# GRAPH ASSEMBLY
# ═══════════════════════════════════════════════
builder = StateGraph(AgentState)

builder.add_node("router"       , router_node)
builder.add_node("agent"        , agent_node)
builder.add_node("get_schema"   , schema_node)
builder.add_node("executor"     , executor_node)
builder.add_node("validator"    , validator_node)
builder.add_node("error_fix"    , error_fix_node)
builder.add_node("responder"    , responder_node)
builder.add_node("general_agent", general_agent_node)

builder.set_entry_point("router")

builder.add_conditional_edges(
    "router", intent_router,
    {"sql": "agent", "general": "general_agent"}
)
builder.add_conditional_edges(
    "agent", agent_router,
    {"get_schema": "get_schema", "end": END}
)
builder.add_edge("get_schema", "executor")
builder.add_conditional_edges(
    "executor", executor_router,
    {"validate": "validator", "error_fix": "error_fix"}
)
builder.add_conditional_edges(
    "validator", validator_router,
    {"respond": "responder", "error_fix": "error_fix"}
)
builder.add_conditional_edges(
    "error_fix", error_fix_router,
    {"executor": "executor", "respond": "responder", "end": END}
)
builder.add_edge("responder"    , END)
builder.add_edge("general_agent", END)

graph = builder.compile()


# ═══════════════════════════════════════════════
# PUBLIC ENTRY POINT
# ═══════════════════════════════════════════════
def run_agent(question: str, domain: str = None, context: dict = None) -> dict:
    print("\n" + "█"*60)
    print("🚀 AGENT PIPELINE START")
    print("█"*60)
    print(f"   Question: {question}")

    # ── Log fallback context if received ─────────────────────
    if context:
        print(f"\n   📦 FALLBACK received context:")
        print(f"      fail_reason  : {context.get('fail_reason', '')}")
        print(f"      failed_sql   : {context.get('failed_sql', '')[:80]}")
        print(f"      domain       : {context.get('domain', '')}")

    result = graph.invoke({
        "question"   : question,
        "intent"     : "",
        "domain"     : domain or (context.get("domain", "") if context else ""),
        "schema"     : "",
        "sql"        : "",
        "tables"     : [],
        "result"     : {},
        "is_valid"   : False,
        "error"      : "",
        "retry_count": 0,
        "messages"   : [
            {
                "role"   : "system",
                "content": (
                    "You are a SQL agent for Air India Express crew management system.\n"
                    "STRICT RULES:\n"
                    "- First output ONLY: get_schema\n"
                    "- Do NOT explain anything\n"
                    "- Do NOT write SQL here\n"
                    + (
                        f"\nPREVIOUS AGENT CONTEXT:\n"
                        f"- Fail reason  : {context.get('fail_reason', '')}\n"
                        f"- Failed SQL   : {context.get('failed_sql', '')}\n"
                        f"- Avoid repeating the same SQL or same tables that already failed.\n"
                        if context else ""
                    )
                )
            },
            {
                "role"   : "user",
                "content": question
            }
        ],
    })

    answer = ""
    for msg in reversed(result.get("messages", [])):
        if msg["role"] == "assistant" and msg["content"]:
            answer = msg["content"]
            break

    print("\n" + "█"*60)
    print("🏁 AGENT PIPELINE COMPLETE")
    print("█"*60)
    print(f"   Intent  : {result.get('intent', '')}")
    print(f"   Domain  : {result.get('domain', '')}")
    print(f"   Tables  : {result.get('tables', [])}")
    print(f"   SQL     : {result.get('sql', '')[:150]}")
    print(f"   Rows    : {len(result.get('result', {}).get('rows', []))}")
    print(f"   Answer  : {answer}")
    print("█"*60 + "\n")

    return {
        "answer" : answer,
        "sql"    : result.get("sql", ""),
        "columns": result.get("result", {}).get("columns", []),
        "rows"   : result.get("result", {}).get("rows", []),
        "intent" : result.get("intent", ""),
        "domain" : result.get("domain", ""),
    }