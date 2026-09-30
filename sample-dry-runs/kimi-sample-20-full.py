import json
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("OPENROUTER_API_KEY")
if not api_key:
    raise SystemExit("OPENROUTER_API_KEY is missing. Put it in .env.")


def json_schema_type(field_type):
    if field_type == "string[]":
        return {"type": "array", "items": {"type": "string"}}
    if field_type == "object[]":
        return {"type": "array", "items": {"type": "object"}}
    if field_type == "string | null":
        return {"type": "string"}
    if field_type in {"string", "number", "integer", "boolean", "object"}:
        return {"type": field_type}
    return {"type": "string"}


def to_openai_tool(tool):
    properties = {}
    required = []
    for field in tool["inputs"]:
        schema = json_schema_type(field["type"])
        schema["description"] = field["description"]
        properties[field["name"]] = schema
        if field["required"]:
            required.append(field["name"])

    parameters = {"type": "object", "properties": properties}
    if required:
        parameters["required"] = required

    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": parameters,
        },
    }


catalog_path = Path(__file__).resolve().parent / "catalog" / "catalog_20_full.json"
catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
tools = [to_openai_tool(tool) for tool in catalog]

body = {
    "model": "moonshotai/kimi-k3",
    "messages": [
        {
            "role": "user",
            "content": "Show me the open issues in the payments repo",
        }
    ],
    "tools": tools,
    "tool_choice": "required",
    "max_tokens": 400,
    "reasoning": {"effort": "low"},
}

response = requests.post(
    url="https://openrouter.ai/api/v1/chat/completions",
    headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    },
    data=json.dumps(body),
)

payload = response.json()
print(response.status_code)
print(json.dumps(payload, indent=2))

message = payload.get("choices", [{}])[0].get("message", {})
tool_calls = message.get("tool_calls") or []
if tool_calls:
    picked = tool_calls[0]["function"]["name"]
    print(f"picked: {picked}")
