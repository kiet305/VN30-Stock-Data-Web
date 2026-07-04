---
name: market-intel
description: Use for ticker-level market intelligence in TradingAgents, including price action, technical indicators, volume, support/resistance, public market context, and concise Vietnamese analyst reports.
---

# Market Intel

Use this skill when the user asks for stock market intelligence or a market analyst report.

## Procedure

1. Identify ticker and analysis date.
2. Check existing reports in `reports/`.
3. Prefer local warehouse/project data when available.
4. Use web search only for missing public context or current market context.
5. Produce a concise Vietnamese markdown report.

## Output Shape

```markdown
# Market Intel: <TICKER>

## Tong quan

## Du lieu da dung

## Tin hieu chinh

## Rui ro va data gaps

## Ket luan

Rating: Neutral
```

Valid ratings: `Strong Bull`, `Slightly Bull`, `Neutral`, `Slightly Bear`, `Strong Bear`.

