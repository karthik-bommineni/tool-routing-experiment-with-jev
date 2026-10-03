# Contributing

Thanks for taking an interest in this experiment. The current results are based on only three investigation tasks (one each at 50, 100, and 200 tools), run across Kimi full-menu, Jev + Kimi, and Astra full-menu. A larger labeled eval set would make the accuracy claims much stronger.

## Ways to help

- Add more investigation-style tasks to `testset/tasks.txt` (prompt + golden answer; do not put "Look for" hints inside the prompt itself).
- Propose hard or ambiguous cases, especially near-duplicate tools.
- Fix scoring bugs (for example, treating `1,200` the same as `1200`).
- Re-run the loops with a pinned OpenRouter provider and share comparable cost numbers.
- Add a Jev + Astra argument-filler condition.
- Help with the paused embedding-router experiment once it is unpaused.

## Local setup

```powershell
uv sync
# put OPENROUTER_API_KEY in .env
```

Run Kimi full-menu (set `CATALOG_FILE` + `TASK` in the script first):

```powershell
uv run python kimi-loop-full.py
```

Run Jev + Kimi (set `CATALOG_FILE` + `TASK` in the script first):

```powershell
uv run python jev-kimi-loop.py
```

Run Astra full-menu (one script per catalog size):

```powershell
uv run python astra-loop-50.py
uv run python astra-loop-100.py
uv run python astra-loop-200.py
```

Astra is much more expensive than Kimi. Prefer the 50 script first if you are checking the harness.

## Pull requests

1. Fork the repo and create a branch.
2. Keep changes focused. Prefer adding tasks or scoring fixes over rewriting the harness unless needed.
3. Do not commit `.env`, API keys, local blog drafts, or embedding WIP.
4. Open a PR with a short description of what you changed and why.

Repo: https://github.com/karthik-bommineni/tool-routing-experiment-with-jev
