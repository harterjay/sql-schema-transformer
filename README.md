# SQL Schema Transformer

This app generates SQL SELECT statements to transform data from a source schema to a target schema using Claude's LLM.

## Features
- Upload two Excel files (source and target schemas)
- Each file must have columns: `table`, `column`, `type`, `description`
- Returns SQL to transform source into target

## Setup
1. Clone/download this project.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Create a `.env` file in the project root with your Claude API key:
   ```env
   CLAUDE_API_KEY=your-claude-api-key-here
   ```
4. Run the app:
   ```bash
   uvicorn main:app --reload
   ```
5. Open your browser to [http://localhost:8000/docs](http://localhost:8000/docs) to use the API UI.

## Usage
- Use the `/generate-sql/` endpoint to upload your source and target Excel files.
- The response will contain the generated SQL statement.

## Notes
- Both Excel files must have the columns: `table`, `column`, `type`, `description` (case-insensitive).
- The app uses Claude 3 Opus by default. You can change the model in `main.py` if needed. 