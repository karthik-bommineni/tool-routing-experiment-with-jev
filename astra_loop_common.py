"""Shared full-menu loop for OpenAI GPT-6 Astra via OpenRouter.

Same catalogs, tasks, fakes, and golden checks as the Kimi experiment.
Writes output/astra_catalog_{50,100,200}.json.

Astra is roughly $10 / $50 per 1M tokens on OpenRouter. Expect these runs
to cost more than the Kimi baselines. Do not run all three casually.
"""

import importlib.util
import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("kimi_loop", ROOT / "kimi-loop-full.py")
kimi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kimi)

MODEL = "openai/gpt-6-astra"
MAX_HOPS = 12
MAX_TOKENS = 1000

TASKS = {
    50: {
        "catalog_file": "catalog_50_full.json",
        "task": """
Checkout latency started after a recent change in acme/payments. Find the open checkout issue. Find the recent commit that changed the checkout timeout, and read the file that commit touched. Check the open pull request for that change and whether CI failed. Also check secret scanning. Comment on the checkout issue with the exact body "suspect abc1234" if that is the commit you found. Do not comment on the UI issue. Do not merge the pull request and do not trigger a workflow. Finish with an incident note: the suspected commit, the timeout value you read, the pull request number, the CI result, and the secret-scanning result.
""",
    },
    100: {
        "catalog_file": "catalog_100_full.json",
        "task": """
Continue the acme/payments checkout investigation in the payments namespace. List the checkout pods, read the logs of the pod that is not ready, list warning events, and get the checkout Deployment. Decide whether the cluster symptom matches a client timeout of 200ms. Do not delete pods, do not scale the deployment, and do not apply a manifest. Finish with an incident note: the unhealthy pod name, what its logs say, the warning event, how many replicas are ready, and whether that matches the 200ms timeout.
""",
    },
    200: {
        "catalog_file": "catalog_200_full.json",
        "task": """
Close the acme/payments checkout investigation with the metrics. Query Prometheus for the checkout p95 latency over the last 15 minutes. Query Loki for deadline-exceeded errors from the checkout app. List the firing alert rule and the firing OnCall alert group. Decide whether the alert is a true positive and whether the timeout change should be rolled back. Do not create an incident, do not silence or delete an alert, and do not edit a dashboard. Finish with an incident note: the p95 value, how many matching logs you found, the alert state, and a yes or no on rolling back the timeout change, with the reason.
""",
    },
}


def run(catalog_size):
    if catalog_size not in TASKS:
        raise SystemExit(f"Unsupported catalog size: {catalog_size}")

    config = TASKS[catalog_size]
    catalog_file = config["catalog_file"]
    task = config["task"]

    kimi.COMMENTS.clear()
    catalog_path = ROOT / "catalog" / catalog_file
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    tools = [kimi.to_openai_tool(tool) for tool in catalog]

    messages = [
        {"role": "system", "content": kimi.SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]

    print(f"model: {MODEL}")
    print(f"tools in menu: {len(tools)}")
    print(f"task: {task}")
    print(f"max hops: {MAX_HOPS}")
    print(
        "note: Astra is much more expensive than Kimi. "
        "Stop the run if cost climbs faster than you expect."
    )

    total_cost = 0.0
    hop_log = []
    final_answer = ""

    for hop in range(1, MAX_HOPS + 1):
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {kimi.api_key}",
                "Content-Type": "application/json",
            },
            data=json.dumps(
                {
                    "model": MODEL,
                    "messages": messages,
                    "tools": tools,
                    "tool_choice": "auto",
                    "max_tokens": MAX_TOKENS,
                    "reasoning": {"effort": "low"},
                }
            ),
        )
        payload = response.json()
        if response.status_code != 200:
            print(f"hop {hop}  http {response.status_code}")
            print(json.dumps(payload, indent=2))
            raise SystemExit(1)

        usage = payload.get("usage") or {}
        cost = usage.get("cost") or 0
        total_cost += cost
        message = payload["choices"][0]["message"]
        tool_calls = message.get("tool_calls") or []
        names = [call["function"]["name"] for call in tool_calls] or ["(final answer)"]
        prompt_tokens = usage.get("prompt_tokens") or 0
        completion_tokens = usage.get("completion_tokens") or 0
        hop_log.append(
            {
                "hop": hop,
                "tools": names,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost": cost,
            }
        )
        print(
            f"hop {hop}  tools={', '.join(names)}  "
            f"prompt={prompt_tokens}  "
            f"completion={completion_tokens}  "
            f"cost={cost}"
        )

        if not tool_calls:
            final_answer = message.get("content") or ""
            print("final:")
            print(final_answer)
            break

        messages.append(kimi.assistant_message(message))
        for call in tool_calls:
            args = kimi.parse_args(call["function"].get("arguments"))
            result = kimi.fake_result(call["function"]["name"], args)
            print(f"  fake {call['function']['name']} -> {json.dumps(result)}")
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(result),
                }
            )
    else:
        print(f"stopped after {MAX_HOPS} hops")

    called = [
        name for hop in hop_log for name in hop["tools"] if name != "(final answer)"
    ]
    checks = kimi.golden_checks(
        catalog_size, called, final_answer.lower(), kimi.COMMENTS
    )
    result = {
        "catalog_file": catalog_file,
        "catalog_size": catalog_size,
        "model": MODEL,
        "hops": len(hop_log),
        "prompt_tokens": sum(hop["prompt_tokens"] for hop in hop_log),
        "completion_tokens": sum(hop["completion_tokens"] for hop in hop_log),
        "cost": total_cost,
        "tools_called": called,
        "comments": kimi.COMMENTS,
        "final_answer": final_answer,
        "matched_golden": bool(checks) and all(checks.values()),
        "checks": checks,
        "hop_log": hop_log,
    }
    output_dir = ROOT / "output"
    output_dir.mkdir(exist_ok=True)
    result_path = output_dir / f"astra_catalog_{catalog_size}.json"
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"total cost: {total_cost}")
    print(f"fake comments recorded: {json.dumps(kimi.COMMENTS)}")
    print(f"matched golden: {result['matched_golden']}")
    print(f"wrote {result_path}")
    return result
