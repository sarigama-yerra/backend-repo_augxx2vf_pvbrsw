"""
Database Schemas for TouristTable

Each Pydantic model below maps to a MongoDB collection using the lowercase
name of the class. Example: class Restaurant -> "restaurant" collection.
"""
from typing import List, Optional, Literal
from pydantic import BaseModel, Field, EmailStr

# Core domain models

class Owner(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None
    languages: List[str] = Field(default_factory=lambda: ["sq", "en"])  # supported languages
    is_active: bool = True

class Restaurant(BaseModel):
    owner_id: Optional[str] = Field(None, description="Reference to owner _id as string")
    name: str
    address: str
    city: str = Field(..., description="City in Albania")
    cuisine: List[str] = Field(default_factory=list)
    description: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    avg_rating: float = 0.0
    price_level: Optional[Literal[1,2,3,4]] = None  # 1=budget, 4=luxury
    menu: List[dict] = Field(default_factory=list, description="List of menu items with translations")
    images: List[str] = Field(default_factory=list)
    accepts_reservations: bool = True
    tourist_discounts: List[dict] = Field(default_factory=list)  # [{code, description, percent}]

class Review(BaseModel):
    restaurant_id: str
    user_name: str
    user_country: Optional[str] = None
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = None
    is_trusted: bool = True  # for MVP, assume phone/email verified off-platform

class Event(BaseModel):
    title: str
    city: str
    date: str  # ISO date string for simplicity
    description: Optional[str] = None
    category: Literal['festival','food','music','culture','other'] = 'food'
    venue: Optional[str] = None

class Reservation(BaseModel):
    restaurant_id: str
    name: str
    email: EmailStr
    party_size: int = Field(..., ge=1)
    date_time: str
    status: Literal['confirmed','pending','waitlist'] = 'pending'
    notes: Optional[str] = None

class Campaign(BaseModel):
    restaurant_id: str
    name: str
    message: str
    target_cuisines: List[str] = Field(default_factory=list)
    target_cities: List[str] = Field(default_factory=list)
    budget_eur: Optional[float] = None
    active: bool = True

class Discount(BaseModel):
    restaurant_id: str
    code: str
    description: Optional[str] = None
    percent: float = Field(..., ge=0, le=100)
    active: bool = True

# Public schema endpoint helper
class SchemaInfo(BaseModel):
    collections: List[str]
"""
Note: The Flames database viewer may read these via GET /schema endpoint.
"""
