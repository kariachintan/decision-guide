"""The user's needs: what they want, what they can spend, what they value."""
from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class NeedsProfile:
    category: str
    budget: float | None = None
    priorities: tuple[str, ...] = ()
    must_have: tuple[str, ...] = ()
    avoid: tuple[str, ...] = ()

    def with_budget(self, budget: float | None) -> "NeedsProfile":
        return replace(self, budget=budget)

    def with_priority(self, priority: str) -> "NeedsProfile":
        if priority in self.priorities:
            return self
        return replace(self, priorities=self.priorities + (priority,))

    def describe(self) -> str:
        parts = [f"category={self.category}"]
        parts.append(f"budget={'any' if self.budget is None else f'${self.budget:.0f}'}")
        if self.priorities:
            parts.append("priorities=" + ",".join(self.priorities))
        if self.must_have:
            parts.append("must=" + ",".join(self.must_have))
        if self.avoid:
            parts.append("avoid=" + ",".join(self.avoid))
        return " ".join(parts)
