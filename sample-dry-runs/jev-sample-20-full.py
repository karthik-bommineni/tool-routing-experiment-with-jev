import json
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("OPENROUTER_API_KEY")
if not api_key:
    raise SystemExit("OPENROUTER_API_KEY is missing. Put it in .env.")


def tool_text(tool):
    lines = [tool["description"]]
    for field in tool["inputs"]:
        required = "required" if field["required"] else "optional"
        lines.append(
            f"{field['name']} ({field['type']}, {required}): {field['description']}"
        )
    return "\n".join(lines)


catalog_path = Path(__file__).resolve().parent / "catalog" / "catalog_20_full.json"
catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
criteria = {tool["name"]: tool_text(tool) for tool in catalog}

body = {
    "model": "typesafe/jev-1.13",
    "state": "Show me the open issues in the payments repo",
    "questions": {
        "tool": {
            "type": "choice",
            "instructions": "Which one tool should handle this request?",
            "criteria": criteria,
        }
    },
}

response = requests.post(
    url="https://openrouter.ai/api/alpha/decisions",
    headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    },
    data=json.dumps(body),
)

print(response.status_code)
print(json.dumps(response.json(), indent=2))
