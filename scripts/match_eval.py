"""Measure recipe-ingredient matching and "what can we cook" against hand-checked data.

Part (a) needs nothing but the golden set (backend/tests/fixtures/match_golden.json): each
ingredient name is matched against the household's products and compared with the product(s) a
person said it is (an empty list means "none of these"). A false "you have it" is worse than a
false "missing", so precision is the number to protect.

Part (b) runs the real service code against a database (e.g. a restored copy of production) and
reports the share of ingredient lines classed as staple and the top suggestions.

Usage (from backend/):
  uv run python ../scripts/match_eval.py                      # golden set only
  uv run python ../scripts/match_eval.py -v                   # ... listing every miss
  uv run python ../scripts/match_eval.py --db postgresql+asyncpg://user:pw@host/db \
      [--top 12] [--max-missing 1] [--course dinner ...]
"""

import argparse
import asyncio
import json
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from pantrynanny.recipes.match import Pantry, ProductCandidate, is_staple  # noqa: E402

GOLDEN = Path(__file__).resolve().parents[1] / "backend/tests/fixtures/match_golden.json"


def load_golden(path: Path = GOLDEN) -> dict:
    return json.loads(path.read_text())


def golden_pantry(golden: dict) -> Pantry:
    return Pantry(
        [
            ProductCandidate(
                id=i,
                name=p["name"],
                aliases=p["aliases"],
                total=Decimal(p["total"]),
                stock_unit=p["stock_unit"],
                package_size=Decimal(p["package_size"]) if p["package_size"] else None,
                package_unit=p["package_unit"],
            )
            for i, p in enumerate(golden["products"])
        ]
    )


def golden_report(golden: dict) -> dict:
    pantry = golden_pantry(golden)
    tp = fp = fn = tn = 0
    wrong: list[str] = []
    missed: list[str] = []
    for case in golden["cases"]:
        got = pantry.best(case["ingredient"])
        name = got.name if got else None
        expect = case["expect"]
        if name is not None and name in expect:
            tp += 1
        elif name is not None:
            fp += 1
            wrong.append(f"{case['ingredient']!r} -> {name!r} (expected {expect or 'none'})")
            if expect:
                fn += 1
        elif expect:
            fn += 1
            missed.append(f"{case['ingredient']!r} -> none (expected {expect})")
        else:
            tn += 1
    staple_ok = sum(is_staple(s) for s in golden["staples"])
    staple_fp = [s for s in golden["not_staples"] if is_staple(s)]
    return {
        "cases": len(golden["cases"]),
        "positives": sum(1 for c in golden["cases"] if c["expect"]),
        "precision": tp / (tp + fp) if tp + fp else 1.0,
        "recall": tp / (tp + fn) if tp + fn else 1.0,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "wrong": wrong,
        "missed": missed,
        "staples_recognised": f"{staple_ok}/{len(golden['staples'])}",
        "staples_missed": [s for s in golden["staples"] if not is_staple(s)],
        "not_staples_wrongly_staple": staple_fp,
    }


async def db_report(url: str, top: int, max_missing: int, courses: list[str]) -> None:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from pantrynanny.models import Household
    from pantrynanny.services import recipes as svc

    engine = create_async_engine(url)
    async with async_sessionmaker(engine)() as session:
        for hid, hname in (await session.execute(select(Household.id, Household.name))).all():
            recipes = await svc.list_recipes(session, hid)
            if not recipes:
                continue
            ctx = await svc.pantry(session, hid)
            pairs = [(r, svc.availability(r, ctx)) for r in recipes]
            status = Counter(it.status for _, a in pairs for it in a.items)
            lines = sum(status.values())
            print(f"\n## {hname}: {len(recipes)} recipes, {lines} ingredient lines")
            print("   line status: " + ", ".join(f"{k} {v / lines:.1%}" for k, v in status.items()))
            ranked = svc.rank(pairs, max_missing=max_missing, courses=courses or None)
            print(
                f"   max_missing={max_missing}"
                + (f" course={','.join(courses)}" if courses else "")
                + f": {len(ranked)} candidates"
            )
            cov = [a.coverage for _, a in ranked[:20]]
            if cov:
                print(
                    f"   top-20 coverage: min {min(cov):.2f} median {sorted(cov)[len(cov) // 2]:.2f}"
                    f" max {max(cov):.2f}; required lines median "
                    f"{sorted(a.required for _, a in ranked[:20])[len(cov) // 2]}"
                )
            for i, (r, a) in enumerate(ranked[:top], 1):
                miss = [it.ingredient.name for it in a.items if it.status == "missing"]
                print(
                    f"   {i:2}. {r.title[:60]:60} [{svc.course_of(r) or "-"}] {a.have}/{a.required}"
                    f" cov {a.coverage:.2f}" + (f"  missing: {', '.join(miss)}" if miss else "")
                )
    await engine.dispose()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--db")
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--max-missing", type=int, default=1)
    ap.add_argument("--course", action="append", default=[])
    args = ap.parse_args()
    rep = golden_report(load_golden())
    print(
        f"golden: {rep['cases']} cases ({rep['positives']} positive)  "
        f"precision {rep['precision']:.3f}  recall {rep['recall']:.3f}  "
        f"(tp {rep['tp']} fp {rep['fp']} fn {rep['fn']} tn {rep['tn']})"
    )
    print(f"staples: {rep['staples_recognised']} recognised, "
          f"{len(rep['not_staples_wrongly_staple'])} non-staples wrongly staple")
    if args.verbose:
        for title, key in (
            ("WRONG", "wrong"),
            ("MISSED", "missed"),
            ("STAPLE MISSED", "staples_missed"),
            ("NOT A STAPLE", "not_staples_wrongly_staple"),
        ):
            for line in rep[key]:
                print(f"  {title}: {line}")
    if args.db:
        asyncio.run(db_report(args.db, args.top, args.max_missing, args.course))


if __name__ == "__main__":
    main()
