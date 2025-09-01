# sd.py — Python 3.10+ / aiogram v3 / Pydantic v2
import asyncio
import json
import logging
import os
from typing import List, Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from pydantic import BaseModel, HttpUrl, field_validator

# ============ CONFIG ============
TOKEN = os.getenv("8482576456:AAFPhZXdyo_K__umsHkHT3SqI29epGQjiLI") or "8482576456:AAFPhZXdyo_K__umsHkHT3SqI29epGQjiLI"  # <-- лучше через env
TARGET_CHAT_ID = int(os.getenv("TARGET_CHAT_ID") or 0)   # <-- -100... (если 0 — постим в текущий чат)
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x}  # опционально

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("order-bot")

# ============ DOMAIN ============
class MetroPoint(BaseModel):
    name: str
    distance_km: float

class Order(BaseModel):
    order_id: str
    service_title: str           # "Выездная диагностика" / "Эксперт на день" ...
    city: str = "Москва"

    contract: Optional[str] = None
    date: Optional[str] = None
    time: Optional[str] = None
    address: Optional[str] = None
    client_presence: Optional[str] = None

    ad_links: List[HttpUrl] = []
    maps_link: Optional[HttpUrl] = None
    navigator_link: Optional[HttpUrl] = None

    sum_rub: Optional[int] = None
    to_pay_rub: Optional[int] = 0

    metro: List[MetroPoint] = []
    details: Optional[str] = None
    distance_zone_note: Optional[str] = None

    @field_validator("service_title")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("service_title must be non-empty")
        return v

def _mention_html(user_id: int, name: str) -> str:
    safe = (name or "специалист").replace("<", "").replace(">", "")
    return f'<a href="tg://user?id={user_id}">{safe}</a>'

def build_order_text(o: Order) -> str:
    lines = [f"<b>‼ {o.service_title} ‼</b>", f"{o.city}"]
    if o.contract: lines.append(f"<b>Договор:</b> {o.contract}")
    if o.date: lines.append(f"<b>Дата:</b> {o.date}")
    if o.time: lines.append(f"<b>Время:</b> {o.time}")
    if o.address: lines.append(f"<b>Адрес:</b> {o.address}")
    if o.client_presence: lines.append(f"<b>Присутствие клиента:</b> {o.client_presence}")

    if o.ad_links:
        lines.append("")
        lines.append("<b>Ссылки на объявления</b>" if len(o.ad_links) > 1 else "<b>Ссылка на объявление</b>")
        lines.extend(str(u) for u in o.ad_links)

    if o.maps_link or o.navigator_link:
        lines.append("")
        if o.maps_link: lines.append("Яндекс карты")
        if o.navigator_link: lines.append("Яндекс навигатор")

    if o.metro:
        lines.append("")
        lines.append("<b>До метро:</b>")
        for m in o.metro:
            km = f"{m.distance_km:.2f}".rstrip("0").rstrip(".")
            lines.append(f"{m.name}: {km} км.")

    if o.sum_rub is not None: lines.append(f"<b>Сумма заказа:</b> {o.sum_rub}")
    if o.to_pay_rub is not None: lines.append(f"<b>К оплате:</b> {o.to_pay_rub}")

    if o.details:
