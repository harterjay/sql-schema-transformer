# SQL Schema Transformer

This app generates SQL SELECT statements to transform and join data from multiple source schemas to a target schema using Claude's LLM. The app provides both a FastAPI backend and a user-friendly Streamlit frontend.

## Features

### Core Functionality
- **Multiple Source Support**: Upload multiple source Excel files (e.g., transactional data, master data)
- **Target Schema**: Upload one target Excel file defining the desired output schema
- **Join Key Mapping**: Optionally upload a join key table to specify table relationships
- **SQL Generation**: Automatically generates Microsoft SQL Server (T-SQL) SELECT statements with proper JOINs
- **LLM Integration**: Uses Claude's AI to intelligently map fields and generate SQL

### File Formats
- **Source/Target Schemas**: Excel files with columns: `table`, `column`, `type`, `description`
- **Join Key Table** (optional): Excel file with columns: `left_table`, `left_field`, `right_table`, `right_field`

### User Interface Options
- **Streamlit App** (`app.py`): User-friendly web interface for file uploads and SQL generation
- **FastAPI Backend** (`main.py`): REST API for programmatic access

## Setup

### Prerequisites
- Python 3.8+
- Claude API key from [Anthropic](https://console.anthropic.com/)

### Installation
1. Clone/download this project:
   ```bash
   git clone https://github.com/harterjay/sql-schema-transformer.git
   cd sql-schema-transformer
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Create a `.env` file in the project root with your Claude API key:
   ```env
   CLAUDE_API_KEY=your-claude-api-key-here
   ```

## Usage

### Option 1: Streamlit Web App (Recommended)
1. Run the Streamlit app:
   ```bash
   streamlit run app.py
   ```
2. Open your browser to [http://localhost:8501](http://localhost:8501)
3. Upload your source schema files (multiple files supported)
4. Upload your target schema file
5. Optionally upload a join key table
6. Click "Generate SQL" to get your T-SQL statement

### Option 2: FastAPI Backend
1. Run the FastAPI server:
   ```bash
   uvicorn main:app --reload
   ```
2. Open your browser to [http://localhost:8000/docs](http://localhost:8000/docs)
3. Use the `/generate-sql/` endpoint to upload files and generate SQL

## Example Workflow

1. **Prepare Your Files**:
   - Source files: `transactional_data.xlsx`, `master_data.xlsx`
   - Target file: `target_schema.xlsx`
   - Join keys (optional): `join_keys.xlsx`

2. **Upload and Generate**:
   - Upload all source files
   - Upload target file
   - Upload join keys (if available)
   - Generate SQL

3. **Result**: A T-SQL SELECT statement that joins the appropriate source tables to produce your target schema

## File Format Examples

### Source/Target Schema Format
| table | column | type | description |
|-------|--------|------|-------------|
| users | id | int | user identifier |
| users | name | varchar | user's full name |

### Join Key Table Format
| left_table | left_field | right_table | right_field |
|------------|------------|-------------|-------------|
| roll | base_grade | product | productid |
| order | customer_id | customer | id |

## Notes
- All Excel files must have the required columns (case-insensitive)
- The app uses Claude 3 Opus by default for SQL generation
- Generated SQL is formatted for Microsoft SQL Server (T-SQL)
- Join relationships are automatically determined based on field names and descriptions, or explicitly specified via the join key table

## Troubleshooting
- Ensure your Claude API key is valid and has sufficient credits
- Check that all Excel files have the correct column headers
- For large schemas, the API call may take up to 60 seconds 