"""Catalog loading and validation.

All data is synthetic. Loading is deliberately strict: a malformed catalog is a
failure state the CLI reports, not something we paper over.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_CATALOG = Path(__file__).resolve().parent.parent / "data" / "catalog.json"
REQUIRED_ITEM_KEYS = {"id", "category", "name", "price", "features", "attributes"}


class CatalogError(ValueError):
    """Raised when a catalog file is missing, unreadable, or malformed."""


@dataclass(frozen=True)
class Item:
    id: str
    category: str
    name: str
    price: float
    features: tuple[str, ...]
    attributes: dict[str, int]
    notes: str = ""

    def attr(self, name: str) -> int:
        """Attribute score 1-5; missing attributes count as neutral (3)."""
        return self.attributes.get(name, 3)


@dataclass
class Catalog:
    items: list[Item]
    priorities: dict[str, str] = field(default_factory=dict)

    def by_id(self, item_id: str) -> Item | None:
        return next((i for i in self.items if i.id == item_id), None)

    def categories(self) -> list[str]:
        return sorted({i.category for i in self.items})

    def features(self) -> list[str]:
        return sorted({f for i in self.items for f in i.features})


def _parse_item(raw: dict[str, Any], index: int) -> Item:
    missing = REQUIRED_ITEM_KEYS - raw.keys()
    if missing:
        raise CatalogError(f"item #{index} is missing keys: {sorted(missing)}")
    try:
        price = float(raw["price"])
    except (TypeError, ValueError) as exc:
        raise CatalogError(f"item {raw.get('id')!r}: price must be numeric") from exc
    if price < 0:
        raise CatalogError(f"item {raw['id']!r}: price must be >= 0")
    attributes = raw["attributes"]
    if not isinstance(attributes, dict):
        raise CatalogError(f"item {raw['id']!r}: attributes must be an object")
    for key, value in attributes.items():
        if not isinstance(value, int) or not 1 <= value <= 5:
            raise CatalogError(f"item {raw['id']!r}: attribute {key!r} must be an int 1-5")
    return Item(
        id=str(raw["id"]),
        category=str(raw["category"]).lower(),
        name=str(raw["name"]),
        price=price,
        features=tuple(str(f).lower() for f in raw["features"]),
        attributes=dict(attributes),
        notes=str(raw.get("notes", "")),
    )


def load_catalog(path: str | Path = DEFAULT_CATALOG) -> Catalog:
    path = Path(path)
    if not path.exists():
        raise CatalogError(f"catalog not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CatalogError(f"catalog is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise CatalogError("catalog must be an object with an 'items' list")
    items = [_parse_item(raw, i) for i, raw in enumerate(data["items"])]
    ids = [i.id for i in items]
    dupes = sorted({x for x in ids if ids.count(x) > 1})
    if dupes:
        raise CatalogError(f"duplicate item ids: {dupes}")
    return Catalog(items=items, priorities=dict(data.get("priorities", {})))
