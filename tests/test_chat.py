import pytest

from decision_guide.chat import ChatSession
from decision_guide.llm import AnthropicProvider, ProviderError
from decision_guide.profile import NeedsProfile


@pytest.fixture
def session(catalog):
    return ChatSession(catalog=catalog, profile=NeedsProfile("chair", budget=350, priorities=("ergonomics",)))


def test_why_not_excluded(session):
    t = session.ask("why not chr-03")
    assert t.intent == "why-not"
    assert "exceeds budget" in t.reply
    assert not t.guard_triggered


def test_why_not_ranked_lower(session):
    t = session.ask("why not chr-01")
    assert "scored" in t.reply and "chr-02" in t.reply


def test_why_not_top_pick(session):
    assert "top recommendation" in session.ask("why not chr-02").reply


def test_what_is_unknown_id(session):
    assert "no item zzz-99" in session.ask("what is zzz-99").reply


def test_compare(session):
    t = session.ask("compare chr-02 and chr-05")
    assert t.intent == "compare" and "price" in t.reply


def test_budget_change_reranks(session):
    before = session.recommendation().top.item.id
    t = session.ask("what if my budget is 150")
    assert t.intent == "budget"
    assert session.profile.budget == 150
    assert session.recommendation().top.item.id != before


def test_budget_too_low_gives_hint(session):
    t = session.ask("what if my budget is 40")
    assert "nothing" in t.reply and "cheapest chair" in t.reply


def test_cheaper_chain(session):
    t = session.ask("anything cheaper")
    assert t.intent == "cheaper" and "chr-01" in t.reply


def test_out_of_scope(session):
    assert session.ask("what is the weather").intent == "out-of-scope"


def test_empty_question(session):
    assert session.ask("   ").intent == "empty"


class HallucinatingClient:
    """Fake Anthropic client whose model invents an item id."""

    class messages:  # noqa: N801
        @staticmethod
        def create(**kwargs):
            class Block:
                text = "Honestly you should buy chr-99, it is the best chair."

            class Resp:
                content = [Block()]

            return Resp()


class FailingClient:
    class messages:  # noqa: N801
        @staticmethod
        def create(**kwargs):
            raise RuntimeError("503 overloaded")


def test_guard_rejects_invented_ids(catalog):
    s = ChatSession(catalog, NeedsProfile("chair", budget=350), provider=AnthropicProvider(client=HallucinatingClient(), model="fake"))
    t = s.ask("what is chr-02")
    assert t.guard_triggered
    assert "chr-99" not in t.reply.split("[model")[0]
    assert "Halden" in t.reply


def test_provider_failure_falls_back(catalog):
    s = ChatSession(catalog, NeedsProfile("chair", budget=350), provider=AnthropicProvider(client=FailingClient(), model="fake"))
    t = s.ask("what is chr-02")
    assert t.guard_triggered and t.provider == "fallback" and "Halden" in t.reply


def test_anthropic_provider_requires_config(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="ANTHROPIC_API_KEY"):
        AnthropicProvider()
