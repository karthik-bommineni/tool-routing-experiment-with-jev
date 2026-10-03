# Tool routing experiment: LLM vs Jev

Measure how an agent picks the **next tool** as the catalog grows from 50 → 100 → 200 tools.

Conditions so far (same tasks, catalogs, fake tool results, and golden checks):

1. **Kimi full-menu router** — Kimi K3 sees every tool schema on every hop (`tool_choice: auto`).
2. **Jev router** — Jev (`typesafe/jev-1.13`) picks one tool or `finish`; Kimi only fills arguments for that one tool (or writes the incident note).
3. **Astra full-menu router** — GPT-6 Astra sees the same full menu as Kimi (enterprise / OpenAI baseline).

An embedding router is paused and will come later.

## Setup

```powershell
uv sync
# put OPENROUTER_API_KEY in .env
```

## How to run

Tasks and golden answers live in [`testset/tasks.txt`](testset/tasks.txt).

```powershell
# Experiment 1 — Kimi sees the full menu
# Set CATALOG_FILE + TASK in the script, then:
uv run python kimi-loop-full.py

# Experiment 2 — Jev picks one tool per lap
# Set CATALOG_FILE + TASK in the script, then:
uv run python jev-kimi-loop.py

# Experiment 1b — Astra sees the full menu (one script per catalog size)
uv run python astra-loop-50.py
uv run python astra-loop-100.py
uv run python astra-loop-200.py
```

Results are written to `output/`:

| Condition | Output files |
|---|---|
| Kimi full menu | `output/catalog_{50,100,200}.json` |
| Jev + Kimi | `output/jev_catalog_{50,100,200}.json` |
| Astra full menu | `output/astra_catalog_{50,100,200}.json` |

## Catalogs

Built from real MCP tool definitions (GitHub → Kubernetes → Grafana):

| File | Tools |
|---|---|
| `catalog/catalog_50_full.json` | GitHub |
| `catalog/catalog_100_full.json` | GitHub + Kubernetes |
| `catalog/catalog_200_full.json` | GitHub + Kubernetes + Grafana |

## Results

### Scoreboard

| Catalog | Kimi full menu | Jev + Kimi | Astra full menu |
|---|---|---|---|
| **50** | Strict golden **pass** | Strict golden **fail** (extra comment); note + routing OK | Strict golden **pass** |
| **100** | Strict golden **pass** | Strict golden **pass** | Strict golden **pass** |
| **200** | Strict golden **fail** (`1,200`); note OK | Strict golden **fail** (`1,200`); note OK | Strict golden **fail** (`1,200`); note OK |

### Cost and hops

| Catalog | Metric | Kimi | Jev + Kimi | Astra |
|---|---|---|---|---|
| **50** | Hops | 6 | 10 | 4 |
| | Prompt tokens (filler LLM) | 55,734 | 18,866 | 27,638 |
| | Total cost | $0.086 | $0.086 | $0.144 |
| | Jev cost | — | $0.0034 | — |
| **100** | Hops | 3 | 5 | 3 |
| | Prompt tokens (filler LLM) | 55,032 | 5,035 | 43,108 |
| | Total cost | $0.078 | **$0.031** | $0.228 |
| | Jev cost | — | $0.0034 | — |
| **200** | Hops | 2 | 5 | 2 |
| | Prompt tokens (filler LLM) | 44,215 | 4,197 | 33,162 |
| | Total cost | $0.139 | **$0.031** | $0.244 |
| | Jev cost | — | $0.0040 | — |

### Takeaways

- At **50 tools**, Kimi and Jev+Kimi cost about the same (~$0.086). Astra passed golden cleanly but cost more (~$0.144). Jev's golden fail was an extra issue comment, not a wrong route.
- At **100 and 200**, Jev+Kimi is clearly cheapest (~$0.031). Full-menu Astra is the most expensive (~$0.23–$0.24) because OpenAI pricing is higher even when prompt tokens are similar or lower than Kimi.
- All three **200** notes were correct (p95 4.2, 1,200 Loki matches, firing alerts, rollback yes). The shared checker looks for `1200`, so `1,200` scores false for every model.
- Hop count is logged but is **not** part of the golden score. Jev is one tool per lap; full-menu LLMs can batch.

## Models

| Role | Model |
|---|---|
| Full-menu agent (cheap / OpenAI-compatible) | `moonshotai/kimi-k3` via OpenRouter |
| Full-menu agent (enterprise OpenAI baseline) | `openai/gpt-6-astra` via OpenRouter |
| Argument filler / note writer with Jev | `moonshotai/kimi-k3` via OpenRouter |
| Bounded next-tool choice | `typesafe/jev-1.13` via OpenRouter Decisions API |

## Repo layout

```
catalog/              # tool menus + builder
testset/tasks.txt     # prompts + golden answers
kimi-loop-full.py     # Kimi full-menu loop
jev-kimi-loop.py      # Jev + Kimi loop
astra_loop_common.py  # shared Astra runner
astra-loop-50.py      # Astra 50-tool task
astra-loop-100.py     # Astra 100-tool task
astra-loop-200.py     # Astra 200-tool task
output/               # recorded run JSON
sample-dry-runs/      # early single-call samples
CONTRIBUTING.md       # how to help grow the eval set
```

## What's Next

Embedding router (nearest-neighbor over tool descriptions) is paused. A Jev + Astra argument-filler pair is a natural follow-up.
