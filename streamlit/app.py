# import streamlit as st
# import requests
# import pandas as pd
# import sqlparse
# import time

# st.set_page_config(page_title="SQL AI Agent", layout="wide")

# st.title("SQL AI Agent")

# # ================= INPUT =================
# with st.form(key="query_form"):
#     question = st.text_input("Ask your question")
#     submit = st.form_submit_button("Submit")

# if submit and question:

#     start_time = time.time()  # ⏱️ start timer

#     # 🔄 LOADING SPINNER
#     with st.spinner("Processing your query..."):

#         try:
#             response = requests.post(
#                 "http://127.0.0.1:8000/ask",
#                 json={
#                     "question": question,
#                     "session_id": "user_001"   # 🔥 SAME ID
#                 },
#                 timeout=60
#             )

#             if response.status_code != 200:
#                 st.error(f"API Error: {response.text}")
#                 st.stop()

#             data = response.json()

#         except Exception as e:
#             st.error(f"Connection Error: {e}")
#             st.stop()

#     end_time = time.time()  # ⏱️ end timer
#     execution_time = round(end_time - start_time, 2)

#     # ================= OUTPUT CONTROL =================
#     rows = data.get("rows", [])
#     columns = data.get("columns", [])
#     answer = data.get("answer", "")

#     # 🔴 1. ERROR MESSAGE
#     if not rows:
#         if answer:
#             st.error(answer)
#         else:
#             st.error("No data found")

#         st.caption(f"⏱️ Query time: {execution_time} sec")
#         st.stop()

#     # ================= SQL QUERY (OPTIONAL) =================
#     if data.get("sql"):
#         formatted_sql = sqlparse.format(
#             data["sql"],
#             reindent=True,
#             keyword_case='upper'
#         )
#         st.subheader("SQL Query")
#         st.code(formatted_sql, language="sql")

#     # 🟢 2. TABLE
#     st.subheader("Result")
#     df = pd.DataFrame(rows, columns=columns)
#     st.dataframe(df, use_container_width="stretch")

#     # ⏱️ TIME DISPLAY
#     st.caption(f"⏱️ Query time: {execution_time} sec")

import streamlit as st
import requests
import pandas as pd
import sqlparse
import time

st.set_page_config(page_title="SQL AI Agent", layout="wide")
st.title("SQL AI Agent")

# ══════════════════════════════════════════════════════════════
# INITIALIZE SESSION STATE
# ══════════════════════════════════════════════════════════════
if "result"        not in st.session_state: st.session_state.result        = None
if "question"      not in st.session_state: st.session_state.question      = ""
if "feedback_mode" not in st.session_state: st.session_state.feedback_mode = None
if "feedback_done" not in st.session_state: st.session_state.feedback_done = False


# ══════════════════════════════════════════════════════════════
# INPUT FORM
# ══════════════════════════════════════════════════════════════
with st.form(key="query_form"):
    question_input = st.text_input("Ask your question")
    submit         = st.form_submit_button("Submit")

if submit and question_input:
    # Reset state on new question
    st.session_state.feedback_mode = None
    st.session_state.feedback_done = False
    st.session_state.result        = None
    st.session_state.question      = question_input

    start_time = time.time()

    with st.spinner("Processing your query..."):
        try:
            response = requests.post(
                "http://127.0.0.1:8000/ask",
                json={
                    "question"  : question_input,
                    "session_id": "user_001"
                },
                timeout=60
            )

            if response.status_code != 200:
                st.error(f"API Error: {response.text}")
                st.stop()

            data                   = response.json()
            data["execution_time"] = round(time.time() - start_time, 2)

            # Save to session state
            st.session_state.result = data

        except Exception as e:
            st.error(f"Connection Error: {e}")
            st.stop()


# ══════════════════════════════════════════════════════════════
# DISPLAY RESULT
# Always renders from session_state — survives rerenders
# ══════════════════════════════════════════════════════════════
if st.session_state.result:

    data     = st.session_state.result
    question = st.session_state.question
    rows     = data.get("rows", [])
    columns  = data.get("columns", [])
    answer   = data.get("answer", "")
    exec_time = data.get("execution_time", 0)

    # ── No Data ───────────────────────────────────────────────
    if not rows:
        st.warning(answer if answer else "No data found.")
        st.caption(f"⏱️ Query time: {exec_time} sec")

    else:
        # ── SQL ───────────────────────────────────────────────
        if data.get("sql"):
            formatted_sql = sqlparse.format(
                data["sql"],
                reindent=True,
                keyword_case="upper"
            )
            st.subheader("SQL Query")
            st.code(formatted_sql, language="sql")

        # ── Result Table ──────────────────────────────────────
        st.subheader("Result")
        df = pd.DataFrame(rows, columns=columns)
        st.dataframe(df, use_container_width="stretch")
        st.caption(f"⏱️ Query time: {exec_time} sec")

    # ══════════════════════════════════════════════════════════
    # FEEDBACK SECTION
    # Fully outside submit block — always visible after result
    # ══════════════════════════════════════════════════════════
    st.markdown("---")
    st.markdown("### Was this answer helpful?")

    # ── Feedback already submitted ────────────────────────────
    if st.session_state.feedback_done:
        st.success("✅ Thank you for your feedback!")

    else:
        col1, col2 = st.columns(2)

        # ── Thumbs Up ─────────────────────────────────────────
        with col1:
            if st.button("👍 Correct Answer"):
                try:
                    requests.post(
                        "http://127.0.0.1:8000/feedback",
                        json={
                            "question"  : question,
                            "answer"    : answer,
                            "sql"       : data.get("sql", ""),
                            "domain"    : data.get("domain", ""),
                            "rating"    : 1,
                            "comment"   : "Correct",
                            "session_id": "user_001",
                        }
                    )
                    st.session_state.feedback_done = True
                    st.session_state.feedback_mode = None
                    st.rerun()
                except Exception as e:
                    st.error(f"Feedback error: {e}")

        # ── Thumbs Down ───────────────────────────────────────
        with col2:
            if st.button("👎 Wrong Answer"):
                st.session_state.feedback_mode = "wrong"
                st.rerun()

        # ── Correction Form ───────────────────────────────────
        # Only shown after clicking 👎
        if st.session_state.feedback_mode == "wrong":
            st.markdown("#### What was wrong? Tell us how to fix it:")

            with st.form("correction_form"):
                user_fix    = st.text_area(
                    "Describe what the correct answer should be",
                    placeholder="e.g. Should only show active crew with employmentEnd = 2099-12-31",
                    height=120,
                )
                col_submit, col_cancel = st.columns(2)

                with col_submit:
                    submit_fix = st.form_submit_button("✅ Submit Correction")
                with col_cancel:
                    cancel = st.form_submit_button("❌ Cancel")

                if submit_fix:
                    if not user_fix.strip():
                        st.warning("Please describe what was wrong before submitting.")
                    else:
                        try:
                            requests.post(
                                "http://127.0.0.1:8000/feedback",
                                json={
                                    "question"  : question,
                                    "answer"    : answer,
                                    "sql"       : data.get("sql", ""),
                                    "domain"    : data.get("domain", ""),
                                    "rating"    : 0,
                                    "comment"   : user_fix.strip(),
                                    "session_id": "user_001",
                                }
                            )
                            st.session_state.feedback_done = True
                            st.session_state.feedback_mode = None
                            st.rerun()
                        except Exception as e:
                            st.error(f"Feedback error: {e}")

                if cancel:
                    st.session_state.feedback_mode = None
                    st.rerun()