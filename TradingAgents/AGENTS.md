# TradingAgents Guidance

Use provider API keys or local runtimes for report generation. The web dashboard stores runtime LLM configuration in `reports/logs` and injects the selected provider key when launching `main.py`.

Example:

```bash
python main.py --ticker VRE --date 2026-01-29 --provider openai --model gpt-4.1
```

Do not print API keys, auth files, tokens, or raw secret values.
