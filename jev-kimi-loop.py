import importlib.util
import json
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("kimi_loop", ROOT / "kimi-loop-20-full.py")
kimi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kimi)

# One tool per lap, then one lap to write the note. 16 covers the 50-tool task
# (about eight tool calls) with room for a wrong pick.
MAX_HOPS = 50
# Switch these together. Paste only the Prompt line from testset/tasks.txt.
# 100: catalog_100_full.json
# 200: catalog_200_full.json
CATALOG_FILE = "catalog_200_full.json"
TASK = """
Close the acme/payments checkout investigation with the metrics. Query Prometheus for the checkout p95 latency over the last 15 minutes. Query Loki for deadline-exceeded errors from the checkout app. List the firing alert rule and the firing OnCall alert group. Decide whether the alert is a true positive and whether the timeout change should be rolled back. Do not create an incident, do not silence or delete an alert, and do not edit a dashboard. Finish with an incident note: the p95 value, how many matching logs you found, the alert state, and a yes or no on rolling back the timeout change, with the reason.
"""
JEV_MODEL = "typesafe/jev-1.13"
KIMI_MODEL = "moonshotai/kimi-k3"
FINISH = "finish"


def tool_text(tool):
    lines = [tool["description"]]
    for field in tool["inputs"]:
        required = "required" if field["required"] else "optional"
        lines.append(
            f"{field['name']} ({field['type']}, {required}): {field['description']}"
        )
    return "\n".join(lines)


def build_criteria(catalog, full, blocked=None):
    blocked = blocked or set()
    if full:
        criteria = {
            tool["name"]: tool_text(tool)
            for tool in catalog
            if tool["name"] not in blocked
        }
    else:
        criteria = {
            tool["name"]: tool["description"]
            for tool in catalog
            if tool["name"] not in blocked
        }
    criteria[FINISH] = (
        "Stop calling tools. The facts needed for the incident note are already gathered."
    )
    return criteria


def is_missing_fake(result):
    return (
        isinstance(result, dict)
        and result.get("ok") is False
        and str(result.get("note", "")).startswith("No fake result for ")
    )


def post_json(url, body):
    started = time.perf_counter()
    response = requests.post(
        url=url,
        headers={
            "Authorization": f"Bearer {kimi.api_key}",
            "Content-Type": "application/json",
        },
        data=json.dumps(body),
    )
    seconds = time.perf_counter() - started
    try:
        payload = response.json()
    except ValueError:
        payload = {"raw": response.text}
    return response.status_code, payload, seconds


def looks_like_context_limit(status, payload):
    text = json.dumps(payload).lower()
    mentions_size = any(
        word in text for word in ("context", "token", "length", "too large", "maximum")
    )
    return status in {400, 413, 422} and mentions_size


def read_jev_choice(payload):
    answer = (payload.get("answers") or {}).get("tool") or {}
    if isinstance(answer, str):
        return answer, None
    choice = answer.get("choice")
    confidence = answer.get("confidence")
    if confidence is None:
        confidence = payload.get("confidence")
    return choice, confidence


def ask_jev(state, criteria):
    status, payload, seconds = post_json(
        "https://openrouter.ai/api/alpha/decisions",
        {
            "model": JEV_MODEL,
            "state": state,
            "questions": {
                "tool": {
                    "type": "choice",
                    "instructions": (
                        "Pick exactly one next step. Choose a tool to gather one missing fact "
                        "or to take the one action the task allows. Choose finish when the "
                        "incident note can be written from the facts already gathered."
                    ),
                    "criteria": criteria,
                }
            },
        },
    )
    return status, payload, seconds


def ask_kimi(messages, tool):
    body = {
        "model": KIMI_MODEL,
        "messages": messages,
        "max_tokens": 1000,
        "reasoning": {"effort": "low"},
    }
    if tool is not None:
        body["tools"] = [tool]
        body["tool_choice"] = "required"
    status, payload, seconds = post_json(
        "https://openrouter.ai/api/v1/chat/completions",
        body,
    )
    return status, payload, seconds


def main():
    kimi.COMMENTS.clear()
    catalog_path = ROOT / "catalog" / CATALOG_FILE
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    by_name = {tool["name"]: tool for tool in catalog}
    blocked_tools = set()

    messages = [
        {"role": "system", "content": kimi.SYSTEM_PROMPT},
        {"role": "user", "content": TASK},
    ]
    facts = ""

    print(f"tools in menu: {len(catalog)}")
    print(f"task: {TASK}")
    print(f"max hops: {MAX_HOPS}")

    hop_log = []
    final_answer = ""
    stopped_early = False

    for hop in range(1, MAX_HOPS + 1):
        full_criteria = build_criteria(catalog, full=True, blocked=blocked_tools)
        short_criteria = build_criteria(catalog, full=False, blocked=blocked_tools)
        blocked_note = ""
        if blocked_tools:
            blocked_note = (
                "\n\nUnavailable tools (do not pick again): "
                + ", ".join(sorted(blocked_tools))
            )
        state = (
            f"{kimi.SYSTEM_PROMPT}\n\nTask:\n{TASK.strip()}\n\n"
            f"Facts gathered so far:\n{facts or 'None yet.'}{blocked_note}"
        )
        criteria_mode = "full"
        status, payload, jev_seconds = ask_jev(state, full_criteria)
        if status != 200 and looks_like_context_limit(status, payload):
            print(f"hop {hop}  jev full menu did not fit, retrying with short descriptions")
            criteria_mode = "short"
            status, payload, jev_seconds = ask_jev(state, short_criteria)
        if status != 200:
            print(f"hop {hop}  jev http {status}")
            print(json.dumps(payload, indent=2))
            raise SystemExit(1)

        choice, confidence = read_jev_choice(payload)
        usage = payload.get("usage") or {}
        jev_tokens = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
        jev_cost = usage.get("cost") or 0
        if choice not in by_name and choice != FINISH:
            print(f"hop {hop}  jev returned an unknown choice: {choice}")
            print(json.dumps(payload, indent=2))
            raise SystemExit(1)

        print(
            f"hop {hop}  jev={choice}  confidence={confidence}  "
            f"criteria={criteria_mode}  jev_input={jev_tokens}  jev_cost={jev_cost}"
        )

        if choice == FINISH:
            messages.append(
                {
                    "role": "user",
                    "content": "Write the incident note now from the facts above. Do not call any tools.",
                }
            )
            kimi_tool = None
        else:
            kimi_tool = kimi.to_openai_tool(by_name[choice])

        status, payload, kimi_seconds = ask_kimi(messages, kimi_tool)
        if status != 200:
            print(f"hop {hop}  kimi http {status}")
            print(json.dumps(payload, indent=2))
            raise SystemExit(1)

        usage = payload.get("usage") or {}
        kimi_cost = usage.get("cost") or 0
        prompt_tokens = usage.get("prompt_tokens") or 0
        completion_tokens = usage.get("completion_tokens") or 0
        message = payload["choices"][0]["message"]
        tool_calls = message.get("tool_calls") or []

        if choice == FINISH:
            final_answer = message.get("content") or ""
            hop_log.append(
                {
                    "hop": hop,
                    "jev_choice": choice,
                    "jev_confidence": confidence,
                    "criteria_mode": criteria_mode,
                    "jev_input_tokens": jev_tokens,
                    "jev_cost": jev_cost,
                    "jev_seconds": round(jev_seconds, 3),
                    "kimi_tools": ["(final answer)"],
                    "kimi_prompt_tokens": prompt_tokens,
                    "kimi_completion_tokens": completion_tokens,
                    "kimi_cost": kimi_cost,
                    "kimi_seconds": round(kimi_seconds, 3),
                }
            )
            print(
                f"hop {hop}  kimi=final  prompt={prompt_tokens}  "
                f"completion={completion_tokens}  cost={kimi_cost}"
            )
            print("final:")
            print(final_answer)
            break

        if not tool_calls:
            print(f"hop {hop}  kimi did not fill arguments for {choice}")
            print(json.dumps(payload, indent=2))
            stopped_early = True
            break

        messages.append(kimi.assistant_message(message))
        called_names = []
        newly_blocked = []
        for call in tool_calls:
            name = call["function"]["name"]
            args = kimi.parse_args(call["function"].get("arguments"))
            result = kimi.fake_result(name, args)
            called_names.append(name)
            print(f"  fake {name} -> {json.dumps(result)}")
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(result),
                }
            )
            facts += f"\n\nCalled {name} with {json.dumps(args)}\nResult: {json.dumps(result)}"
            if is_missing_fake(result) and name not in blocked_tools:
                blocked_tools.add(name)
                newly_blocked.append(name)
                facts += (
                    f"\n{name} is unavailable in this experiment. "
                    "Do not call it again. Pick a different tool or finish."
                )
                print(f"  blocked {name} from later Jev menus")

        hop_log.append(
            {
                "hop": hop,
                "jev_choice": choice,
                "jev_confidence": confidence,
                "criteria_mode": criteria_mode,
                "jev_input_tokens": jev_tokens,
                "jev_cost": jev_cost,
                "jev_seconds": round(jev_seconds, 3),
                "kimi_tools": called_names,
                "blocked_tools": newly_blocked,
                "kimi_prompt_tokens": prompt_tokens,
                "kimi_completion_tokens": completion_tokens,
                "kimi_cost": kimi_cost,
                "kimi_seconds": round(kimi_seconds, 3),
            }
        )
        print(
            f"hop {hop}  kimi={', '.join(called_names)}  prompt={prompt_tokens}  "
            f"completion={completion_tokens}  cost={kimi_cost}"
        )
    else:
        print(f"stopped after {MAX_HOPS} hops")

    if stopped_early:
        raise SystemExit(1)

    catalog_size = int(CATALOG_FILE.split("_")[1])
    called = [name for hop in hop_log for name in hop["kimi_tools"] if name != "(final answer)"]
    checks = kimi.golden_checks(catalog_size, called, final_answer.lower(), kimi.COMMENTS)
    jev_cost = sum(hop["jev_cost"] for hop in hop_log)
    kimi_cost = sum(hop["kimi_cost"] for hop in hop_log)
    result = {
        "catalog_file": CATALOG_FILE,
        "catalog_size": catalog_size,
        "router": JEV_MODEL,
        "argument_model": KIMI_MODEL,
        "hops": len(hop_log),
        "jev_input_tokens": sum(hop["jev_input_tokens"] for hop in hop_log),
        "jev_cost": jev_cost,
        "kimi_prompt_tokens": sum(hop["kimi_prompt_tokens"] for hop in hop_log),
        "kimi_completion_tokens": sum(hop["kimi_completion_tokens"] for hop in hop_log),
        "kimi_cost": kimi_cost,
        "cost": jev_cost + kimi_cost,
        "tools_called": called,
        "comments": kimi.COMMENTS,
        "final_answer": final_answer,
        "matched_golden": bool(checks) and all(checks.values()),
        "checks": checks,
        "hop_log": hop_log,
    }
    output_dir = ROOT / "output"
    output_dir.mkdir(exist_ok=True)
    result_path = output_dir / f"jev_catalog_{catalog_size}.json"
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"total cost: {result['cost']}")
    print(f"fake comments recorded: {json.dumps(kimi.COMMENTS)}")
    print(f"matched golden: {result['matched_golden']}")
    print(f"wrote {result_path}")


if __name__ == "__main__":
    main()
