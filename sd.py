# sd.py — Python 3.10+ / aiogram v3.21 / Pydantic v2
import asyncio
import json
import logging
import os
from typing import List, Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties  # <-- добавлено
from pydantic import BaseModel, HttpUrl, field_validator

# ============ CONFIG ============
# РЕКОМЕНДАЦИЯ: токен хранить в переменной окружения BOT_TOKEN
TOKEN = os.getenv("BOT_TOKEN") or "8482576456:AAFPhZXdyo_K__umsHkHT3SqI29epGQjiLI"
TARGET_CHAT_ID = int(os.getenv("TARGET_CHAT_ID") or 0)  # -100... (0 = постить в текущий чат)
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x}

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
    service_title: str
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

    if o.ad_links:
        lines.append("")
        lines.append("<b>Ссылки на объявления</b>" if len(o.ad_links) > 1 else "<b>Ссылка на объявление</b>")
        lines.extend(str(u) for u in o.ad_links)

    if o.maps_link or o.navigator_link:
        lines.append("")
        if o.maps_link:
            lines.append("Яндекс карты")
        if o.navigator_link:
            lines.append("Яндекс навигатор")

    if o.metro:
        lines.append("")
        lines.append("<b>До метро:</b>")
        for m in o.metro:
            km = f"{m.distance_km:.2f}".rstrip("0").rstrip(".")
            lines.append(f"{m.name}: {km} км.")

    if o.sum_rub is not None:
        lines.append(f"<b>Сумма заказа:</b> {o.sum_rub}")
    if o.to_pay_rub is not None:
        lines.append(f"<b>К оплате:</b> {o.to_pay_rub}")

    if o.details:
        lines.append("")
        lines.append("<b>Подробности:</b>")
        lines.append(o.details)

    if o.distance_zone_note:
        lines.append("<b>Удалённость:</b>")
        lines.append(o.distance_zone_note)

    return "\n".join(lines)

# ============ TG LAYER ============
router = Router(name="main")

@router.message(Command("start"))
async def cmd_start(m: Message):
    await m.answer("Готов публиковать заказы.\n• /demo — пример\n• /postjson {…} — пост из JSON")

@router.message(Command("demo"))
async def cmd_demo(m: Message):
    order = Order(
        order_id="907351",
        service_title="Выездная диагностика",
        city="Москва",
        contract="907351",
        date="02.08.2025",
        time="10 утра",
        address="Москва, Академика Семенова 79к3",
        client_presence="с клиентом",
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

@router.message(Command("postjson"))
async def cmd_postjson(m: Message, command: CommandObject):
    if ADMIN_IDS and m.from_user.id not in ADMIN_IDS:
        await m.answer("⛔ Недостаточно прав.")
        return
    if not command.args:
        await m.answer('Нужен JSON: /postjson {"order_id":"A1","service_title":"Эксперт на день"}')
        return
    try:
        data = json.loads(command.args)
        order = Order(**data)
    except Exception as e:
        log.warning("bad json from %s: %s", m.from_user.id, e)
        await m.answer(f"⚠️ Ошибка JSON/валидации: {e}")
        return
    await publish_order(m, order)

async def publish_order(m: Message, order: Order):
    text = build_order_text(order)
    kb = InlineKeyboardBuilder()
    kb.button(text="Забрать заказ", callback_data=f"take:{order.order_id}")
    kb.adjust(1)

    chat_id = TARGET_CHAT_ID if TARGET_CHAT_ID != 0 else m.chat.id
    await m.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=kb.as_markup(),
        disable_web_page_preview=False,
    )
    log.info("order %s published to %s by %s", order.order_id, chat_id, m.from_user.id)
    if chat_id != m.chat.id:
        await m.answer("✅ Заказ опубликован в целевой группе.")

@router.callback_query(F.data.startswith("take:"))
async def on_take(cb: CallbackQuery):
    try:
        order_id = cb.data.split(":", 1)[1]
        username = _mention_html(cb.from_user.id, cb.from_user.full_name)
        original = cb.message.html_text or ""
        if "Забрал:" in original or "Взял:" in original:
            await cb.answer("Заказ уже забран.", show_alert=True)
            log.info("order %s already taken; user=%s", order_id, cb.from_user.id)
            return
        new_text = original + f"\n\n<b>Забрал:</b> {username}"
        await cb.message.edit_text(new_text, reply_markup=None)
        await cb.answer("Заказ закреплён за тобой.")
        log.info("order %s taken by user=%s", order_id, cb.from_user.id)
    except Exception as e:
        log.exception("take handler failed")
        try:
            await cb.answer(f"⚠️ Ошибка: {e}", show_alert=True)
        except Exception:
            pass

# ============ ENTRY ============
async def main():
    # Проверка токена
    if not TOKEN or ":" not in TOKEN:
        raise RuntimeError("Не указан корректный BOT_TOKEN (env BOT_TOKEN или константа TOKEN).")

    # Главное изменение: parse_mode задаём через DefaultBotProperties
    bot = Bot(
        token=TOKEN,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    dp = Dispatcher()
    dp.include_router(router)

    log.info("Bot started")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())
