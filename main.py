from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
import pandas as pd
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# Parse the uploaded Excel schema file
def parse_schema(file) -> pd.DataFrame:
    df = pd.read_excel(file)
    df.columns = [c.lower() for c in df.columns]
    required_cols = {"table", "column", "type", "description"}
    if not required_cols.issubset(df.columns):
        raise ValueError("Missing required columns in schema file.")
    return df

# Convert schema DataFrame to readable text for prompt
def schema_to_text(df: pd.DataFrame) -> str:
    return "\n".join(
        f"{row['table']}.{row['column']} {row['type']} -- {row['description']}"
        for _, row in df.iterrows()
    )

# Call Claude API with the prompt
def call_claude(prompt: str) -> str:
    CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")
    CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
    print("Claude API Key:", CLAUDE_API_KEY)
    print("Claude API URL:", CLAUDE_API_URL)
    print("Prompt length:", len(prompt))
    print("Calling Claude API...")
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
    print("Claude API call complete.")
    response.raise_for_status()
    return response.json()["content"][0]["text"]


@app.post("/generate-sql/")
async def generate_sql(
    source: UploadFile = File(...),
    target: UploadFile = File(...)
):
    print("generate_sql endpoint called")
    try:
        source_df = parse_schema(source.file)
        target_df = parse_schema(target.file)
        source_text = schema_to_text(source_df)
        target_text = schema_to_text(target_df)
        prompt = f"""Given the following source schema:
<source>
{source_text}
</source>

And the following target schema:
<target>
{target_text}
</target>

Write ONLY the SQL SELECT statement (no explanation, no comments, no description) that transforms data from the source schema to match the target schema.
Format the SQL as a valid Microsoft SQL Server (T-SQL) script, using proper indentation and line breaks. Do not include any explanation or commentary—output only the SQL code."""
        sql = call_claude(prompt)
        return JSONResponse({"sql": sql})
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}") 