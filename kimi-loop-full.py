import json
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("OPENROUTER_API_KEY")
if not api_key:
    raise SystemExit("OPENROUTER_API_KEY is missing. Put it in .env.")

MAX_HOPS = 12
# Switch this to catalog_100_full.json or catalog_200_full.json for the later tasks.
CATALOG_FILE = "catalog_200_full.json"
SYSTEM_PROMPT = (
    "You are the on-call engineer for the acme payments service. "
    "The GitHub repository is acme/payments. The Kubernetes namespace is payments. "
    "Grafana datasources for this service are Prometheus uid prometheus-payments and Loki uid loki-payments. "
    "Use a tool when the task needs a fact you do not already have. "
    "Do not merge pull requests, trigger workflows, delete or scale workloads, "
    "silence alerts, or create incidents unless the task tells you to. "
    "When the investigation is finished, stop calling tools and write the incident note."
)
TASK = """
Close the acme/payments checkout investigation with the metrics. Query Prometheus for the checkout p95 latency over the last 15 minutes. Query Loki for deadline-exceeded errors from the checkout app. List the firing alert rule and the firing OnCall alert group. Decide whether the alert is a true positive and whether the timeout change should be rolled back. Do not create an incident, do not silence or delete an alert, and do not edit a dashboard. Finish with an incident note: the p95 value, how many matching logs you found, the alert state, and a yes or no on rolling back the timeout change, with the reason.
"""

# Fake repo. Nothing here calls GitHub.
ISSUES = [
    {
        "number": 18,
        "title": "Checkout times out under load",
        "state": "open",
        "created_at": "2026-09-01T10:00:00Z",
        "user": "dev-a",
    },
    {
        "number": 42,
        "title": "Retry button missing on failed payments",
        "state": "open",
        "created_at": "2026-09-20T15:00:00Z",
        "user": "dev-b",
    },
]
COMMENTS = []


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


def parse_args(raw):
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def issue_by_number(number):
    for issue in ISSUES:
        if issue["number"] == number:
            return issue
    return None


def fake_result(name, args):
    owner = args.get("owner")
    repo = args.get("repo")
    in_payments = owner in (None, "acme") and repo in (None, "payments")

    if name == "list_issues":
        state = args.get("state")
        issues = ISSUES
        if state:
            issues = [issue for issue in issues if issue["state"] == state]
        if not in_payments:
            issues = []
        return {"owner": owner or "acme", "repo": repo or "payments", "issues": issues}

    if name == "search_issues":
        query = str(args.get("query", "")).lower()
        issues = [
            issue
            for issue in ISSUES
            if not query or query in issue["title"].lower() or query in "open"
        ]
        return {"issues": issues, "query": args.get("query")}

    if name == "issue_read":
        issue = issue_by_number(args.get("issue_number"))
        if issue is None:
            return {"error": "Issue not found in the fake acme/payments repo."}
        method = args.get("method", "get")
        if method == "get_comments":
            return {"issue": issue, "comments": COMMENTS}
        if method == "get_labels":
            return {"issue": issue, "labels": ["bug"]}
        return {"issue": issue, "method": method}

    if name == "add_issue_comment":
        number = args.get("issue_number")
        body = args.get("body") or args.get("reaction") or ""
        comment = {"id": 9000 + len(COMMENTS) + 1, "issue_number": number, "body": body}
        COMMENTS.append(comment)
        return {"ok": True, "comment": comment}

    if name == "issue_write":
        return {
            "ok": True,
            "note": "Fake write accepted. No GitHub issue was created or changed.",
            "method": args.get("method"),
            "title": args.get("title"),
        }

    if name == "get_me":
        return {"login": "octocat", "name": "Fake User"}

    if name == "get_teams":
        return {"teams": [{"name": "payments", "slug": "payments"}]}

    if name == "get_label":
        return {"name": args.get("name", "bug"), "color": "d73a4a", "description": "Something isn't working"}

    if name in {"list_discussions", "get_discussion"}:
        return {"discussions": [], "note": "The fake payments repo has no discussions."}

    if name in {"list_gists", "create_gist"}:
        return {"gists": [], "note": "The fake user has no gists."}

    if name == "actions_list":
        return {
            "workflows": [
                {
                    "name": "ci",
                    "latest_run_id": 555,
                    "head_sha": "abc1234",
                    "conclusion": "failure",
                    "branch": "main",
                }
            ]
        }

    if name == "get_job_logs":
        return {
            "run_id": args.get("run_id", 555),
            "job": "checkout-tests",
            "conclusion": "failure",
            "log": "checkout client: context deadline exceeded after 200ms",
        }

    if name in {"search_commits", "list_commits", "get_commit"}:
        return {
            "commits": [
                {
                    "sha": "abc1234",
                    "message": "lower checkout client timeout to 200ms",
                    "author": "dev-a",
                    "files": ["src/checkout/client.go"],
                }
            ]
        }

    if name == "get_file_contents":
        path = str(args.get("path", ""))
        if "client.go" in path or path == "":
            return {
                "path": "src/checkout/client.go",
                "content": "const checkoutTimeout = 200 * time.Millisecond",
            }
        return {"path": path, "content": ""}

    if name in {"list_pull_requests", "pull_request_read"}:
        return {
            "pull_requests": [
                {
                    "number": 77,
                    "title": "speed up checkout",
                    "state": "open",
                    "head_sha": "abc1234",
                }
            ]
        }

    if name == "list_secret_scanning_alerts":
        return {"alerts": []}

    if name in {"pods_list", "pods_list_in_namespace", "pods_get"}:
        pods = [
            {"name": "checkout-7f9", "namespace": "payments", "phase": "Running", "ready": False, "restarts": 14, "reason": "CrashLoopBackOff"},
            {"name": "checkout-abc", "namespace": "payments", "phase": "Running", "ready": True, "restarts": 0},
            {"name": "checkout-def", "namespace": "payments", "phase": "Running", "ready": True, "restarts": 0},
        ]
        if name == "pods_get":
            wanted = args.get("name")
            pods = [pod for pod in pods if pod["name"] == wanted] or pods[:1]
        return {"namespace": args.get("namespace", "payments"), "pods": pods}

    if name == "pods_log":
        return {
            "name": args.get("name", "checkout-7f9"),
            "namespace": args.get("namespace", "payments"),
            "log": "checkout client: context deadline exceeded after 200ms",
        }

    if name == "events_list":
        return {
            "events": [
                {
                    "type": "Warning",
                    "reason": "BackOff",
                    "object": "Pod/checkout-7f9",
                    "message": "Back-off restarting failed container checkout",
                }
            ]
        }

    if name in {"resources_get", "resources_list"}:
        return {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "name": "checkout",
            "namespace": "payments",
            "spec": {"replicas": 3},
            "status": {"readyReplicas": 1},
        }

    if name == "query_prometheus":
        return {
            "datasource": "prometheus-payments",
            "metric": "checkout_request_duration_seconds",
            "p95_over_15m": 4.2,
        }

    if name == "query_loki_logs":
        return {
            "datasource": "loki-payments",
            "query": '{app="checkout"} |= "deadline exceeded"',
            "matches_over_15m": 1200,
            "sample": "checkout client: context deadline exceeded after 200ms",
        }

    if name == "alerting_manage_rules":
        return {
            "rules": [
                {
                    "uid": "checkout-latency-high",
                    "title": "CheckoutLatencyHigh",
                    "state": "firing",
                    "summary": "checkout p95 is above 2s",
                }
            ]
        }

    if name == "list_alert_groups":
        return {
            "alert_groups": [
                {"id": "ag-18", "title": "CheckoutLatencyHigh", "state": "firing"}
            ]
        }

    if name == "get_alert_group":
        return {
            "id": "ag-18",
            "title": "CheckoutLatencyHigh",
            "state": "firing",
            "alerts": [
                {
                    "name": "CheckoutLatencyHigh",
                    "state": "firing",
                    "summary": "checkout p95 is above 2s",
                }
            ],
        }

    if name in {"list_dependabot_alerts", "get_dependabot_alert", "list_code_scanning_alerts", "get_code_scanning_alert"}:
        return {"alerts": [], "note": "The fake payments repo has no security alerts."}

    if name == "search_code":
        return {"items": [], "note": "The fake payments repo has no code index."}

    return {"ok": False, "note": f"No fake result for {name}."}


def golden_checks(catalog_size, called, note, comments):
    comment_on = {comment["issue_number"]: comment["body"] for comment in comments}

    def has_any(options):
        return any(name in called for name in options)

    if catalog_size == 50:
        return {
            "suspected_commit_abc1234": "abc1234" in note,
            "timeout_200ms": "200" in note,
            "pull_request_77": "77" in note,
            "ci_failed": "fail" in note,
            "no_secret_alerts": "secret" in note and "no" in note,
            "commented_suspect_on_18": comment_on.get(18) == "suspect abc1234",
            "no_comment_on_42": 42 not in comment_on,
            "no_merge_or_workflow_trigger": not has_any(["merge_pull_request", "actions_run_trigger"]),
        }
    if catalog_size == 100:
        return {
            "unhealthy_pod_checkout_7f9": "checkout-7f9" in note,
            "logs_mention_deadline_or_200ms": "deadline" in note or "200" in note,
            "warning_backoff": "backoff" in note or "back-off" in note,
            "one_of_three_replicas_ready": "1" in note and "3" in note,
            "matches_200ms_timeout": "match" in note or "consistent" in note or "yes" in note,
            "no_delete_or_scale": not has_any(["pods_delete", "resources_delete", "resources_scale"]),
        }
    if catalog_size == 200:
        return {
            "p95_is_4_2": "4.2" in note,
            "loki_match_count_1200": "1200" in note,
            "alert_firing": "firing" in note,
            "rollback_yes": "yes" in note and "roll" in note,
            "no_incident_or_silence": not has_any(["create_incident", "update_incident"]),
        }
    return {}


def assistant_message(message):
    stored = {
        "role": "assistant",
        "content": message.get("content"),
        "tool_calls": message.get("tool_calls") or [],
    }
    if message.get("reasoning_details"):
        stored["reasoning_details"] = message["reasoning_details"]
    return stored



def main():
    catalog_path = Path(__file__).resolve().parent / "catalog" / CATALOG_FILE
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    tools = [to_openai_tool(tool) for tool in catalog]

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        },
        {"role": "user", "content": TASK},
    ]

    print(f"tools in menu: {len(tools)}")
    print(f"task: {TASK}")
    print(f"max hops: {MAX_HOPS}")

    total_cost = 0.0
    hop_log = []
    final_answer = ""

    for hop in range(1, MAX_HOPS + 1):
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            data=json.dumps(
                {
                    "model": "moonshotai/kimi-k3",
                    "messages": messages,
                    "tools": tools,
                    "tool_choice": "auto",
                    "max_tokens": 500,
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

        messages.append(assistant_message(message))
        for call in tool_calls:
            args = parse_args(call["function"].get("arguments"))
            result = fake_result(call["function"]["name"], args)
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

    print(f"total cost: {total_cost}")
    print(f"fake comments recorded: {json.dumps(COMMENTS)}")

    catalog_size = int(CATALOG_FILE.split("_")[1])
    called = [name for hop in hop_log for name in hop["tools"] if name != "(final answer)"]
    note = final_answer.lower()
    checks = golden_checks(catalog_size, called, note, COMMENTS)

    result = {
        "catalog_file": CATALOG_FILE,
        "catalog_size": catalog_size,
        "model": "moonshotai/kimi-k3",
        "hops": len(hop_log),
        "prompt_tokens": sum(hop["prompt_tokens"] for hop in hop_log),
        "completion_tokens": sum(hop["completion_tokens"] for hop in hop_log),
        "cost": total_cost,
        "tools_called": called,
        "comments": COMMENTS,
        "final_answer": final_answer,
        "matched_golden": bool(checks) and all(checks.values()),
        "checks": checks,
        "hop_log": hop_log,
    }
    output_dir = Path(__file__).resolve().parent / "output"
    output_dir.mkdir(exist_ok=True)
    result_path = output_dir / f"catalog_{catalog_size}.json"
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"matched golden: {result['matched_golden']}")
    print(f"wrote {result_path}")


if __name__ == '__main__':
    main()
