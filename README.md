# Tool routing experiment: LLM vs Jev

Measure how an agent picks the **next tool** as the catalog grows from 50 → 100 → 200 tools.

Two conditions so far (same tasks, catalogs, fake tool results, and golden checks):

1. **LLM full-menu router** — Kimi K3 sees every tool schema on every hop (`tool_choice: auto`).
2. **Jev router** — Jev (`typesafe/jev-1.13`) picks one tool or `finish`; Kimi only fills arguments for that one tool (or writes the incident note).

A third condition (embedding router) is paused and will come later.

## Setup

```powershell
uv sync
# put OPENROUTER_API_KEY in .env
```

## How to run

Tasks and golden answers live in [`testset/tasks.txt`](testset/tasks.txt).  
For each catalog size, set `CATALOG_FILE` and paste only the **Prompt** into `TASK`.

```powershell
# Experiment 1 — Kimi sees the full menu
uv run python kimi-loop-full.py

# Experiment 2 — Jev picks one tool per lap
uv run python jev-kimi-loop.py
```

Results are written to `output/`:

| Condition | Output files |
|---|---|
| Kimi full menu | `output/catalog_{50,100,200}.json` |
| Jev + Kimi | `output/jev_catalog_{50,100,200}.json` |

## Catalogs

Built from real MCP tool definitions (GitHub → Kubernetes → Grafana):

| File | Tools |
|---|---|
| `catalog/catalog_50_full.json` | GitHub |
| `catalog/catalog_100_full.json` | GitHub + Kubernetes |
| `catalog/catalog_200_full.json` | GitHub + Kubernetes + Grafana |

## Results

### Scoreboard

| Catalog | Exp 1: Kimi full menu | Exp 2: Jev routes + Kimi fills args |
|---|---|---|
| **50** | Strict golden **pass** | Strict golden **fail** (extra comment on issue 18); note + routing OK |
| **100** | Strict golden **pass** | Strict golden **pass** |
| **200** | Strict golden **fail** (`1,200` vs `1200` checker); note OK | Strict golden **fail** (`1,200` vs `1200` checker); note OK |

### Cost and hops

| Catalog | Metric | Exp 1 Kimi | Exp 2 Jev + Kimi |
|---|---|---|---|
| **50** | Hops | 6 | 10 |
| | Kimi prompt tokens | 55,734 | 18,866 |
| | Total cost | $0.086 | $0.086 |
| | Jev cost | — | $0.0034 |
| **100** | Hops | 3 | 5 |
| | Kimi prompt tokens | 55,032 | 5,035 |
| | Total cost | $0.078 | **$0.031** |
| | Jev cost | — | $0.0034 |
| **200** | Hops | 2 | 5 |
| | Kimi prompt tokens | 44,215 | 4,197 |
| | Total cost | $0.139 | **$0.031** |
| | Jev cost | — | $0.0040 |

### Takeaways

- At **50 tools**, total cost is about even. Jev routed sensibly; the golden fail was Kimi posting a second issue comment after Jev chose `add_issue_comment`.
- At **100 and 200**, Jev cuts total spend by roughly **2.5×–4.5×** because Kimi only sees one tool schema per lap instead of the full menu. Jev itself stays under about **$0.004** per run.
- Both **200** runs wrote the correct incident note (p95 4.2, 1,200 Loki matches, firing alerts, rollback yes). The shared checker looks for the substring `1200`, so `1,200` scores false.
- Hop count is logged but is **not** part of the golden score. Jev is one tool per lap; Kimi can batch several tools in one reply.

## Models

| Role | Model |
|---|---|
| Full-menu agent / argument filler / note writer | `moonshotai/kimi-k3` via OpenRouter |
| Bounded next-tool choice | `typesafe/jev-1.13` via OpenRouter Decisions API |

## Repo layout

```
catalog/           # tool menus + builder
testset/tasks.txt  # prompts + golden answers
kimi-loop-full.py  # experiment 1
jev-kimi-loop.py   # experiment 2
output/            # recorded run JSON
sample-dry-runs/   # early single-call samples
```

## Next

Embedding router (nearest-neighbor over tool descriptions) is paused. Planned as experiment 3 with the same tasks, catalogs, fakes, and golden checks.
