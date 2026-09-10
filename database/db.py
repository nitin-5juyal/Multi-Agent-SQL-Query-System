import pyodbc
import os


# ================= CONNECTION STRING =================
CONNECTION_STRING = (
    f"DRIVER={{ODBC Driver 17 for SQL Server}};"
    f"SERVER={os.getenv('DB_SERVER')};"
    f"DATABASE={os.getenv('DB_NAME')};"
    f"UID={os.getenv('DB_USER')};"
    f"PWD={os.getenv('DB_PASSWORD')};"
    "TrustServerCertificate=yes;"
)


# ================= GET CONNECTION =================
def get_connection():
    try:
        return pyodbc.connect(CONNECTION_STRING, timeout=10)
    except Exception as e:
        raise Exception(f"Database connection failed: {str(e)}")


# ================= LOAD CONTEXT =================
def get_context():
    try:
        with open("database/context.txt", "r") as f:
            return f.read()
    except:
        return "" 


# ================= GET ALL TABLES =================
def get_all_tables():
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT TABLE_NAME 
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_TYPE = 'BASE TABLE'
        """)

        tables = [row[0] for row in cursor.fetchall()]

        conn.close()
        return tables

    except Exception as e:
        print(f"Error fetching tables: {e}")
        return []


# ================= GET TABLE INFO =================
def get_table_info(allowed_tables):

    if not allowed_tables:
        return ""

    conn = get_connection()
    cursor = conn.cursor()

    schema_text = ""

    try:
        for table in allowed_tables:
            try:
                cursor.execute("""
                    SELECT COLUMN_NAME, DATA_TYPE
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_NAME = ?
                    ORDER BY ORDINAL_POSITION
                """, (table,))

                rows = cursor.fetchall()

                if not rows:
                    continue

                columns = [f"{row[0]} ({row[1]})" for row in rows]

                schema_text += f"""
Table: {table}
Columns:
{chr(10).join(["- " + col for col in columns])}

"""

            except Exception as inner_e:
                print(f"Error reading table {table}: {inner_e}")
                continue

    finally:
        conn.close()

    # 🔹 Add context (optional)
    context = get_context()
    if context:
        schema_text += f"\nContext:\n{context[:500]}"

    return schema_text.strip()