"""NutriLens API: persistent MySQL nutrition lookup with an optional AI-estimated fallback.

An AI estimate is NOT verified nutrition. UI must prompt the user to confirm recipe/portion.
"""
import base64
import binascii
import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal


from fastapi.responses import FileResponse

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, ForeignKey, String, Float, DateTime, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    raise RuntimeError("Set DATABASE_URL before starting the server")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)

class Base(DeclarativeBase):
    pass

class FoodRow(Base):
    __tablename__ = "nutrition_foods"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    kcal: Mapped[float] = mapped_column(Float)
    protein: Mapped[float] = mapped_column(Float)
    carbs: Mapped[float] = mapped_column(Float)
    fat: Mapped[float] = mapped_column(Float)
    fiber: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(40), default="ai_estimate")
    assumptions: Mapped[str] = mapped_column(String(1000), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class AliasRow(Base):
    __tablename__ = "food_aliases"
    id: Mapped[int] = mapped_column(primary_key=True)
    normalized: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    food_id: Mapped[int] = mapped_column(ForeignKey("nutrition_foods.id"))

app = FastAPI(title="NutriLens Nutrition API", version="0.1.0")
ALIASES = json.loads((Path(__file__).with_name("label_aliases.json")).read_text(encoding="utf-8"))

class ResolveRequest(BaseModel):
    label: str = Field(min_length=1, max_length=160)
    # Optional description of cooking method; this changes the estimate.
    preparation: str | None = Field(default=None, max_length=600)

class FoodOutput(BaseModel):
    id: str
    name: str
    kcal: float
    protein: float
    carbs: float
    fat: float
    fiber: float
    source: Literal["verified", "ai_estimate", "user_estimate"]
    assumptions: str = ""

class ResolveResponse(BaseModel):
    food: FoodOutput
    cached: bool

def normalize(label: str) -> str:
    return re.sub(r"[\s\-]+", "_", unicodedata.normalize("NFKC", label).strip().casefold())

def safe_slug(label: str) -> str:
    """Preserve Bengali identifiers; reject unsupported punctuation and length."""
    value = re.sub(r"[^\w]+", "_", normalize(label), flags=re.UNICODE).strip("_")
    return (value or "food")[:170]

def response_for(food: FoodRow, cached: bool) -> ResolveResponse:
    return ResolveResponse(food=FoodOutput(
        id=food.slug, name=food.name, kcal=food.kcal,
        protein=food.protein, carbs=food.carbs, fat=food.fat,
        fiber=food.fiber, source=food.source, assumptions=food.assumptions,
    ), cached=cached)

def estimate_per_100g(label: str, preparation: str | None) -> dict | None:
    """Ask AI for an approximate recipe-based 100g estimate; never label it verified.

    Without OPENAI_API_KEY we deliberately return None. Do not fabricate a value.
    """
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return None
    prompt = (
        "Estimate nutrition per exactly 100 grams of this cooked Bangladeshi food. "
        "The estimate is uncertain, varies by recipe and oil. Never claim lab accuracy. "
        "Return JSON with keys name, kcal, protein, carbs, fat, fiber, assumptions. "
        "Numbers must be numeric grams or kcal per 100g. If the dish is ambiguous, "
        "give assumptions and a conservative typical preparation. "
        f"Food: {label!r}. Preparation: {(preparation or 'unknown')!r}."
    )
    result = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
              "messages": [{"role": "user", "content": prompt}],
              "response_format": {"type": "json_object"}, "temperature": 0.1},
        timeout=25,
    )
    result.raise_for_status()
    estimate = json.loads(result.json()["choices"][0]["message"]["content"])
    for key in ("kcal", "protein", "carbs", "fat", "fiber"):
        number = float(estimate[key])
        # Guard rails for obviously invalid responses. These are not clinical validation.
        maximum = 900 if key == "kcal" else 100
        if not 0 <= number <= maximum:
            raise ValueError(f"AI returned invalid {key}={number}")
        estimate[key] = number
    estimate["name"] = str(estimate.get("name") or label)[:255]
    estimate["assumptions"] = str(estimate.get("assumptions") or "AI recipe estimate")[:1000]
    return estimate

@app.on_event("startup")
def startup():
    Base.metadata.create_all(engine)

@app.get("/health")
def health():
    return {"status": "ok"}


BASE_DIR = Path(__file__).resolve().parent

@app.get("/privacy-policy", include_in_schema=False)
def privacy_policy():
    return FileResponse(
        path=BASE_DIR / "static" / "privacy-policy.html",
        media_type="text/html"
    )





@app.post("/v1/nutrition/resolve", response_model=ResolveResponse)
def resolve(body: ResolveRequest):
    normalized = normalize(body.label)
    canonical = ALIASES.get(normalized, normalized)
    canonical_slug = safe_slug(canonical)
    with SessionLocal() as session:
        alias = session.scalar(select(AliasRow).where(AliasRow.normalized == normalized))
        found = session.get(FoodRow, alias.food_id) if alias else None
        if found is None:
            found = session.scalar(select(FoodRow).where(FoodRow.slug == canonical_slug))
        if found is not None:
            return response_for(found, cached=True)

    try:
        estimated = estimate_per_100g(body.label, body.preparation)
    except (requests.RequestException, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=502, detail="AI nutrition service failed: " + str(error))
    if estimated is None:
        raise HTTPException(status_code=404,
            detail="Not cached. Configure OPENAI_API_KEY for AI estimates or add a reviewed food record.")

    with SessionLocal.begin() as session:
        # Race-safe deployments should handle unique-key collisions on concurrent first requests.
        row = FoodRow(slug=canonical_slug, name=estimated["name"],
                      kcal=estimated["kcal"], protein=estimated["protein"],
                      carbs=estimated["carbs"], fat=estimated["fat"],
                      fiber=estimated["fiber"], source="ai_estimate",
                      assumptions=estimated["assumptions"])
        session.add(row)
        session.flush()
        session.add(AliasRow(normalized=normalized, food_id=row.id))
        value = response_for(row, cached=False)
    return value


class VisionRequest(BaseModel):
    image_base64: str = Field(min_length=100, max_length=7_500_000)

@app.post("/v1/vision/components")
def detect_plate_components(body: VisionRequest):
    """Optional mixed-plate vision assistant. Returns tentative labels, not probabilities or grams."""
    key = os.getenv("OPENAI_API_KEY", "")
    if not key:
        raise HTTPException(status_code=503, detail="Configure OPENAI_API_KEY for online plate analysis")
    try:
        raw = base64.b64decode(body.image_base64, validate=True)
    except binascii.Error:
        raise HTTPException(status_code=400, detail="Invalid base64 image")
    if not raw.startswith(b"\xff\xd8\xff") or len(raw) > 5_000_000:
        raise HTTPException(status_code=400, detail="A JPEG image under 5 MB is required")
    data_uri = "data:image/jpeg;base64," + body.image_base64
    prompt = (
        "Identify visually distinguishable components of this Bangladeshi meal. "
        "Pay special attention to cooked rice (ভাত), dal, fish, meat, roti, and vegetables. "
        "Do not treat an entire polao/biryani dish and its rice as separate servings. "
        "Return JSON with one key 'items' containing up to six objects with 'label' "
        "(short canonical English food name, e.g. cooked_rice, fish_curry) and "
        "'reason' (brief visible evidence). Do not invent nutrition numbers, weights, "
        "calibrated probabilities, or unseen ingredients. Uncertain items should be omitted."
    )
    try:
        reply = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
                  "messages": [{"role": "user", "content": [
                      {"type": "text", "text": prompt},
                      {"type": "image_url", "image_url": {"url": data_uri, "detail": "high"}}
                  ]}], "response_format": {"type": "json_object"},
                  "temperature": 0.1}, timeout=35,
        )
        reply.raise_for_status()
        result = json.loads(reply.json()["choices"][0]["message"]["content"])
        items = []
        for item in result.get("items", [])[:6]:
            label = str(item.get("label", "")).strip()[:120]
            if label:
                items.append({"label": label, "reason": str(item.get("reason", ""))[:200]})
        return {"items": items, "source": "vision_ai_suggestion", "requires_confirmation": True}
    except (requests.RequestException, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=502, detail="Vision provider error: " + str(error))
