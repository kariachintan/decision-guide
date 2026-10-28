"""Conversational follow-up, grounded in the catalog.

Flow for every turn:
  1. Parse intent with small, explicit rules (no model needed).
  2. Compute the answer from the engine -> a plain-text draft + list of facts.
  3. Ask the provider to phrase it (SimulatedProvider returns the draft as-is).
  4. Guard: any item id in the reply must appear in the facts; otherwise fall
     back to the draft and flag it. This keeps a real model from inventing SKUs.

Intents supported: why-not <id>, what-is <id>, compare <id> and <id>,
budget change, "cheaper", "best", and a graceful out-of-scope answer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .catalog import Catalog
from .engine import Recommendation, compare, recommend
from .llm import Provider, ProviderError, SimulatedProvider
from .profile import NeedsProfile

ID_RE = re.compile(r"\b([a-z]{3}-\d{2})\b")
MONEY_RE = re.compile(r"\$?\s*(\d{2,5})(?:\.\d+)?")


@dataclass
class Turn:
    question: str
    intent: str
    reply: str
    facts: list[str]
    provider: str
    guard_triggered: bool = False


@dataclass
class ChatSession:
    catalog: Catalog
    profile: NeedsProfile
    provider: Provider = field(default_factory=SimulatedProvider)
    history: list[Turn] = field(default_factory=list)
    _rec: Recommendation | None = None

    # ---- public --------------------------------------------------------
    def recommendation(self) -> Recommendation:
        if self._rec is None:
            self._rec = recommend(self.catalog, self.profile)
        return self._rec

    def ask(self, question: str) -> Turn:
        q = question.strip()
        if not q:
            turn = Turn(q, "empty", "Ask me about an item id, a comparison, or a budget change.", [], self.provider.name)
            self.history.append(turn)
            return turn
        intent, draft, facts = self._answer(q)
        reply, guarded, provider_name = self._phrase(draft, facts)
        turn = Turn(q, intent, reply, facts, provider_name, guard_triggered=guarded)
        self.history.append(turn)
        return turn

    # ---- intent handling -----------------------------------------------
    def _answer(self, q: str) -> tuple[str, str, list[str]]:
        low = q.lower()
        ids = ID_RE.findall(low)
        rec = self.recommendation()

        if "compare" in low and len(ids) >= 2:
            return self._compare(ids[0], ids[1])
        if low.startswith("why not") or "why isn't" in low or "why didn't" in low:
            return self._why_not(ids[0]) if ids else ("why-not", "Which item? Give me its id (e.g. chr-03).", [])
        if "budget" in low or low.startswith("what if"):
            money = MONEY_RE.search(low)
            if money:
                return self._rebudget(float(money.group(1)))
        if "cheaper" in low or "cheapest" in low or "less expensive" in low:
            return self._cheaper()
        if ids:
            return self._what_is(ids[0])
        if any(w in low for w in ("best", "recommend", "top", "pick")):
            return self._best()
        return (
            "out-of-scope",
            "I can only answer about items in this catalog and your stated needs. "
            "Try 'what is <id>', 'why not <id>', 'compare <id> and <id>', or 'what if my budget is 300'.",
            [],
        )

    def _best(self) -> tuple[str, str, list[str]]:
        rec = self.recommendation()
        if not rec.top:
            return "best", f"Nothing in the catalog fits {self.profile.describe()}.", []
        s = rec.top
        facts = [self._fact(s.item.id), f"score {s.score} from {s.contributions}"]
        draft = (
            f"Top pick: {s.item.name} ({s.item.id}) at ${s.item.price:.0f}. "
            f"Strengths: {', '.join(s.strengths) or 'balanced'}. "
            f"Weaknesses: {', '.join(s.weaknesses) or 'none flagged'}."
        )
        return "best", draft, facts

    def _what_is(self, item_id: str) -> tuple[str, str, list[str]]:
        item = self.catalog.by_id(item_id)
        if item is None:
            return "what-is", f"There is no item {item_id} in the catalog.", []
        draft = f"{item.name} ({item.id}): ${item.price:.0f}, features {', '.join(item.features)}. {item.notes}".strip()
        return "what-is", draft, [self._fact(item.id)]

    def _why_not(self, item_id: str) -> tuple[str, str, list[str]]:
        rec = self.recommendation()
        item = self.catalog.by_id(item_id)
        if item is None:
            return "why-not", f"There is no item {item_id} in the catalog.", []
        excl = rec.exclusion_for(item_id)
        if excl:
            draft = f"{item.name} ({item.id}) was excluded: " + "; ".join(excl.reasons) + "."
            return "why-not", draft, [self._fact(item.id), "exclusion reasons: " + "; ".join(excl.reasons)]
        scored = rec.find(item_id)
        top = rec.top
        if scored and top and scored.item.id == top.item.id:
            return "why-not", f"{item.name} ({item.id}) is actually the top recommendation.", [self._fact(item.id)]
        if scored and top:
            draft = (
                f"{item.name} ({item.id}) scored {scored.score} vs {top.score} for {top.item.name} ({top.item.id}). "
                f"Its weaker points on your priorities: {', '.join(scored.weaknesses) or 'none - it lost on budget headroom'}."
            )
            return "why-not", draft, [self._fact(item.id), self._fact(top.item.id), f"scores {scored.score} vs {top.score}"]
        # fits constraints but fell outside the top-N shown
        from .engine import score_item

        s = score_item(item, self.profile)
        draft = f"{item.name} ({item.id}) fits your constraints but scored {s.score}, below the items shown."
        return "why-not", draft, [self._fact(item.id), f"score {s.score}"]

    def _compare(self, a: str, b: str) -> tuple[str, str, list[str]]:
        left, right = self.catalog.by_id(a), self.catalog.by_id(b)
        missing = [x for x, it in ((a, left), (b, right)) if it is None]
        if missing:
            return "compare", f"Unknown item id(s): {', '.join(missing)}.", []
        cmp = compare(left, right, self.profile.priorities)
        lines = [f"{row[0]}: {left.id}={row[1]} | {right.id}={row[2]} -> {row[3]}" for row in cmp.rows]
        draft = f"Comparing {left.name} ({left.id}) and {right.name} ({right.id}):\n" + "\n".join(lines)
        return "compare", draft, [self._fact(left.id), self._fact(right.id)] + lines

    def _rebudget(self, budget: float) -> tuple[str, str, list[str]]:
        self.profile = self.profile.with_budget(budget)
        self._rec = None
        rec = self.recommendation()
        if not rec.top:
            cheapest = min((i for i in self.catalog.items if i.category == self.profile.category), key=lambda i: i.price, default=None)
            hint = f" The cheapest {self.profile.category} is {cheapest.name} ({cheapest.id}) at ${cheapest.price:.0f}." if cheapest else ""
            return "budget", f"At ${budget:.0f} nothing in the {self.profile.category} category fits.{hint}", []
        s = rec.top
        draft = f"With a ${budget:.0f} budget the top pick becomes {s.item.name} ({s.item.id}) at ${s.item.price:.0f}."
        return "budget", draft, [self._fact(s.item.id), f"new budget {budget:.0f}"]

    def _cheaper(self) -> tuple[str, str, list[str]]:
        rec = self.recommendation()
        if not rec.top:
            return "cheaper", "There is no current recommendation to go cheaper than.", []
        current = rec.top.item
        cheaper = sorted(
            (i for i in self.catalog.items if i.category == current.category and i.price < current.price),
            key=lambda i: -i.price,
        )
        if not cheaper:
            return "cheaper", f"{current.name} ({current.id}) is already the cheapest {current.category} in the catalog.", [self._fact(current.id)]
        alt = cheaper[0]
        draft = (
            f"Next step down from {current.name} ({current.id}, ${current.price:.0f}) is "
            f"{alt.name} ({alt.id}) at ${alt.price:.0f}. {alt.notes}"
        ).strip()
        return "cheaper", draft, [self._fact(current.id), self._fact(alt.id)]

    # ---- phrasing + guard ----------------------------------------------
    def _phrase(self, draft: str, facts: list[str]) -> tuple[str, bool, str]:
        try:
            reply = self.provider.rephrase(draft, facts)
        except ProviderError as exc:
            return f"{draft}\n\n[model unavailable: {exc}; showing grounded draft]", True, "fallback"
        allowed = set(ID_RE.findall(" ".join(facts).lower())) | set(ID_RE.findall(draft.lower()))
        mentioned = set(ID_RE.findall(reply.lower()))
        if mentioned - allowed:
            return f"{draft}\n\n[model mentioned items not in the facts: {sorted(mentioned - allowed)}; showing grounded draft]", True, self.provider.name
        return reply, False, self.provider.name

    def _fact(self, item_id: str) -> str:
        item = self.catalog.by_id(item_id)
        assert item is not None
        return f"{item.id}: {item.name}, ${item.price:.0f}, features={list(item.features)}, attributes={item.attributes}, notes={item.notes!r}"
