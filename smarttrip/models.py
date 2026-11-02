from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

Category = Literal["architecture", "museums", "parks", "history", "art", "food"]
Pace = Literal["calm", "medium", "active"]
Days = Annotated[StrictInt, Field(ge=1, le=5)]
Budget = Annotated[StrictInt, Field(ge=0, le=1_000_000)]
LABELS = {"architecture": "Архитектура", "museums": "Музеи", "parks": "Парки и прогулки",
          "history": "История", "art": "Искусство", "food": "Гастрономия"}
PACE_LABELS = {"calm": "Спокойный", "medium": "Умеренный", "active": "Активный"}
FIELDS = ("destination", "days", "budget", "interests", "exclude", "pace", "start_time")

class Draft(BaseModel):
    """Контракт NLP. Все поля присутствуют, неизвестные значения — null."""
    model_config = ConfigDict(extra="forbid")
    destination: Annotated[str, Field(max_length=100)] | None
    days: Days | None
    budget: Budget | None
    interests: list[Category] | None
    exclude: list[Category] | None
    pace: Pace | None
    start_time: str | None

    @field_validator("start_time")
    @classmethod
    def validate_time(cls, value):
        if value is None:
            return value
        import re
        if not re.fullmatch(r"(0[7-9]|1[0-6]):[0-5][0-9]", value):
            raise ValueError("Начало дня: от 07:00 до 16:59 в формате ЧЧ:ММ")
        return value

    @field_validator("interests", "exclude")
    @classmethod
    def unique_categories(cls, value):
        return list(dict.fromkeys(value)) if value is not None else None

class TripRequest(Draft):
    destination: Literal["Санкт-Петербург"]
    days: Days
    budget: Budget
    interests: Annotated[list[Category], Field(min_length=1, max_length=6)]
    exclude: Annotated[list[Category], Field(max_length=6)]
    pace: Pace
    start_time: str

    @model_validator(mode="after")
    def no_conflicts(self):
        if set(self.interests) & set(self.exclude):
            raise ValueError("Одна категория не может быть одновременно интересом и исключением")
        return self

class Place(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    latitude: float = Field(ge=59.8, le=60.1)
    longitude: float = Field(ge=30.0, le=30.6)
    tags: list[Category]
    price: int = Field(ge=0)
    duration: int = Field(ge=10, le=240)
    source_url: str
    opening_hours: str | None
    visit_mode: Literal["inside", "outdoor", "market"]
    price_note: str
    source_date: str

def normalize_city(value):
    if value is None:
        return None
    city = value.strip().lower().replace("ё", "е")
    if city in {"санкт-петербург", "санкт петербург", "петербург", "питер", "спб", "saint petersburg", "st petersburg"}:
        return "Санкт-Петербург"
    return value.strip()

def empty_draft():
    return {field: None for field in FIELDS}

