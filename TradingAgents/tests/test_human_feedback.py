from scripts.human_feedback import (
    append_feedback,
    feedback_context_for,
    load_feedback,
    relevant_feedback,
)


def test_append_and_load_feedback(tmp_path):
    path = tmp_path / "feedback.jsonl"

    append_feedback(
        ticker="msn",
        trade_date="2026-01-29",
        agent="market",
        issue="Called attention bullish without price confirmation.",
        correction="Separate attention from price confirmation.",
        evidence="User reviewed MSN report.",
        path=path,
    )

    entries = load_feedback(path)
    assert len(entries) == 1
    assert entries[0].ticker == "MSN"
    assert entries[0].agent == "market"
    assert "Separate attention" in entries[0].correction


def test_relevant_feedback_filters_ticker_and_agent_group(tmp_path):
    path = tmp_path / "feedback.jsonl"
    append_feedback(
        ticker="MSN",
        agent="market",
        issue="Market issue",
        correction="Market correction",
        path=path,
    )
    append_feedback(
        ticker="MSN",
        agent="analyst",
        issue="Analyst issue",
        correction="Analyst correction",
        path=path,
    )
    append_feedback(
        ticker="HPG",
        agent="market",
        issue="Other ticker issue",
        correction="Other ticker correction",
        path=path,
    )
    append_feedback(
        ticker="*",
        agent="all",
        issue="Global issue",
        correction="Global correction",
        path=path,
    )

    entries = relevant_feedback(
        ticker="MSN",
        agents=("market", "analyst", "all"),
        path=path,
    )

    issues = {entry.issue for entry in entries}
    assert "Market issue" in issues
    assert "Analyst issue" in issues
    assert "Global issue" in issues
    assert "Other ticker issue" not in issues


def test_research_feedback_does_not_include_analyst_group(tmp_path):
    path = tmp_path / "feedback.jsonl"
    append_feedback(
        ticker="MSN",
        agent="analyst",
        issue="Analyst-only issue",
        correction="Analyst-only correction",
        path=path,
    )
    append_feedback(
        ticker="MSN",
        agent="research",
        issue="Research issue",
        correction="Research correction",
        path=path,
    )

    entries = relevant_feedback(
        ticker="MSN",
        agents=("bull", "research", "all"),
        path=path,
    )

    assert [entry.issue for entry in entries] == ["Research issue"]


def test_feedback_context_formats_prompt_block(tmp_path):
    path = tmp_path / "feedback.jsonl"
    append_feedback(
        ticker="MSN",
        agent="news",
        issue="Used post-date news as if it was known.",
        correction="Label all post-analysis-date context explicitly.",
        path=path,
    )

    context = feedback_context_for(
        ticker="MSN",
        agents=("news", "analyst", "all"),
        path=path,
    )

    assert "Human correction memory" in context
    assert "Used post-date news" in context
    assert "Label all post-analysis-date" in context
