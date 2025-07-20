import streamlit as st
import pandas as pd
import os
import httpx
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- Helper functions (copied from main.py) ---
def parse_schema(file) -> pd.DataFrame:
    """Parse an Excel schema file and return a DataFrame."""
    df = pd.read_excel(file)
    df.columns = [c.lower() for c in df.columns]
    required_cols = {"table", "column", "type", "description"}
    if not required_cols.issubset(df.columns):
        raise ValueError("Missing required columns in schema file.")
    return df

def schema_to_text(df: pd.DataFrame, source_name: str | None = None) -> str:
    """Convert schema DataFrame to text format."""
    prefix = f"[{source_name}]\n" if source_name else ""
    return prefix + "\n".join(
        f"{row['table']}.{row['column']} {row['type']} -- {row['description']}"
        for _, row in df.iterrows()
    )

def join_keys_to_text(df: pd.DataFrame) -> str:
    """Convert join keys DataFrame to text format."""
    # Assume columns: left_table, left_field, right_table, right_field
    return "\n".join(
        f"{row['left_table']}.{row['left_field']} = {row['right_table']}.{row['right_field']}" for _, row in df.iterrows()
    )

def call_claude(prompt: str) -> str:
    """Call Claude API to generate SQL based on the prompt."""
    # Environment variable loaded from .env file
    CLAUDE_API_KEY: str = os.getenv("CLAUDE_API_KEY") or ""
    if not CLAUDE_API_KEY:
        raise ValueError("CLAUDE_API_KEY environment variable not found. Please create a .env file with your Claude API key.")
    
    CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": CLAUDE_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    data = {
        "model": "claude-3-5-sonnet-20241022",
        "max_tokens": 4096,  # or higher, if supported
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }
    response = httpx.post(CLAUDE_API_URL, headers=headers, json=data, timeout=60)
    response.raise_for_status()
    response_data = response.json()
    return response_data["content"][0]["text"]

# --- Streamlit UI ---
# Configure page settings
st.set_page_config(page_title="SQL Schema Transformer", layout="centered")
st.title("SQL Schema Transformer")
st.write("Upload your source and target schema Excel files. The app will generate a SQL SELECT statement to transform and join the source schemas to produce the target schema (formatted for Microsoft SQL Server).\n\n**Excel files must have columns:** `table`, `column`, `type`, `description`. You may upload multiple source files (e.g., transactional, master data, etc.). Optionally, you can upload a Join Key table (Excel) with columns: `left_table`, `left_field`, `right_table`, `right_field` to specify join relationships.")

# Place these before the form
unmapped_option = st.radio(
    "What should the SQL output for unmapped fields?",
    ("Null", "NO_VALUE", "Custom value")
)
custom_value = ""
if unmapped_option == "Custom value":
    custom_value = st.text_input("Enter custom value (max 10 characters):", max_chars=10)

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
            if unmapped_option == "Null":
                unmapped_instruction = "If a target field cannot be mapped to any source field, output NULL for that field in the SELECT statement."
            elif unmapped_option == "NO_VALUE":
                unmapped_instruction = "If a target field cannot be mapped to any source field, output the string literal 'NO_VALUE' for that field in the SELECT statement."
            else:
                unmapped_instruction = f"If a target field cannot be mapped to any source field, output the string literal '{custom_value}' for that field in the SELECT statement."
            prompt = f"""Given the following source schemas (from different systems):\n{sources_text}\n\nAnd the following target schema:\n<target>\n{target_text}\n</target>\n"""
            if join_keys_text:
                prompt += f"\nUse the following join keys when joining tables (these are the correct join relationships):\n{join_keys_text}\n"
            prompt += f"\n{unmapped_instruction}\n"
            prompt += """
Write ONLY the SQL SELECT statement (no explanation, no comments, no description) that transforms and joins the appropriate source tables to produce the target schema. Use field names and descriptions to determine which source table/column to use for each target field. Format the SQL as a valid Microsoft SQL Server (T-SQL) script, using proper indentation, line breaks, and JOINs as needed. Do not include any explanation or commentary—output only the SQL code."""
            with st.spinner("Generating SQL with Claude..."):
                sql = call_claude(prompt)
            st.success("SQL generated!")
            st.code(sql, language="sql")
        except Exception as e:
            st.error(f"Error: {e}") 