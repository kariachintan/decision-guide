from decision_guide.engine import check_constraints, compare, priority_weights, recommend, score_item
from decision_guide.profile import NeedsProfile


def test_budget_and_category_exclusions(catalog):
    rec = recommend(catalog, NeedsProfile("chair", budget=350))
    ids = {s.item.id for s in rec.ranked}
    assert "chr-03" not in ids
    assert "$689 exceeds budget $350" in rec.exclusion_for("chr-03").reasons[0]
    assert all(s.item.category == "chair" for s in rec.ranked)


def test_must_have_and_avoid(catalog):
    rec = recommend(catalog, NeedsProfile("monitor", must_have=("usb-c",), avoid=("curved",)), limit=10)
    ids = {s.item.id for s in rec.ranked}
    assert "mon-01" not in ids  # no usb-c
    assert "mon-04" not in ids  # curved
    assert {"mon-02", "mon-03", "mon-05"} <= ids


def test_first_priority_dominates(catalog):
    rec = recommend(catalog, NeedsProfile("chair", budget=350, priorities=("ergonomics", "quiet")))
    assert rec.top.item.id == "chr-02"
    rec2 = recommend(catalog, NeedsProfile("chair", budget=350, priorities=("portability", "ergonomics")))
    assert rec2.top.item.id == "chr-04"


def test_weights_are_harmonic():
    assert priority_weights(("a", "b", "c")) == {"a": 1.0, "b": 0.5, "c": 0.333}


def test_score_is_sum_of_contributions(catalog):
    s = score_item(catalog.by_id("chr-02"), NeedsProfile("chair", budget=400, priorities=("ergonomics",)))
    assert s.score == round(sum(s.contributions.values()), 2)
    assert "ergonomics 4/5" in s.strengths


def test_no_priorities_falls_back_to_value(catalog):
    s = score_item(catalog.by_id("kbd-01"), NeedsProfile("keyboard"))
    assert s.contributions == {"value": 5.0}


def test_empty_result_when_budget_too_low(catalog):
    rec = recommend(catalog, NeedsProfile("chair", budget=50))
    assert rec.ranked == []
    assert rec.top is None
    assert len(rec.excluded) == len(catalog.items)


def test_check_constraints_lists_every_reason(catalog):
    reasons = check_constraints(catalog.by_id("mon-04"), NeedsProfile("monitor", budget=100, must_have=("4k",), avoid=("curved",)))
    assert len(reasons) == 3


def test_compare_rows(catalog):
    cmp = compare(catalog.by_id("mon-02"), catalog.by_id("mon-03"), ("eye-comfort", "value"))
    assert cmp.winner_on("price") == "mon-02"
    assert cmp.winner_on("eye-comfort") == "mon-03"
    assert cmp.winner_on("value") == "mon-02"
    assert cmp.rows[-1][0] == "unique features"


def test_deterministic_ordering_ties_by_price_then_id(catalog):
    rec = recommend(catalog, NeedsProfile("webcam"), limit=5)
    scores = [s.score for s in rec.ranked]
    assert scores == sorted(scores, reverse=True)
