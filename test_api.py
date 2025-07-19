import requests
import os
from dotenv import load_dotenv

load_dotenv()

CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")
print("Claude API Key:", CLAUDE_API_KEY)

headers = {
    "x-api-key": CLAUDE_API_KEY,
    "anthropic-version": "2023-06-01",
    "Content-Type": "application/json"
}
data = {
    "model": "claude-opus-4-20250514",
    "max_tokens": 1024,
    "messages": [
        {"role": "user", "content": "Hello"}
    ]
}
response = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=data)
print(response.status_code)
print(response.text)