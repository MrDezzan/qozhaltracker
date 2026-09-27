from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

# Единый словарь типов событий на весь проект.
# Новые CV-модули (вес, здоровье, re-id) добавляют СЮДА новый тип,
# а не новую таблицу — схема БД при этом не меняется.
EventType = Literal[
    "detected",
    "counted",
    "weight_estimated",
    "health_alert",
    "face_id_matched",
    "zone_enter",
    "zone_exit",
]


class AnimalEvent(BaseModel):
    farm_id: str
    camera_id: str
    animal_id: str | None = None
    event_type: EventType
    payload: dict = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_row(self) -> dict:
        return self.model_dump(mode="json")
