# Multi-Agent-SQL-Query-System
AI-powered multi-agent system for natural language to SQL query generation and execution.
# 🤖 Multi-Agent SQL Query System

An AI-powered multi-agent system that converts natural language questions into SQL queries and retrieves information from a relational database through an intelligent, state-driven workflow.

The system uses **LangGraph and LangChain** to coordinate specialized agents for intent classification, domain routing, schema selection, SQL generation, execution, validation, and error correction.

## 🚀 Key Features

* **Natural Language to SQL** — Ask database questions using plain English.
* **Multi-Agent Architecture** — Specialized agents handle different stages of the query workflow.
* **Intelligent Routing** — Routes user requests to the appropriate domain or agent.
* **Schema-Aware SQL Generation** — Selects relevant tables and database objects before generating SQL.
* **SQL Execution** — Executes generated queries against Microsoft SQL Server.
* **SQL Validation & Error Handling** — Validates generated SQL and supports automatic correction/retry workflows.
* **Guardrails** — Applies input checks before processing requests.
* **Memory & Feedback** — Supports feedback-driven improvements and session-based application memory.
* **Streamlit Interface** — Provides an interactive UI for submitting natural-language queries and viewing results.

## 🏗️ Architecture

```text
                    ┌─────────────────────┐
                    │     User Query      │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │   Input Guardrails  │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │      Router         │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │   Orchestrator      │
                    │     (LangGraph)     │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
       Schema Selection   SQL Generation   Domain Agent
              │                │                │
              └────────────────┼────────────────┘
                               ▼
                    ┌─────────────────────┐
                    │    SQL Validator    │
                    └──────────┬──────────┘
                               │
                         Error / Retry
                               │
                               ▼
                    ┌─────────────────────┐
                    │   SQL Execution     │
                    │   (MS SQL Server)   │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │   Final Response    │
                    └─────────────────────┘
```

## 🧠 Multi-Agent Workflow

The system is organized around specialized components:

### Router

Determines which part of the system should handle the user's request.

### Orchestrator

Coordinates the overall workflow using a state-driven architecture implemented with **LangGraph**.

### SQL / Fallback Agents

Handle SQL planning, table selection, query generation, validation, and fallback processing.

### Crew Agent

Handles crew-related database requests using specialized tools and prompts.

### Guardrails

Checks incoming user requests and helps prevent inappropriate or unsupported inputs from entering the workflow.

### Memory & Feedback

Stores application-level feedback and session information to support feedback-driven improvements.

## 🛠️ Tech Stack

| Category              | Technologies                        |
| --------------------- | ----------------------------------- |
| Language              | Python                              |
| AI / LLM              | Groq API                            |
| Agent Framework       | LangChain, LangGraph                |
| Database              | Microsoft SQL Server                |
| Database Connectivity | pyodbc                              |
| Backend API           | FastAPI                             |
| Frontend              | Streamlit                           |
| Query Processing      | SQL                                 |
| Architecture          | Multi-Agent / State-Driven Workflow |

## 📁 Project Structure

```text
Lan_sub_agent/
│
├── agents/
│   ├── fallback_agent/
│   │   ├── agent.py
│   │   └── tools/
│   │       ├── query_generator.py
│   │       ├── table_registry.py
│   │       ├── table_selector.py
│   │       └── validator.py
│   │
│   ├── general_agent.py
│   ├── router.py
│   │
│   ├── guardrails/
│   │   └── input_guard.py
│   │
│   ├── memory/
│   │   ├── feedback_manager.py
│   │   └── memory_manager.py
│   │
│   ├── orchestrator/
│   │   └── orchestrator.py
│   │
│   └── sub_agents/
│       ├── crew_agent/
│       └── generic_tools/
│
├── api/
│   └── main.py
│
├── context/
│   ├── crew.txt
│   └── sql_context.txt
│
├── database/
│   └── db.py
│
├── streamlit/
│   └── app.py
│
├── .gitignore
└── requirement.txt
```

## ⚙️ Setup

### 1. Clone the repository

```bash
git clone https://github.com/nitin-5juyal/Multi-Agent-SQL-Query-System.git
cd Multi-Agent-SQL-Query-System
```

### 2. Create a virtual environment

```bash
python -m venv venv
```

Activate it on Windows:

```powershell
venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirement.txt
```

### 4. Configure environment variables

Create a `.env` file locally.

Example:

```env
GROQ_API_KEY=your_groq_api_key

DB_SERVER=your_sql_server
DB_DATABASE=your_database
DB_USER=your_database_user
DB_PASSWORD=your_database_password
```

> **Never commit `.env` or real credentials to GitHub.**

The project reads credentials from environment variables rather than storing them directly in the source code.

## ▶️ Running the Application

### Start the API

From the project root:

```bash
uvicorn api.main:app --reload
```

### Start the Streamlit interface

In another terminal:

```bash
streamlit run streamlit/app.py
```

The exact runtime configuration may depend on your local SQL Server and environment-variable setup.

## 💬 Example Queries

The system is designed to accept natural-language database questions such as:

```text
Show me the top 10 crew by total pay.
```

```text
Who has the highest salary?
```

```text
Show me the top 3 crew members.
```

The system processes the request, determines the relevant database context, generates SQL, validates it, executes it, and returns the result.

## 🔐 Security

Sensitive configuration is intentionally kept outside the source code.

The repository excludes:

* `.env`
* Database files
* Runtime session data
* Application-generated memory data
* Python virtual environments
* IDE-specific files

API keys and database credentials should always be supplied through environment variables.

## 🎯 Project Highlights

* Designed a **multi-agent architecture** for natural-language database interaction.
* Implemented **state-driven workflow orchestration using LangGraph**.
* Built specialized components for **routing, schema selection, SQL generation, execution, and validation**.
* Integrated **Microsoft SQL Server through pyodbc**.
* Added **feedback and memory mechanisms** for improving query handling.
* Provided both **FastAPI and Streamlit interfaces**.

## 👨‍💻 Author

**Nitin Juyal**

GitHub: https://github.com/nitin-5juyal

---

⭐ If you find this project useful, consider giving the repository a star.
