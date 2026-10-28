import json

import pytest

from decision_guide.catalog import CatalogError, load_catalog


def test_default_catalog_loads(catalog):
    assert len(catalog.items) >= 10
    assert "chair" in catalog.categories()
    assert catalog.by_id("chr-02").name


def test_missing_file(tmp_path):
    with pytest.raises(CatalogError, match="not found"):
        load_catalog(tmp_path / "nope.json")


def test_invalid_json(tmp_path):
    f = tmp_path / "c.json"
    f.write_text("{not json")
    with pytest.raises(CatalogError, match="not valid JSON"):
        load_catalog(f)


@pytest.mark.parametrize(
    "items, msg",
    [
        ([{"id": "x-01"}], "missing keys"),
        ([{"id": "x-01", "category": "c", "name": "n", "price": "cheap", "features": [], "attributes": {}}], "numeric"),
        ([{"id": "x-01", "category": "c", "name": "n", "price": 1, "features": [], "attributes": {"q": 9}}], "1-5"),
        (
            [{"id": "x-01", "category": "c", "name": "n", "price": 1, "features": [], "attributes": {}}] * 2,
            "duplicate",
        ),
    ],
)
def test_malformed_items(tmp_path, items, msg):
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"items": items}))
    with pytest.raises(CatalogError, match=msg):
        load_catalog(f)


def test_empty_catalog_is_valid(tmp_path):
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"items": []}))
    assert load_catalog(f).items == []
