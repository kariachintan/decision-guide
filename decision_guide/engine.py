"""Filtering, scoring, explanation, and comparison.

Scoring is intentionally simple and inspectable:

  score = sum(weight(priority) * item.attr(priority)) + value_bonus

* Hard constraints (category, budget, must-have / avoid features) exclude items
  outright and are reported as exclusion reasons, never silently dropped.
* Priorities are weighted by order (1, 1/2, 1/3, ...): the first stated
  priority dominates, which matches how people actually state needs.
* A small budget-headroom bonus (max 0.5) breaks ties toward cheaper items
  without overriding priorities. Users who care about cost add "value" as a
  priority instead.

The output carries every contribution so the CLI and chat layer can explain
*why* without re-deriving anything.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .catalog import Catalog, Item
from .profile import NeedsProfile


@dataclass
class Exclusion:
    item: Item
    reasons: list[str]


@dataclass
class Scored:
    item: Item
    score: float
    contributions: dict[str, float] = field(default_factory=dict)
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)


@dataclass
class Recommendation:
    profile: NeedsProfile
    ranked: list[Scored]
    excluded: list[Exclusion]

    @property
    def top(self) -> Scored | None:
        return self.ranked[0] if self.ranked else None

    def find(self, item_id: str) -> Scored | None:
        return next((s for s in self.ranked if s.item.id == item_id), None)

    def exclusion_for(self, item_id: str) -> Exclusion | None:
        return next((e for e in self.excluded if e.item.id == item_id), None)


def priority_weights(priorities: tuple[str, ...]) -> dict[str, float]:
    """Harmonic weights: 1.0, 0.5, 0.33, ... so the first priority dominates."""
    return {p: round(1.0 / (i + 1), 3) for i, p in enumerate(priorities)}


def check_constraints(item: Item, profile: NeedsProfile) -> list[str]:
    reasons: list[str] = []
    if item.category != profile.category.lower():
        reasons.append(f"category is {item.category}, not {profile.category}")
    if profile.budget is not None and item.price > profile.budget:
        reasons.append(f"${item.price:.0f} exceeds budget ${profile.budget:.0f}")
    for feat in profile.must_have:
        if feat.lower() not in item.features:
            reasons.append(f"missing required feature '{feat}'")
    for feat in profile.avoid:
        if feat.lower() in item.features:
            reasons.append(f"has avoided feature '{feat}'")
    return reasons


def score_item(item: Item, profile: NeedsProfile) -> Scored:
    weights = priority_weights(profile.priorities)
    contributions: dict[str, float] = {}
    strengths, weaknesses = [], []
    for prio, weight in weights.items():
        value = item.attr(prio)
        contributions[prio] = round(weight * value, 2)
        if value >= 4:
            strengths.append(f"{prio} {value}/5")
        elif value <= 2:
            weaknesses.append(f"{prio} {value}/5")
    if not weights:  # no priorities stated: fall back to the item's own value rating
        contributions["value"] = float(item.attr("value"))
    if profile.budget:
        headroom = max(0.0, (profile.budget - item.price) / profile.budget)
        # Capped at 0.5 so it only breaks ties; "value" is a selectable priority for cost-sensitive users.
        contributions["budget-headroom"] = round(0.5 * headroom, 2)
    return Scored(
        item=item,
        score=round(sum(contributions.values()), 2),
        contributions=contributions,
        strengths=strengths,
        weaknesses=weaknesses,
    )


def recommend(catalog: Catalog, profile: NeedsProfile, limit: int = 3) -> Recommendation:
    ranked, excluded = [], []
    for item in catalog.items:
        reasons = check_constraints(item, profile)
        if reasons:
            excluded.append(Exclusion(item=item, reasons=reasons))
        else:
            ranked.append(score_item(item, profile))
    ranked.sort(key=lambda s: (-s.score, s.item.price, s.item.id))
    return Recommendation(profile=profile, ranked=ranked[:limit], excluded=excluded)


@dataclass
class Comparison:
    left: Item
    right: Item
    rows: list[tuple[str, str, str, str]]  # (dimension, left, right, edge)

    def winner_on(self, dimension: str) -> str:
        return next((r[3] for r in self.rows if r[0] == dimension), "tie")


def compare(left: Item, right: Item, priorities: tuple[str, ...] = ()) -> Comparison:
    rows: list[tuple[str, str, str, str]] = []
    cheaper = left.id if left.price < right.price else right.id if right.price < left.price else "tie"
    rows.append(("price", f"${left.price:.0f}", f"${right.price:.0f}", cheaper))
    dims = list(priorities) or sorted(set(left.attributes) | set(right.attributes))
    for dim in dims:
        lv, rv = left.attr(dim), right.attr(dim)
        edge = left.id if lv > rv else right.id if rv > lv else "tie"
        rows.append((dim, f"{lv}/5", f"{rv}/5", edge))
    only_left = sorted(set(left.features) - set(right.features))
    only_right = sorted(set(right.features) - set(left.features))
    rows.append(("unique features", ", ".join(only_left) or "-", ", ".join(only_right) or "-", "tie"))
    return Comparison(left=left, right=right, rows=rows)
