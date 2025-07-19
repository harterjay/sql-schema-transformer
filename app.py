import streamlit as st
import pandas as pd
import os
import httpx
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- Helper functions (copied from main.py) ---
def parse_schema(file) -> pd.DataFrame:
    df = pd.read_excel(file)
    df.columns = [c.lower() for c in df.columns]
    required_cols = {"table", "column", "type", "description"}
    if not required_cols.issubset(df.columns):
        raise ValueError("Missing required columns in schema file.")
    return df

def schema_to_text(df: pd.DataFrame, source_name: str = None) -> str:
    prefix = f"[{source_name}]\n" if source_name else ""
    return prefix + "\n".join(
        f"{row['table']}.{row['column']} {row['type']} -- {row['description']}"
        for _, row in df.iterrows()
    )

def join_keys_to_text(df: pd.DataFrame) -> str:
    # Assume columns: left_table, left_field, right_table, right_field
    return "\n".join(
        f"{row['left_table']}.{row['left_field']} = {row['right_table']}.{row['right_field']}" for _, row in df.iterrows()
    )

def call_claude(prompt: str) -> str:
    CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")
    CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": CLAUDE_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    data = {
        "model": "claude-opus-4-20250514",
        "max_tokens": 1024,
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }
    response = httpx.post(CLAUDE_API_URL, headers=headers, json=data, timeout=60)
    response.raise_for_status()
    return response.json()["content"][0]["text"]

# --- Streamlit UI ---
st.set_page_config(page_title="SQL Schema Transformer", layout="centered")
st.title("SQL Schema Transformer")
st.write("Upload your source and target schema Excel files. The app will generate a SQL SELECT statement to transform and join the source schemas to produce the target schema (formatted for Microsoft SQL Server).\n\n**Excel files must have columns:** `table`, `column`, `type`, `description`. You may upload multiple source files (e.g., transactional, master data, etc.). Optionally, you can upload a Join Key table (Excel) with columns: `left_table`, `left_field`, `right_table`, `right_field` to specify join relationships.")

with st.form("schema_form"):
    source_files = st.file_uploader("Source schema Excel files (you can select multiple)", type=["xlsx"], accept_multiple_files=True)
    target_file = st.file_uploader("Target schema Excel file", type=["xlsx"])
    join_key_file = st.file_uploader("(Optional) Join Key table (Excel, columns: left_table, left_field, right_table, right_field)", type=["xlsx"])
    submitted = st.form_submit_button("Generate SQL")

if submitted:
    if not source_files or not target_file:
        st.error("Please upload at least one source schema file and one target schema file.")
    else:
        try:
            # Parse all source files and keep their names
            source_schemas = []
            for file in source_files:
                df = parse_schema(file)
                source_schemas.append((file.name, df))
            target_df = parse_schema(target_file)
            # Build source schemas text
            sources_text = "\n\n".join(
                schema_to_text(df, source_name=name) for name, df in source_schemas
            )
            target_text = schema_to_text(target_df)
            join_keys_text = ""
            if join_key_file:
                join_keys_df = pd.read_excel(join_key_file)
                # Validate columns
                required_join_cols = {"left_table", "left_field", "right_table", "right_field"}
                join_keys_df.columns = [c.lower() for c in join_keys_df.columns]
                if not required_join_cols.issubset(join_keys_df.columns):
                    raise ValueError("Join Key table must have columns: left_table, left_field, right_table, right_field")
                join_keys_text = join_keys_to_text(join_keys_df)
            # Build prompt
            prompt = f"""Given the following source schemas (from different systems):
{sources_text}

And the following target schema:
<target>
{target_text}
</target>
"""
            if join_keys_text:
                prompt += f"\nUse the following join keys when joining tables (these are the correct join relationships):\n{join_keys_text}\n"
            prompt += """
Write ONLY the SQL SELECT statement (no explanation, no comments, no description) that transforms and joins the appropriate source tables to produce the target schema. Use field names and descriptions to determine which source table/column to use for each target field. Format the SQL as a valid Microsoft SQL Server (T-SQL) script, using proper indentation, line breaks, and JOINs as needed. Do not include any explanation or commentary—output only the SQL code."""
            with st.spinner("Generating SQL with Claude..."):
                sql = call_claude(prompt)
            st.success("SQL generated!")
            st.code(sql, language="sql")
        except Exception as e:
            st.error(f"Error: {e}") 