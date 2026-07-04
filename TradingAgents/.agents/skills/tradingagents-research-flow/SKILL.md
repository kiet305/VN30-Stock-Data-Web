---
name: tradingagents-research-flow
description: Use when running or modifying the TradingAgents stock research synthesis flow, especially Codex-backed research with `--provider codex`, analyst report generation, bull/bear researcher synthesis, report outputs, or Vietnamese stock analysis orchestration.
---

# TradingAgents Research Flow

Use this skill for full research synthesis tasks in this repository.

## Default Command

```powershell
python main.py --ticker <TICKER> --date <YYYY-MM-DD> --provider codex
```

Use `--output reports/<name>.md` when the caller wants a specific file path.

## Workflow

1. Confirm `ticker` and `date`.
2. Run `main.py` with `--provider codex` unless the user explicitly requests another provider.
3. Expect one synthesis report with these sections:
   - Market Analyst
   - Fundamentals Analyst
   - Sentiment Analyst
   - News Analyst
   - Bull Researcher
   - Bear Researcher
   - Final action summary
4. Keep output in Vietnamese.
5. Label post-date facts as post-date context.
6. Save reports under `reports/`.

## Key Files

- `main.py`: top-level CLI entrypoint.
- `scripts/run_research_synthesis_agent.py`: orchestration and Codex SDK/CLI integration.
- `tradingagents/llm_clients/api_key_env.py`: provider key mapping.
- `reports/`: generated markdown output.

## Checks

```powershell
python -B -c "import sys; sys.path.insert(0, '.'); import main; import scripts.run_research_synthesis_agent; print('import ok')"
python -m pip check
```

