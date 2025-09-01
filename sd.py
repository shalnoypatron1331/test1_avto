# Python 3.10
# pip install aiogram==3.* pydantic==1.*
import asyncio
import json
import logging
import os
from typing import List, Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    Message,
    CallbackQuery,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from pydantic import BaseModel, AnyHttpUrl, validator

# ===================== CONFIG =====================
TOKEN = os.getenv("BOT_TOKEN") or "PUT_YOUR_TOKEN_HERE"  # <-- лучше через env
TARGET_CHAT_ID = int(os.getenv("TARGET_CHAT_ID") or 0)   # <-- -100... (если 0 — постим в текущий чат)
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x}  # опционально

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("order-bot")

# ===================== DOMAIN =====================
class MetroPoint(BaseModel):
    name: str
    distance_km: float

class Order(BaseModel):
    # Ключевые поля под формат из скринов
    order_id: str
    service_title: str  # "Выездная диагностика" / "Эксперт на день" / "Комплекс" и т.п.
    city: str = "Москва"

    contract: Optional[str] = None           # "906787"
    date: Optional[str] = None               # "03.08.2025"
    time: Optional[str] = None               # "14:00-15:00" / "в течение дня"
    address: Optional[str] = None            # полный адрес
    client_presence: Optional[str] = None    # "с клиентом" / "без клиента"

    ad_links: List[AnyHttpUrl] = []          # ссылки на объявления
    maps_link: Optional[AnyHttpUrl] = None
    navigator_link: Optional[AnyHttpUrl] = None

    sum_rub: Optional[int] = None            # "Сумма заказа"
    to_pay_rub: Optional[int] = 0            # "К оплате"

    metro: List[MetroPoint] = []             # "До метро: ..."
    details: Optional[str] = None            # любые доп. детали (модель авто и т.п.)
    distance_zone_note: Optional[str] = None # "Зона 2: 1250 руб." и пр.

    @validator("service_title")
    def non_empty(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("service_title must be non-empty")
        return v

def mention_html(user_id: int, name: str) -> str:
    safe = (name or "специалист").replace("<", "").replace(">", "")
    return f'<a href="tg://user?id={user_id}">{safe}</a>'

def build_order_text(o: Order) -> str:
    # Шапка
    lines = [
        f"<b>‼ {o.service_title} ‼</b>",
        f"{o.city}",
    ]
    if o.contract:
        lines.append(f"<b>Договор:</b> {o.contract}")
    if o.date:
        lines.append(f"<b>Дата:</b> {o.date}")
    if o.time:
        lines.append(f"<b>Время:</b> {o.time}")
    if o.address:
        lines.append(f"<b>Адрес:</b> {o.address}")
    if o.client_presence:
        lines.append(f"<b>Присутствие клиента:</b> {o.client_presence}")

    # Ссылки
    if o.ad_links:
        lines.append("")
        if len(o.ad_links) == 1:
            lines.append("<b>Ссылка на объявление</b>")
        else:
            lines.append("<b>Ссылки на объявления</b>")
        for url in o.ad_links:
            lines.append(str(url))

    if o.maps_link or o.navigator_link:
        lines.append("")
        if o.maps_link:
            lines.append("Яндекс карты")
        if o.navigator_link:
            lines.append("Яндекс навигатор")

    # До метро
    if o.metro:
        lines.append("")
        lines.append("<b>До метро:</b>")
        for m in o.metro:
            # округлим до двух знаков как в примерах
            km = f"{m.distance_km:.2f}".rstrip("0").rstrip(".")
            lines.append(f"{m.name}: {km} км.")

    # Сумма
    if o.sum_rub is not None:
        lines.append(f"<b>Сумма заказа:</b> {o.sum_rub}")
    if o.to_pay_rub is not None:
        lines.append(f"<b>К оплате:</b> {o.to_pay_rub}")

    # Подробности/удалённость
    if o.details:
        lines.append("")
        lines.append("<b>Подробности:</b>")
        lines.append(o.details)

    if o.distance_zone_note:
        lines.append("<b>Удалённость:</b>")
        lines.append(o.distance_zone_note)

    return "\n".join(lines)

# ===================== TG LAYER =====================
router = Router(name="main")

@router.message(Command("start"))
async def cmd_start(m: Message):
    await m.answer("Готов публиковать заказы.\n"
                   "• /demo — пример сообщения\n"
                   "• /postjson {…} — опубликовать заказ из JSON")

@router.message(Command("demo"))
async def cmd_demo(m: Message):
    """Постим демонстрационный заказ в текущий чат (или в TARGET_CHAT_ID, если задан)."""
    try:
        order = Order(
            order_id="907351",
            service_title="Выездная диагностика",
            city="Москва",
            contract="907351",
            date="02.08.2025",
            time="10 утра",
            address="Москва, Академика Семенова 79к3",
            client_presence="с клиентом",
            ad_links=[],
            maps_link=None,
            navigator_link=None,
            sum_rub=13050,
            to_pay_rub=0,
            metro=[
                MetroPoint(name="Потапово", distance_km=1.55),
                MetroPoint(name="Бунинская аллея", distance_km=1.7),
                MetroPoint(name="Новомосковская (Коммунарка)", distance_km=2.67),
            ],
            details="Стандарт",
            distance_zone_note="Удалённость  Зона 2: 1250 руб.",
        )
        await publish_order(m, order)
    except Exception as e:
        log.exception("demo failed")
        await m.answer(f"⚠️ Ошибка demo: {e}")

@router.message(Command("postjson"))
async def cmd_postjson(m: Message, command: CommandObject):
    """
    /postjson {"order_id":"...", "service_title":"...", ...}
    JSON валидируется через Pydantic. Поля см. модель Order.
    """
    if ADMIN_IDS and m.from_user.id not in ADMIN_IDS:
        await m.answer("⛔ Недостаточно прав.")
        return

    if not command.args:
        await m.answer("Нужен JSON после команды. Пример:\n"
                       "/postjson {\"order_id\":\"A1\",\"service_title\":\"Эксперт на день\",\"city\":\"Москва\"}")
        return

    try:
        data = json.loads(command.args)
        order = Order(**data)
    except Exception as e:
        log.warning("bad json from %s: %s", m.from_user.id, e)
        await m.answer(f"⚠️ Ошибка парсинга/валидации JSON: {e}")
        return

    try:
        await publish_order(m, order)
    except Exception as e:
        log.exception("postjson failed")
        await m.answer(f"⚠️ Не удалось опубликовать заказ: {e}")

async def publish_order(m: Message, order: Order):
    """Формирует текст, публикует и ставит кнопку 'Забрать заказ'."""
    text = build_order_text(order)
    kb = InlineKeyboardBuilder()
    kb.button(text="Забрать заказ", callback_data=f"take:{order.order_id}")
    kb.adjust(1)

    chat_id = TARGET_CHAT_ID if TARGET_CHAT_ID != 0 else m.chat.id
    msg = await m.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=kb.as_markup(),
        disable_web_page_preview=False,  # ссылки видимыми
    )
    log.info("order %s published to chat %s by %s", order.order_id, chat_id, m.from_user.id)
    if chat_id != m.chat.id:
        await m.answer("✅ Заказ опубликован в целевую группу.")

@router.callback_query(F.data.startswith("take:"))
async def on_take(cb: CallbackQuery):
    """Первый клик закрепляет заказ, последующие получают alert."""
    try:
        order_id = cb.data.split(":", 1)[1]
        username = mention_html(cb.from_user.id, cb.from_user.full_name)

        original = cb.message.html_text or ""
        if "Взял:" in original or "Забрал:" in original:
            await cb.answer("Заказ уже забран.", show_alert=True)
            log.info("order %s already taken; user=%s", order_id, cb.from_user.id)
            return

        new_text = original + f"\n\n<b>Забрал:</b> {username}"
        # Убираем кнопку, чтобы исключить гонки
        await cb.message.edit_text(new_text, reply_markup=None)
        await cb.answer("Заказ закреплён за тобой.")
        log.info("order %s taken by user=%s", order_id, cb.from_user.id)

    except Exception as e:
        log.exception("take handler failed")
        # user-alert по ТЗ
        try:
            await cb.answer(f"⚠️ Ошибка: {e}", show_alert=True)
        except Exception:
            pass

# ===================== ENTRY =====================
async def main():
    token = TOKEN
    if token == "PUT_YOUR_TOKEN_HERE":
        raise RuntimeError("Не указан BOT_TOKEN (env BOT_TOKEN или константа TOKEN).")

    bot = Bot(token=token, parse_mode="HTML")
    dp = Dispatcher()
    dp.include_router(router)

    log.info("Bot started")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        log.info("Bot stopped")

if __name__ == "__main__":
    asyncio.run(main())