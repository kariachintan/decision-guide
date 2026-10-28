"""Command-line interface.

    decision-guide validate [--catalog PATH]
    decision-guide recommend --category chair --budget 350 --priority ergonomics [--must f] [--avoid f] [--json]
    decision-guide compare chr-02 chr-03 [--priority ...]
    decision-guide chat --category chair --budget 350 [--script FILE]
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .catalog import DEFAULT_CATALOG, Catalog, CatalogError, load_catalog
from .chat import ChatSession
from .engine import compare, recommend
from .llm import ProviderError, provider_from_env
from .profile import NeedsProfile

EXIT_OK, EXIT_USAGE, EXIT_DATA, EXIT_PROVIDER = 0, 2, 3, 4


def _load(path: str | Path, out) -> Catalog | None:
    try:
        return load_catalog(path)
    except CatalogError as exc:
        print(f"error: {exc}", file=out)
        return None


def _profile_from(args) -> NeedsProfile:
    return NeedsProfile(
        category=args.category.lower(),
        budget=args.budget,
        priorities=tuple(p.lower() for p in (args.priority or [])),
        must_have=tuple(f.lower() for f in (args.must or [])),
        avoid=tuple(f.lower() for f in (args.avoid or [])),
    )


def _validate_profile(catalog: Catalog, profile: NeedsProfile, out) -> bool:
    ok = True
    if profile.category not in catalog.categories():
        print(f"error: unknown category {profile.category!r}; choose from {catalog.categories()}", file=out)
        ok = False
    known = set(catalog.priorities) or {k for i in catalog.items for k in i.attributes}
    for p in profile.priorities:
        if p not in known:
            print(f"error: unknown priority {p!r}; choose from {sorted(known)}", file=out)
            ok = False
    return ok


def cmd_validate(args, out) -> int:
    catalog = _load(args.catalog, out)
    if catalog is None:
        return EXIT_DATA
    print(f"ok: {len(catalog.items)} items, categories={catalog.categories()}, priorities={sorted(catalog.priorities)}", file=out)
    return EXIT_OK


def cmd_recommend(args, out) -> int:
    catalog = _load(args.catalog, out)
    if catalog is None:
        return EXIT_DATA
    profile = _profile_from(args)
    if not _validate_profile(catalog, profile, out):
        return EXIT_USAGE
    rec = recommend(catalog, profile, limit=args.limit)
    if args.json:
        payload = {
            "profile": asdict(profile),
            "ranked": [
                {"id": s.item.id, "name": s.item.name, "price": s.item.price, "score": s.score,
                 "contributions": s.contributions, "strengths": s.strengths, "weaknesses": s.weaknesses}
                for s in rec.ranked
            ],
            "excluded": [{"id": e.item.id, "reasons": e.reasons} for e in rec.excluded],
        }
        print(json.dumps(payload, indent=2), file=out)
        return EXIT_OK
    print(f"Needs: {profile.describe()}", file=out)
    if not rec.ranked:
        print("No items fit. Closest exclusions:", file=out)
        same_cat = [e for e in rec.excluded if e.item.category == profile.category][:3]
        for e in same_cat or rec.excluded[:3]:
            print(f"  - {e.item.name} ({e.item.id}): {'; '.join(e.reasons)}", file=out)
        return EXIT_OK
    for rank, s in enumerate(rec.ranked, 1):
        print(f"\n#{rank} {s.item.name} ({s.item.id})  ${s.item.price:.0f}  score={s.score}", file=out)
        print(f"   why: " + ", ".join(f"{k}={v}" for k, v in s.contributions.items()), file=out)
        if s.strengths:
            print(f"   strengths: {', '.join(s.strengths)}", file=out)
        if s.weaknesses:
            print(f"   watch out: {', '.join(s.weaknesses)}", file=out)
        if s.item.notes:
            print(f"   notes: {s.item.notes}", file=out)
    in_cat_excluded = [e for e in rec.excluded if e.item.category == profile.category]
    if in_cat_excluded:
        print(f"\nExcluded {profile.category}s:", file=out)
        for e in in_cat_excluded:
            print(f"  - {e.item.name} ({e.item.id}): {'; '.join(e.reasons)}", file=out)
    return EXIT_OK


def cmd_compare(args, out) -> int:
    catalog = _load(args.catalog, out)
    if catalog is None:
        return EXIT_DATA
    left, right = catalog.by_id(args.left), catalog.by_id(args.right)
    missing = [x for x, it in ((args.left, left), (args.right, right)) if it is None]
    if missing:
        print(f"error: unknown item id(s): {', '.join(missing)}", file=out)
        return EXIT_USAGE
    cmp = compare(left, right, tuple(p.lower() for p in (args.priority or [])))
    width = max(len(r[0]) for r in cmp.rows)
    print(f"{'':{width}}  {left.id:<28} {right.id:<28} edge", file=out)
    for dim, lv, rv, edge in cmp.rows:
        print(f"{dim:{width}}  {lv:<28} {rv:<28} {edge}", file=out)
    return EXIT_OK


def cmd_chat(args, out) -> int:
    catalog = _load(args.catalog, out)
    if catalog is None:
        return EXIT_DATA
    profile = _profile_from(args)
    if not _validate_profile(catalog, profile, out):
        return EXIT_USAGE
    try:
        provider = provider_from_env()
    except ProviderError as exc:
        print(f"error: {exc}", file=out)
        return EXIT_PROVIDER
    session = ChatSession(catalog=catalog, profile=profile, provider=provider)
    print(f"[provider: {provider.name}{' - simulated, no model is called' if provider.name == 'simulated' else ''}]", file=out)
    rec = session.recommendation()
    if rec.top:
        print(f"Starting point: {rec.top.item.name} ({rec.top.item.id}) at ${rec.top.item.price:.0f}.", file=out)
    else:
        print(f"Starting point: nothing fits {profile.describe()} yet - try raising the budget.", file=out)

    if args.script:
        questions = [l for l in Path(args.script).read_text(encoding="utf-8").splitlines() if l.strip()]
    else:
        questions = None

    def loop():
        if questions is not None:
            yield from questions
        else:
            print("Type a question (or 'quit').", file=out)
            while True:
                try:
                    line = input("> ")
                except EOFError:
                    return
                if line.strip().lower() in {"quit", "exit"}:
                    return
                yield line

    for q in loop():
        if questions is not None:
            print(f"\n> {q}", file=out)
        turn = session.ask(q)
        print(f"[{turn.intent}] {turn.reply}", file=out)
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="decision-guide", description="Explainable recommendations over a synthetic catalog.")
    p.add_argument("--catalog", default=str(DEFAULT_CATALOG), help="path to catalog JSON")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("validate", help="check the catalog loads").set_defaults(func=cmd_validate)

    def needs(sp):
        sp.add_argument("--category", required=True)
        sp.add_argument("--budget", type=float)
        sp.add_argument("--priority", action="append", help="repeatable; order = importance")
        sp.add_argument("--must", action="append", help="required feature; repeatable")
        sp.add_argument("--avoid", action="append", help="disallowed feature; repeatable")

    r = sub.add_parser("recommend", help="rank items for your needs")
    needs(r)
    r.add_argument("--limit", type=int, default=3)
    r.add_argument("--json", action="store_true")
    r.set_defaults(func=cmd_recommend)

    c = sub.add_parser("compare", help="side-by-side comparison of two items")
    c.add_argument("left")
    c.add_argument("right")
    c.add_argument("--priority", action="append")
    c.set_defaults(func=cmd_compare)

    ch = sub.add_parser("chat", help="grounded follow-up questions")
    needs(ch)
    ch.add_argument("--script", help="file of questions, one per line (non-interactive)")
    ch.set_defaults(func=cmd_chat)
    return p


def main(argv: list[str] | None = None, out=None) -> int:
    out = out or sys.stdout
    args = build_parser().parse_args(argv)
    return args.func(args, out)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
