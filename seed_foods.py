"""Import reviewed per-100g foods into MySQL. CSV values must be independently validated."""
import csv
import sys
from sqlalchemy import select
from main import Base, engine, SessionLocal, FoodRow, AliasRow, normalize, safe_slug

if len(sys.argv) != 2:
    print("Usage: python seed_foods.py reviewed_foods.csv")
    raise SystemExit(2)
Base.metadata.create_all(engine)
with open(sys.argv[1], encoding="utf-8-sig", newline="") as f, SessionLocal.begin() as session:
    for r in csv.DictReader(f):
        slug = safe_slug(r["id"])
        food = session.scalar(select(FoodRow).where(FoodRow.slug == slug))
        if not food:
            food = FoodRow(slug=slug, name=r["name"], source="verified", assumptions="User-provided reviewed nutrition dataset",
                           **{k:float(r[k]) for k in ("kcal","protein","carbs","fat","fiber")})
            session.add(food); session.flush()
        for alias in [r["id"], r["name"], *r.get("aliases", "").split("|")]:
            alias = normalize(alias)
            if alias and not session.scalar(select(AliasRow).where(AliasRow.normalized == alias)):
                session.add(AliasRow(normalized=alias, food_id=food.id))
