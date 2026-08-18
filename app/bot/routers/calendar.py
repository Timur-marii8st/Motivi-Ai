"""
Calendar router — Motivi's internal calendar.

Events are created automatically by the userbot pipeline (LLM extraction from
incoming DMs, group messages and channel posts) or via the LLM
``add_calendar_event`` tool. This router provides the read/manage UI:

* /calendar — upcoming events for the next 7 days
* cal_open:{id} — event details with management buttons
* cal_done / cal_cancel / cal_postpone — lifecycle actions
"""

from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from ...services.calendar_service import CalendarService, format_local
from ...services.profile_services import get_or_create_user

router = Router(name="calendar")

SOURCE_LABELS = {
    "dm": "личное сообщение",
    "group": "группа",
    "channel": "канал",
    "chat": "добавлено в чате",
    "manual": "добавлено вручную",
}


def _esc(text: str) -> str:
    return html.escape(str(text))


async def _render_calendar_list(
    session, user
) -> tuple[str, InlineKeyboardMarkup | None]:
    tzname = user.user_timezone or "UTC"
    events = await CalendarService.list_upcoming(session, user.id, days=7)
    if not events:
        return (
            "📅 <b>Календарь пуст.</b>\n\n"
            "Я автоматически добавляю события из сообщений людей и каналов, "
            "за которыми слежу. Также можно попросить меня в чате: "
            "«добавь в календарь встречу завтра в 15:00»."
        ), None

    lines = ["📅 <b>Календарь на 7 дней:</b>", ""]
    buttons: list[list[InlineKeyboardButton]] = []
    for index, event in enumerate(events[:10], 1):
        time_label = format_local(event.starts_at, tzname)
        lines.append(f"{index}. {_esc(event.title)} — <b>{time_label}</b>")
        button_label = f"{index}. {event.title[:28]} — {time_label}"
        buttons.append(
            [
                InlineKeyboardButton(
                    text=button_label[:60],
                    callback_data=f"cal_open:{event.id}",
                )
            ]
        )

    if len(events) > 10:
        lines.append(f"\n…и ещё {len(events) - 10} событий.")
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=buttons)


async def _render_event_details(
    session, user, event_id: int
) -> tuple[str, InlineKeyboardMarkup | None]:
    tzname = user.user_timezone or "UTC"
    event = await CalendarService.get_for_user(session, event_id, user.id)
    if not event or event.status != "active":
        return await _render_calendar_list(session, user)

    lines = [f"📅 <b>{_esc(event.title)}</b>", ""]
    time_label = format_local(event.starts_at, tzname)
    if event.all_day:
        time_label = (
            format_local(event.starts_at, tzname, with_date=True) + " (весь день)"
        )
    lines.append(f"🕒 <b>{time_label}</b>")
    if event.ends_at:
        lines.append(f"🏁 До: {format_local(event.ends_at, tzname)}")
    if event.description:
        lines.append(f"📌 {_esc(event.description)}")
    source_label = SOURCE_LABELS.get(event.source_type)
    if source_label and event.source_name:
        lines.append(f"👤 Источник: {_esc(event.source_name)} ({source_label})")
    elif source_label:
        lines.append(f"👤 Источник: {source_label}")
    if event.reminded_at:
        lines.append("\n<i>Напоминание уже отправлено.</i>")

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Выполнено", callback_data=f"cal_done:{event.id}"
                ),
                InlineKeyboardButton(
                    text="🗑 Удалить", callback_data=f"cal_cancel:{event.id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⏰ +1 час", callback_data=f"cal_postpone:{event.id}:60"
                ),
                InlineKeyboardButton(
                    text="⏰ +1 день", callback_data=f"cal_postpone:{event.id}:1440"
                ),
            ],
            [InlineKeyboardButton(text="↩️ К списку", callback_data="cal_list")],
        ]
    )
    return "\n".join(lines), keyboard


@router.message(Command("calendar"))
async def cmd_calendar(message: Message, session):
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)
    text, keyboard = await _render_calendar_list(session, user)
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)


@router.callback_query(F.data == "cal_list")
async def cb_calendar_list(callback: CallbackQuery, session):
    user = await get_or_create_user(
        session, callback.from_user.id, callback.message.chat.id
    )
    text, keyboard = await _render_calendar_list(session, user)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("cal_open:"))
async def cb_calendar_open(callback: CallbackQuery, session):
    parts = callback.data.split(":")
    if len(parts) != 2:
        await callback.answer("Некорректное действие")
        return
    try:
        event_id = int(parts[1])
    except ValueError:
        await callback.answer("Некорректное действие")
        return

    user = await get_or_create_user(
        session, callback.from_user.id, callback.message.chat.id
    )
    text, keyboard = await _render_event_details(session, user, event_id)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("cal_done:"))
async def cb_calendar_done(callback: CallbackQuery, session):
    event = await _apply_action(callback, session, "done")
    if event:
        await callback.answer("✅ Отмечено выполненным")
    else:
        await callback.answer("Событие не найдено", show_alert=True)


@router.callback_query(F.data.startswith("cal_cancel:"))
async def cb_calendar_cancel(callback: CallbackQuery, session):
    event = await _apply_action(callback, session, "cancelled")
    if event:
        await callback.answer("🗑 Событие удалено")
    else:
        await callback.answer("Событие не найдено", show_alert=True)


@router.callback_query(F.data.startswith("cal_postpone:"))
async def cb_calendar_postpone(callback: CallbackQuery, session):
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Некорректное действие")
        return
    try:
        event_id = int(parts[1])
        minutes = int(parts[2])
    except ValueError:
        await callback.answer("Некорректное действие")
        return

    user = await get_or_create_user(
        session, callback.from_user.id, callback.message.chat.id
    )
    event = await CalendarService.postpone(session, event_id, user.id, minutes)
    if not event:
        await callback.answer("Событие не найдено", show_alert=True)
        return

    tzname = user.user_timezone or "UTC"
    await callback.answer(f"⏰ Перенесено на {format_local(event.starts_at, tzname)}")
    text, keyboard = await _render_event_details(session, user, event_id)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)


async def _apply_action(callback: CallbackQuery, session, status: str):
    parts = callback.data.split(":")
    if len(parts) != 2:
        await callback.answer("Некорректное действие")
        return None
    try:
        event_id = int(parts[1])
    except ValueError:
        await callback.answer("Некорректное действие")
        return None

    user = await get_or_create_user(
        session, callback.from_user.id, callback.message.chat.id
    )
    event = await CalendarService.set_status(session, event_id, user.id, status)
    if not event:
        return None

    text, keyboard = await _render_calendar_list(session, user)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    return event
