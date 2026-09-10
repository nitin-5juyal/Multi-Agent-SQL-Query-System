"""
router.py
---------
Intent and Domain classifier.
"""

import os
import logging
from groq import Groq

logger = logging.getLogger("router")

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
LLM_MODEL   = "llama-3.3-70b-versatile"

VALID_DOMAINS = {
    "crew",
    "general"
}


def classify_intent(question: str) -> str:
    print("\n" + "═"*60)
    print("🔍 STEP 1 — INTENT CLASSIFICATION")
    print("═"*60)
    print(f"   Question : {question}")
    print("   Calling LLM → is this SQL or GENERAL?")

    prompt = f"""
You are an intent classifier.

Classify the user question into ONLY ONE:
- SQL
- GENERAL

IMPORTANT RULES:

1. If the user is asking about INTERNAL DATA related to the airline or company (crew, flights, roster, base, ranks, list, count, etc.)
→ ALWAYS return SQL

2. If the question can be answered using database tables about crew/flights
→ return SQL

3. Even if the question is in natural language:
   - "who are the crew in delhi"
   - "how many crew in BOM"
   - "give me crew list"
→ return SQL

4. GENERAL is ONLY for:
   - greetings (hello, hi)
   - general knowledge questions (who is the prime minister, what is the capital of india)
   - explanations (what is a database)
   - non-database / out-of-scope questions

Examples:

Q: show crew in DEL
A: SQL

Q: who are the crew members in delhi
A: SQL

Q: how many crew are in BOM
A: SQL

Q: who is the prime minister of india
A: GENERAL

Q: what is SQL
A: GENERAL

Q: hello
A: GENERAL

Now classify:

Question: {question}
Answer:
"""
    try:
        resp   = groq_client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=5,
        )
        intent = resp.choices[0].message.content.strip().upper()
        if intent not in ("SQL", "GENERAL"):
            print(f"   ⚠️  Unexpected response '{intent}' → defaulting to SQL")
            intent = "SQL"
    except Exception as exc:
        print(f"   ❌ LLM call failed: {exc}")
        print("   ⚠️  Defaulting to SQL")
        intent = "SQL"

    print(f"   ✅ Intent = {intent}")
    return intent


def classify_domain(question: str) -> str:
    print("\n" + "─"*60)
    print("🗂️  STEP 2 — DOMAIN CLASSIFICATION")
    print("─"*60)
    print(f"   Question : {question}")
    print("   Calling LLM → which domain does this belong to?")

    prompt = f"""You are a domain classifier for an airline crew management system (Air India Express).

Classify the question into ONE domain:

- crew    → crew details, rank, base, staff number, fleet, roster,
            block hours, statistics, payroll, personal profile,
            duty history, flying summary, functions, designations
- general → greetings, casual talk, help, unclear questions

RULES:
- Return ONLY one word: crew or general
- Since we only have crew domain right now → default to crew for any data question
- No explanation, no extra text

Question: {question}
"""
    try:
        resp   = groq_client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=10,
        )
        domain = resp.choices[0].message.content.strip().lower()
        if domain not in VALID_DOMAINS:
            print(f"   ⚠️  Unexpected response '{domain}' → defaulting to general")
            domain = "general"
    except Exception as exc:
        print(f"   ❌ LLM call failed: {exc}")
        print("   ⚠️  Defaulting to general")
        domain = "general"

    print(f"   ✅ Domain = {domain}")
    return domain