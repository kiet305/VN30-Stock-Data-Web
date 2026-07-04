from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, ToolMessage

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.llm_runtime import (
    apply_llm_runtime_defaults,
    build_llm_kwargs,
)


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_runtime_env() -> None:
    repo_root = _repo_root()
    for candidate in (
        repo_root / ".env",
        repo_root.parent / ".env",
    ):
        _load_env_file(candidate)


def _tool_call_field(call: Any, field: str, default: Any = None) -> Any:
    if isinstance(call, dict):
        return call.get(field, default)
    return getattr(call, field, default)


def run_market_agent(
    ticker: str,
    trade_date: str,
    model: str,
    max_steps: int,
    provider: str = "openai",
    feedback_context: str = "",
) -> tuple[str, list[str]]:
    _load_runtime_env()
    provider = apply_llm_runtime_defaults(provider, model)

    from tradingagents.agents.analysts.market_analyst import (
        clean_market_report,
        create_market_analyst,
    )
    from tradingagents.agents.utils.agent_utils import (
        build_instrument_context,
        resolve_instrument_identity,
    )
    from tradingagents.agents.utils.core_stock_tools import get_stock_data
    from tradingagents.agents.utils.market_data_validation_tools import (
        get_verified_market_snapshot,
    )
    from tradingagents.agents.utils.technical_indicators_tools import get_indicators
    from tradingagents.dataflows.config import set_config
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.propagation import Propagator
    from tradingagents.llm_clients import create_llm_client

    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = provider
    config["quick_think_llm"] = model
    config["deep_think_llm"] = model
    config["output_language"] = os.environ.get("TRADINGAGENTS_OUTPUT_LANGUAGE", "Vietnamese")
    config["data_vendors"] = {
        **config.get("data_vendors", {}),
        "core_stock_apis": "warehouse",
        "technical_indicators": "warehouse",
        "market_data_validation": "warehouse",
    }
    set_config(config)

    llm_kwargs = build_llm_kwargs(provider, config)
    llm = create_llm_client(
        provider=provider,
        model=model,
        base_url=config.get("backend_url"),
        **llm_kwargs,
    ).get_llm()

    tools = [get_stock_data, get_indicators, get_verified_market_snapshot]
    tools_by_name = {tool.name: tool for tool in tools}
    market_node = create_market_analyst(llm)

    identity = resolve_instrument_identity(ticker)
    state = Propagator().create_initial_state(
        ticker,
        trade_date,
        asset_type="stock",
        instrument_context=build_instrument_context(ticker, "stock", identity),
    )
    initial_message = ticker
    if feedback_context:
        initial_message += (
            "\n\n<human_feedback>\n"
            f"{feedback_context}\n"
            "</human_feedback>"
        )
    state["messages"] = [HumanMessage(content=initial_message)]

    trace: list[str] = []
    for _ in range(max_steps):
        output = market_node(state)
        state.update({key: value for key, value in output.items() if key != "messages"})
        state["messages"].extend(output["messages"])

        ai_message = output["messages"][-1]
        tool_calls = getattr(ai_message, "tool_calls", None) or []
        if not tool_calls:
            return clean_market_report(state.get("market_report") or str(ai_message.content)), trace

        for call in tool_calls:
            name = _tool_call_field(call, "name")
            args = _tool_call_field(call, "args", {}) or {}
            call_id = _tool_call_field(call, "id")
            if name not in tools_by_name:
                raise RuntimeError(f"Unknown tool requested by LLM: {name}")
            trace.append(f"{name}({args})")
            result = tools_by_name[name].invoke(args)
            state["messages"].append(
                ToolMessage(content=str(result), name=name, tool_call_id=call_id)
            )

    return clean_market_report(state.get("market_report") or str(state["messages"][-1].content)), trace


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the warehouse-backed Market Analyst.")
    parser.add_argument("--ticker", default="HPG")
    parser.add_argument("--date", default="2026-01-29")
    parser.add_argument("--provider", default="openai")
    parser.add_argument("--model", default="gpt-4.1")
    parser.add_argument("--max-steps", type=int, default=8)
    parser.add_argument(
        "--output",
        default=None,
        help="Markdown output path. Defaults to TradingAgents/reports/<ticker>_market_llm_<provider>_<date>.md",
    )
    args = parser.parse_args()

    report, trace = run_market_agent(
        args.ticker,
        args.date,
        args.model,
        args.max_steps,
        provider=args.provider,
    )
    output_path = (
        Path(args.output)
        if args.output
        else _repo_root() / "reports" / f"{args.ticker}_market_llm_{args.provider}_{args.date}.md"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")

    print(f"PROVIDER={args.provider}")
    print(f"MODEL={args.model}")
    print(f"OUTPUT={output_path}")
    print("TOOL_TRACE:")
    for item in trace:
        print(f"- {item}")
    print("REPORT_PREVIEW:")
    print(report[:5000])


if __name__ == "__main__":
    main()
