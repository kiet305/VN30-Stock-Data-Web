from scripts.run_research_synthesis_agent import (
    AnalystReport,
    DebateDecision,
    DebateRound,
    _debate_report_section,
    _parse_coordinator_decision,
    _run_research_debate,
    run_research_synthesis_agent,
)


def _reports():
    return {
        kind: AnalystReport(
            kind=kind,
            content="## Nhận định tổng quát\nHold with mixed evidence.\n## Kết luận tổng\nHold",
            path=None,
            trace=f"{kind}:test",
        )
        for kind in ("market", "fundamentals", "sentiment", "news")
    }


def test_parse_coordinator_high_confidence_stops_before_max_rounds():
    decision = _parse_coordinator_decision(
        """
        {
          "winner": "Bull",
          "confidence": "high",
          "continue_debate": true,
          "reason": "Bull has stronger evidence.",
          "bull_gaps": [],
          "bear_gaps": ["Bear did not quantify risk."],
          "next_instruction_for_bull": "",
          "next_instruction_for_bear": "Quantify the downside."
        }
        """,
        round_no=1,
        max_rounds=3,
    )

    assert decision.winner == "Bull"
    assert decision.confidence == "high"
    assert decision.continue_debate is False


def test_debate_loop_calls_bull_before_bear(monkeypatch):
    calls = []

    def fake_research_case(ticker, reports, model, side, provider, **kwargs):
        calls.append(side)
        return f"{side} argument", f"{side.lower()}:fake"

    def fake_decision(**kwargs):
        return (
            DebateDecision(
                winner="Tie",
                confidence="medium",
                continue_debate=False,
                reason="Balanced.",
            ),
            "coordinator:fake",
        )

    monkeypatch.setattr(
        "scripts.run_research_synthesis_agent._research_case",
        fake_research_case,
    )
    monkeypatch.setattr(
        "scripts.run_research_synthesis_agent._coordinator_decision",
        fake_decision,
    )

    bull, bear, rounds, trace = _run_research_debate(
        ticker="MSN",
        reports=_reports(),
        model="gpt-4.1",
        provider="openai",
        debate_rounds=2,
        bull_feedback="",
        bear_feedback="",
    )

    assert calls == ["Bull", "Bear"]
    assert bull == "Bull argument"
    assert bear == "Bear argument"
    assert len(rounds) == 1
    assert trace == ["round_1:bull:fake", "round_1:bear:fake", "coordinator:fake"]


def test_debate_report_section_includes_each_round_transcript():
    rounds = [
        DebateRound(
            round_no=1,
            bull_case="Bull round 1 case",
            bear_case="Bear round 1 rebuttal",
            decision=DebateDecision(
                winner="Tie",
                confidence="medium",
                continue_debate=True,
                reason="Both sides still need stronger evidence.",
                bull_gaps=["Quantify upside."],
                bear_gaps=["Quantify downside."],
                next_instruction_for_bull="Address downside.",
                next_instruction_for_bear="Address upside.",
            ),
        ),
        DebateRound(
            round_no=2,
            bull_case="Bull round 2 case",
            bear_case="Bear round 2 rebuttal",
            decision=DebateDecision(
                winner="Bear",
                confidence="high",
                continue_debate=False,
                reason="Bear directly rebutted the catalyst.",
                bull_gaps=["Catalyst is weak."],
                bear_gaps=[],
            ),
        ),
    ]

    section = _debate_report_section(rounds)

    assert '<section id="tranh-bien-theo-vong">' in section
    assert "### Vòng 1" in section
    assert "Bull round 1 case" in section
    assert "Bear round 2 rebuttal" in section
    assert "| 2 | Bear | high | Bear directly rebutted the catalyst. |" in section
