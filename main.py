import os
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import (
    Owner, Restaurant, Review, Event, Reservation, Campaign, Discount, SchemaInfo
)

app = FastAPI(title="TouristTable API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Helpers ----------

def to_str_id(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not doc:
        return doc
    d = {**doc}
    if "_id" in d:
        d["_id"] = str(d["_id"])
    return d


def ensure_object_id(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id format")


# ---------- Root & Health ----------

@app.get("/")
def read_root():
    return {"message": "TouristTable Backend running", "version": "0.1.0"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set",
        "database_name": "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set",
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["connection_status"] = "Connected"
            try:
                response["collections"] = db.list_collection_names()
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:80]}"
        else:
            response["database"] = "⚠️ Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response


@app.get("/schema", response_model=SchemaInfo)
def get_schema_info():
    return SchemaInfo(collections=[
        "owner", "restaurant", "review", "event", "reservation", "campaign", "discount"
    ])


# ---------- Restaurants ----------

@app.post("/restaurants")
def create_restaurant(payload: Restaurant):
    rid = create_document("restaurant", payload)
    return {"_id": rid}


@app.get("/restaurants")
def list_restaurants(
    city: Optional[str] = None,
    cuisine: Optional[str] = None,
    q: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    radius_km: float = 5.0,
    limit: int = Query(50, le=200)
):
    filt: Dict[str, Any] = {}
    if city:
        filt["city"] = {"$regex": city, "$options": "i"}
    if cuisine:
        filt["cuisine"] = {"$in": [cuisine]}
    if q:
        filt["$or"] = [
            {"name": {"$regex": q, "$options": "i"}},
            {"description": {"$regex": q, "$options": "i"}},
            {"address": {"$regex": q, "$options": "i"}},
        ]
    # Basic bounding box filter for lat/lng to avoid requiring geo index
    if lat is not None and lng is not None:
        deg = radius_km / 111.0  # approx degrees per km
        filt["latitude"] = {"$gte": lat - deg, "$lte": lat + deg}
        filt["longitude"] = {"$gte": lng - deg, "$lte": lng + deg}

    docs = get_documents("restaurant", filt, limit)
    return [to_str_id(d) for d in docs]


@app.get("/restaurants/{restaurant_id}")
def get_restaurant(restaurant_id: str):
    doc = db["restaurant"].find_one({"_id": ensure_object_id(restaurant_id)})
    if not doc:
        raise HTTPException(404, "Restaurant not found")
    return to_str_id(doc)


class RestaurantPatch(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    cuisine: Optional[List[str]] = None
    description: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    price_level: Optional[int] = None
    accepts_reservations: Optional[bool] = None


@app.patch("/restaurants/{restaurant_id}")
def update_restaurant(restaurant_id: str, payload: RestaurantPatch):
    updates = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    if not updates:
        return {"updated": False}
    updates["updated_at"] = datetime.now(timezone.utc)
    res = db["restaurant"].update_one({"_id": ensure_object_id(restaurant_id)}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(404, "Restaurant not found")
    return {"updated": True}


# ---------- Reviews ----------

@app.post("/restaurants/{restaurant_id}/reviews")
def create_review(restaurant_id: str, payload: Review):
    if restaurant_id != payload.restaurant_id:
        raise HTTPException(400, "restaurant_id mismatch")
    rid = create_document("review", payload)
    # update avg rating
    pipe = [
        {"$match": {"restaurant_id": restaurant_id}},
        {"$group": {"_id": "$restaurant_id", "avg": {"$avg": "$rating"}, "count": {"$sum": 1}}}
    ]
    agg = list(db["review"].aggregate(pipe))
    if agg:
        avg = float(agg[0]["avg"])
        db["restaurant"].update_one({"_id": ensure_object_id(restaurant_id)}, {"$set": {"avg_rating": round(avg, 2)}})
    return {"_id": rid}


@app.get("/restaurants/{restaurant_id}/reviews")
def list_reviews(restaurant_id: str, limit: int = Query(50, le=200)):
    docs = get_documents("review", {"restaurant_id": restaurant_id}, limit)
    return [to_str_id(d) for d in docs]


# ---------- Reservations ----------

@app.post("/restaurants/{restaurant_id}/reservations")
def create_reservation(restaurant_id: str, payload: Reservation):
    if restaurant_id != payload.restaurant_id:
        raise HTTPException(400, "restaurant_id mismatch")
    res_id = create_document("reservation", payload)
    return {"_id": res_id}


class ReservationPatch(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None


@app.get("/restaurants/{restaurant_id}/reservations")
def list_reservations(restaurant_id: str, status: Optional[str] = None, limit: int = Query(100, le=500)):
    filt: Dict[str, Any] = {"restaurant_id": restaurant_id}
    if status:
        filt["status"] = status
    docs = get_documents("reservation", filt, limit)
    return [to_str_id(d) for d in docs]


@app.patch("/reservations/{reservation_id}")
def update_reservation(reservation_id: str, payload: ReservationPatch):
    updates = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    if not updates:
        return {"updated": False}
    updates["updated_at"] = datetime.now(timezone.utc)
    res = db["reservation"].update_one({"_id": ensure_object_id(reservation_id)}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(404, "Reservation not found")
    return {"updated": True}


# ---------- Events ----------

@app.post("/events")
def create_event(payload: Event):
    eid = create_document("event", payload)
    return {"_id": eid}


@app.get("/events")
def list_events(city: Optional[str] = None, upcoming_only: bool = True, limit: int = Query(50, le=200)):
    filt: Dict[str, Any] = {}
    if city:
        filt["city"] = {"$regex": city, "$options": "i"}
    if upcoming_only:
        # naive: assume date ISO string, filter >= today
        try:
            today = datetime.now(timezone.utc).date().isoformat()
            filt["date"] = {"$gte": today}
        except Exception:
            pass
    docs = get_documents("event", filt, limit)
    return [to_str_id(d) for d in docs]


# ---------- Discounts ----------

@app.post("/restaurants/{restaurant_id}/discounts")
def create_discount(restaurant_id: str, payload: Discount):
    if payload.restaurant_id != restaurant_id:
        raise HTTPException(400, "restaurant_id mismatch")
    did = create_document("discount", payload)
    return {"_id": did}


@app.get("/restaurants/{restaurant_id}/discounts")
def list_discounts(restaurant_id: str, active: Optional[bool] = None, limit: int = Query(50, le=200)):
    filt: Dict[str, Any] = {"restaurant_id": restaurant_id}
    if active is not None:
        filt["active"] = active
    docs = get_documents("discount", filt, limit)
    return [to_str_id(d) for d in docs]


# ---------- Campaigns ----------

@app.post("/restaurants/{restaurant_id}/campaigns")
def create_campaign(restaurant_id: str, payload: Campaign):
    if payload.restaurant_id != restaurant_id:
        raise HTTPException(400, "restaurant_id mismatch")
    cid = create_document("campaign", payload)
    return {"_id": cid}


@app.get("/restaurants/{restaurant_id}/campaigns")
def list_campaigns(restaurant_id: str, active: Optional[bool] = None, limit: int = Query(50, le=200)):
    filt: Dict[str, Any] = {"restaurant_id": restaurant_id}
    if active is not None:
        filt["active"] = active
    docs = get_documents("campaign", filt, limit)
    return [to_str_id(d) for d in docs]


# ---------- Analytics ----------

@app.get("/restaurants/{restaurant_id}/analytics")
def restaurant_analytics(restaurant_id: str):
    # reviews summary
    review_pipe = [
        {"$match": {"restaurant_id": restaurant_id}},
        {"$group": {"_id": "$rating", "count": {"$sum": 1}}}
    ]
    review_stats = {str(d["_id"]): d["count"] for d in db["review"].aggregate(review_pipe)}

    # reservation status summary
    rsv_pipe = [
        {"$match": {"restaurant_id": restaurant_id}},
        {"$group": {"_id": "$status", "count": {"$sum": 1}}}
    ]
    reservation_stats = {str(d["_id"]): d["count"] for d in db["reservation"].aggregate(rsv_pipe)}

    return {
        "reviews": review_stats,
        "reservations": reservation_stats,
    }


@app.get("/analytics/overview")
def overview_analytics():
    # By city
    city_pipe = [
        {"$group": {"_id": "$city", "count": {"$sum": 1}}}
    ]
    by_city = {str(d["_id"]): d["count"] for d in db["restaurant"].aggregate(city_pipe)}

    # By cuisine tag
    cuisine_pipe = [
        {"$unwind": "$cuisine"},
        {"$group": {"_id": "$cuisine", "count": {"$sum": 1}}}
    ]
    by_cuisine = {str(d["_id"]): d["count"] for d in db["restaurant"].aggregate(cuisine_pipe)}

    return {"restaurants_by_city": by_city, "restaurants_by_cuisine": by_cuisine}


# ---------- Translation (MVP) ----------

class MenuTranslateRequest(BaseModel):
    items: List[Dict[str, Any]]  # [{name, description, price, lang?}]
    target_lang: str = "en"


@app.post("/translate_menu")
def translate_menu(req: MenuTranslateRequest):
    # Simple dictionary-based translations for demo purposes
    # This is not exhaustive and only for MVP demonstration
    dictionary = {
        "en": {},
        "sq": {
            "salad": "sallatë", "cheese": "djathë", "grilled": "i pjekur",
            "chicken": "pulë", "fish": "peshk", "beef": "mish viçi", "bread": "bukë",
        },
        "it": {
            "salad": "insalata", "cheese": "formaggio", "grilled": "alla griglia",
            "chicken": "pollo", "fish": "pesce", "beef": "manzo", "bread": "pane",
        },
        "de": {
            "salad": "salat", "cheese": "käse", "grilled": "gegrillt",
            "chicken": "hähnchen", "fish": "fisch", "beef": "rindfleisch", "bread": "brot",
        },
        "fr": {
            "salad": "salade", "cheese": "fromage", "grilled": "grillé",
            "chicken": "poulet", "fish": "poisson", "beef": "boeuf", "bread": "pain",
        },
    }
    tgt = req.target_lang.lower()
    base = dictionary.get(tgt, {})

    def translate_text(text: str) -> str:
        if not text:
            return text
        out = []
        for token in text.split():
            low = token.lower().strip(",.!?;:")
            trans = base.get(low)
            out.append(trans if trans else token)
        return " ".join(out)

    translated = []
    for it in req.items:
        name = translate_text(str(it.get("name", "")))
        desc = translate_text(str(it.get("description", "")))
        translated.append({**it, "name": name, "description": desc, "lang": tgt})

    return {"items": translated, "lang": tgt}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
