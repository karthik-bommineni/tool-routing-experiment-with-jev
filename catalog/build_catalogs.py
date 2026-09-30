"""Build catalog_50/100/200_full.json from published MCP tool lists."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AGENT = Path(r"C:\Users\karth\.cursor\projects\c-Users-karth-OneDrive-Desktop-tool-routing-exp\agent-tools")
GITHUB_DOC = AGENT / "1c1e7df2-6a60-477f-aa75-5dfa9d0aa519.txt"
K8S_DOC = AGENT / "3a34c8f0-607a-4e1b-89ee-fd19e381c891.txt"
GRAFANA_DOC = AGENT / "535c4f7b-2446-4c55-af64-a445993df0a0.txt"

TOOL_RE = re.compile(r"^- \*\*([A-Za-z0-9_-]+)\*\* - (.+)$")
GITHUB_FIELD_RE = re.compile(
    r"^ - `([A-Za-z0-9_]+)`: (.*) \(([^()]*)\)\s*$"
)
K8S_FIELD_RE = re.compile(
    r"^ - `([A-Za-z0-9_]+)` \(`([^`]+)`\)(?: \*\*\(required\)\*\*)? - (.*)$"
)


def field(name, type_name, description, required):
    return {
        "name": name,
        "type": type_name.strip(),
        "required": required,
        "description": " ".join(description.split()),
    }


def parse_bullet_tools(text, source, field_re, kind):
    tools = []
    current = None

    def finish():
        if current and current["name"] not in {tool["name"] for tool in tools}:
            tools.append(current)

    for raw in text.splitlines():
        line = raw.rstrip()
        header = TOOL_RE.match(line)
        if header and not line.startswith(" - "):
            finish()
            current = {
                "name": header.group(1),
                "description": " ".join(header.group(2).split()),
                "source": source,
                "oauth_scopes": [],
                "inputs": [],
            }
            continue
        if current is None:
            continue
        if line.startswith("- **") and "OAuth Challenge Scopes" not in line:
            continue
        if "OAuth Challenge Scopes" in line:
            scopes = re.findall(r"`([^`]+)`", line)
            current["oauth_scopes"] = scopes
            continue
        match = field_re.match(line)
        if not match:
            if line.startswith("(") and current["description"]:
                current["description"] = " ".join(
                    (current["description"] + " " + line).split()
                )
            continue
        if kind == "github":
            name, description, type_info = match.groups()
            required = "required" in type_info and "optional" not in type_info
            type_name = type_info.replace(", required", "").replace(", optional", "").strip()
            current["inputs"].append(field(name, type_name, description, required))
        else:
            name, type_name, description = match.groups()
            required = "**(required)**" in line or description.lower().startswith("required")
            if "(Optional" in description:
                required = False
            current["inputs"].append(field(name, type_name, description, required))
    finish()
    return tools


def parse_grafana(text):
    start = text.find("### Tools")
    end = text.find("## CLI Flags Reference")
    if start != -1 and end != -1:
        text = text[start:end]
    tools = []
    seen = set()
    row = re.compile(r"^\| `([A-Za-z0-9_]+)` \| ([^|]+) \| ([^|]+) \|")
    for line in text.splitlines():
        match = row.match(line)
        if not match:
            continue
        name, _category, description = match.groups()
        if name in seen:
            continue
        seen.add(name)
        tools.append(
            {
                "name": name,
                "description": " ".join(description.split()),
                "source": "grafana/mcp-grafana",
                "oauth_scopes": [],
                "inputs": [],
            }
        )
    return tools


def pool_from(tools, seen):
    pooled = {}
    for tool in tools:
        if tool["name"] in seen or tool["name"] in pooled:
            continue
        pooled[tool["name"]] = tool
    return pooled


def pull(pooled, names):
    picked = []
    for name in names:
        tool = pooled.pop(name, None)
        if tool:
            picked.append(tool)
    return picked


def fill(pooled, count):
    picked = []
    for name in list(pooled):
        if len(picked) >= count:
            break
        picked.append(pooled.pop(name))
    return picked


def main():
    base = json.loads((ROOT / "catalog_20_full.json").read_text(encoding="utf-8"))
    seen = {tool["name"] for tool in base}
    github = pool_from(
        parse_bullet_tools(
            GITHUB_DOC.read_text(encoding="utf-8"),
            "github/github-mcp-server",
            GITHUB_FIELD_RE,
            "github",
        ),
        seen,
    )
    k8s = pool_from(
        parse_bullet_tools(
            K8S_DOC.read_text(encoding="utf-8"),
            "containers/kubernetes-mcp-server",
            K8S_FIELD_RE,
            "k8s",
        ),
        seen,
    )
    grafana = pool_from(parse_grafana(GRAFANA_DOC.read_text(encoding="utf-8")), seen)

    github_first = pull(
        github,
        [
            "search_commits",
            "get_file_contents",
            "list_commits",
            "get_commit",
            "list_pull_requests",
            "pull_request_read",
            "list_secret_scanning_alerts",
        ],
    )
    catalog_50 = base + github_first + fill(github, 50 - len(base) - len(github_first))

    k8s_first = pull(
        k8s,
        [
            "pods_list",
            "pods_list_in_namespace",
            "pods_get",
            "pods_log",
            "events_list",
            "namespaces_list",
            "resources_list",
            "resources_get",
        ],
    )
    catalog_100 = catalog_50 + k8s_first + fill(k8s, 50 - len(k8s_first))
    if len(catalog_100) < 100:
        catalog_100 += fill(github, 100 - len(catalog_100))

    grafana_first = pull(
        grafana,
        [
            "query_prometheus",
            "query_loki_logs",
            "alerting_manage_rules",
            "list_alert_groups",
            "search_dashboards",
            "list_datasources",
            "get_dashboard_by_uid",
        ],
    )
    rest = list(grafana.values()) + list(k8s.values()) + list(github.values())
    catalog_200 = catalog_100 + grafana_first
    for tool in rest:
        if len(catalog_200) >= 200:
            break
        if tool["name"] not in {item["name"] for item in catalog_200}:
            catalog_200.append(tool)

    catalogs = {50: catalog_50, 100: catalog_100, 200: catalog_200}
    for size, tools in catalogs.items():
        if len(tools) != size:
            raise SystemExit(f"catalog {size} has {len(tools)} tools")
        path = ROOT / f"catalog_{size}_full.json"
        path.write_text(json.dumps(tools, indent=2) + "\n", encoding="utf-8")
        print(f"{size}: last={tools[-1]['name']} sources={sorted({tool['source'] for tool in tools})}")


if __name__ == "__main__":
    main()
