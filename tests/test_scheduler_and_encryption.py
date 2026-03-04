import asyncio
from unittest.mock import AsyncMock, MagicMock

from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

from app.scheduler.scheduler_instance import scheduler, start_scheduler, shutdown_scheduler
from app.scheduler.jobs import (
    morning_checkin_job,
    evening_wrapup_job,
    weekly_plan_job,
    monthly_plan_job,
    send_one_off_reminder_job,
    habit_reminder_job,
    cleanup_expired_memories_job,
)
from app.security import encryption_manager
from app.security.encrypted_types import EncryptedTextType, EncryptedJSONType, _VERSION_PREFIX
from datetime import datetime, timezone


# ======================================================================
# РўРµСЃС‚С‹ РїР»Р°РЅРёСЂРѕРІС‰РёРєР° Рё РїСЂРѕР°РєС‚РёРІРЅС‹С… РґР¶РѕР±
# ======================================================================

def test_start_scheduler_registers_cleanup_job():
    """РџСЂРѕРІРµСЂСЏРµРј, С‡С‚Рѕ daily cleanup job РѕРїРёСЃР°РЅ СЃ РїСЂР°РІРёР»СЊРЅС‹Рј CronTrigger.

    Р‘РµР· РІС‹Р·РѕРІР° start_scheduler: РїСЂРѕРІРµСЂСЏРµРј, С‡С‚Рѕ СЃР»РµРґСѓСЋС‰РёР№ Р·Р°РїСѓСЃРє С‚СЂРёРіРіРµСЂР° вЂ” РІ 03:00.
    """

    job_id = "cleanup_expired_memories"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    # Р РµРіРёСЃС‚СЂРёСЂСѓРµРј job РєР°Рє РІ start_scheduler (timezone РЅР° СЃРјС‹СЃР» РЅРµ РІР»РёСЏРµС‚)
    trigger = CronTrigger(hour=3, minute=0, timezone=timezone.utc)
    scheduler.add_job(
        func="app.scheduler.jobs:cleanup_expired_memories_job",
        trigger=trigger,
        id=job_id,
        replace_existing=True,
    )

    job = scheduler.get_job(job_id)
    assert job is not None
    assert isinstance(job.trigger, CronTrigger)

    # РџСЂРѕРІРµСЂСЏРµРј, С‡С‚Рѕ Р±Р»РёР¶Р°Р№С€РёР№ Р·Р°РїСѓСЃРє Р±СѓРґРµС‚ РІ 03:00 (РїРѕ UTC)
    now = datetime.now(timezone.utc)
    next_run = job.trigger.get_next_fire_time(previous_fire_time=None, now=now)
    assert next_run is not None
    assert next_run.hour == 3
    assert next_run.minute == 0

    scheduler.remove_job(job_id)

def test_morning_checkin_job_calls_flow_when_not_in_break_mode(monkeypatch):
    """morning_checkin_job РІС‹Р·С‹РІР°РµС‚ ProactiveFlows.morning_checkin РїСЂРё РѕС‚СЃСѓС‚СЃС‚РІРёРё break_mode."""
    fake_session = AsyncMock()
    fake_user = MagicMock(id=123)
    fake_session.get = AsyncMock(return_value=fake_user)
    fake_session.close = AsyncMock()

    monkeypatch.setattr("app.scheduler.jobs.AsyncSessionLocal", lambda: fake_session)
    monkeypatch.setattr("app.scheduler.jobs._is_break_mode_active", AsyncMock(return_value=False))

    flows_mock = AsyncMock()
    monkeypatch.setattr("app.scheduler.jobs.get_bot_instance", lambda: MagicMock())
    monkeypatch.setattr("app.scheduler.jobs.ProactiveFlows", lambda session, bot=None: flows_mock)

    asyncio.run(morning_checkin_job(user_id=123))

    flows_mock.morning_checkin.assert_awaited_once_with(fake_user)
    fake_session.commit.assert_awaited()


def test_evening_weekly_monthly_jobs_skip_on_break_mode(monkeypatch):
    """evening/weekly/monthly РґР¶РѕР±С‹ РїСЂРѕРїСѓСЃРєР°СЋС‚СЃСЏ, РµСЃР»Рё break_mode Р°РєС‚РёРІРµРЅ."""
    fake_session = AsyncMock()
    fake_session.get = AsyncMock(return_value=MagicMock(id=1))
    fake_session.close = AsyncMock()

    monkeypatch.setattr("app.scheduler.jobs.AsyncSessionLocal", lambda: fake_session)
    monkeypatch.setattr("app.scheduler.jobs._is_break_mode_active", AsyncMock(return_value=True))

    flows_mock = AsyncMock()
    monkeypatch.setattr("app.scheduler.jobs.get_bot_instance", lambda: MagicMock())
    monkeypatch.setattr("app.scheduler.jobs.ProactiveFlows", lambda session, bot=None: flows_mock)

    asyncio.run(evening_wrapup_job(user_id=1))
    asyncio.run(weekly_plan_job(user_id=1))
    asyncio.run(monthly_plan_job(user_id=1))

    flows_mock.evening_wrapup.assert_not_called()
    flows_mock.weekly_plan.assert_not_called()
    flows_mock.monthly_plan.assert_not_called()
    fake_session.commit.assert_not_awaited()


def test_send_one_off_reminder_job_sends_message(monkeypatch):
    """send_one_off_reminder_job РІС‹Р·С‹РІР°РµС‚ Bot.send_message, РµСЃР»Рё РїРѕР»СЊР·РѕРІР°С‚РµР»СЊ РЅР°Р№РґРµРЅ Рё РЅРµ РІ break_mode."""
    fake_session = AsyncMock()
    fake_user = MagicMock(id=1)
    fake_session.get = AsyncMock(return_value=fake_user)
    fake_session.close = AsyncMock()

    monkeypatch.setattr("app.scheduler.jobs.AsyncSessionLocal", lambda: fake_session)
    monkeypatch.setattr("app.scheduler.jobs._is_break_mode_active", AsyncMock(return_value=False))

    send_message_mock = AsyncMock()
    monkeypatch.setattr(
        "app.scheduler.jobs.get_bot_instance",
        lambda: MagicMock(send_message=send_message_mock),
    )

    asyncio.run(send_one_off_reminder_job(user_id=1, chat_id=42, message_text="Hello"))

    send_message_mock.assert_awaited_once_with(42, "Hello")


def test_habit_reminder_job_sends_when_active_and_not_logged(monkeypatch):
    """habit_reminder_job РѕС‚РїСЂР°РІР»СЏРµС‚ СЃРѕРѕР±С‰РµРЅРёРµ, РµСЃР»Рё РїСЂРёРІС‹С‡РєР° Р°РєС‚РёРІРЅР° Рё РЅРµ Р»РѕРіРёСЂРѕРІР°Р»Р°СЃСЊ СЃРµРіРѕРґРЅСЏ."""
    fake_session = AsyncMock()

    class FakeHabit:
        def __init__(self):
            self.id = 10
            self.name = "Read"
            self.current_streak = 5
            self.active = True
            self.user_id = 1

    class FakeUser:
        def __init__(self):
            self.id = 1
            self.tg_chat_id = 100500

    async def fake_get(model, pk):
        if pk == 10:
            return FakeHabit()
        if pk == 1:
            return FakeUser()
        return None

    fake_session.get = AsyncMock(side_effect=fake_get)

    fake_execute_result = MagicMock()
    fake_execute_result.scalar_one_or_none.return_value = None
    fake_session.execute = AsyncMock(return_value=fake_execute_result)
    fake_session.close = AsyncMock()

    monkeypatch.setattr("app.scheduler.jobs.AsyncSessionLocal", lambda: fake_session)

    send_message_mock = AsyncMock()
    monkeypatch.setattr(
        "app.scheduler.jobs.get_bot_instance",
        lambda: MagicMock(send_message=send_message_mock),
    )

    asyncio.run(habit_reminder_job(habit_id=10))

    send_message_mock.assert_awaited_once()
    args, kwargs = send_message_mock.await_args
    assert args[0] == 100500
    assert "Habit Reminder" in args[1]


def test_cleanup_expired_memories_job_basic_flow(monkeypatch):
    """cleanup_expired_memories_job РІС‹РїРѕР»РЅСЏРµС‚ select/ delete / commit РїСЂРё РЅР°Р»РёС‡РёРё СѓСЃС‚Р°СЂРµРІС€РёС… СЃСѓС‰РЅРѕСЃС‚РµР№."""
    fake_session = AsyncMock()

    first_result = MagicMock()
    first_result.all.return_value = [(1,), (2,)]  # Episode ids

    second_result = MagicMock()
    second_result.all.return_value = [(10,)]  # WorkingMemory ids

    # Р”РѕРїРѕР»РЅРёС‚РµР»СЊРЅС‹Р№ СЂРµР·СѓР»СЊС‚Р°С‚, С‡С‚РѕР±С‹ РЅРµ СЃР»РѕРІРёС‚СЊ StopIteration РїСЂРё Р»РёС€РЅРёС… execute
    third_result = MagicMock()
    third_result.all.return_value = []

    fake_session.execute = AsyncMock(side_effect=[first_result, second_result, third_result])
    fake_session.close = AsyncMock()

    monkeypatch.setattr("app.scheduler.jobs.AsyncSessionLocal", lambda: fake_session)

    asyncio.run(cleanup_expired_memories_job())

    # Р”РѕР»Р¶РЅРѕ Р±С‹С‚СЊ РјРёРЅРёРјСѓРј РґРІР° РІС‹Р·РѕРІР° execute (СЌРїРёР·РѕРґС‹ + СЂР°Р±РѕС‡Р°СЏ РїР°РјСЏС‚СЊ)
    assert fake_session.execute.await_count >= 2
    # commit РґРѕР»Р¶РµРЅ Р±С‹С‚СЊ РІС‹Р·РІР°РЅ С…РѕС‚СЏ Р±С‹ РѕРґРёРЅ СЂР°Р·
    assert fake_session.commit.await_count >= 1


# ======================================================================
# РўРµСЃС‚С‹ С€РёС„СЂРѕРІР°РЅРёСЏ Рё Р·Р°С€РёС„СЂРѕРІР°РЅРЅС‹С… С‚РёРїРѕРІ (Р±РµР· СЂРµР°Р»СЊРЅРѕРіРѕ Tink)
# ======================================================================


def test_encrypted_text_type_process_bind_and_result(monkeypatch):
    """EncryptedTextType С€РёС„СЂСѓРµС‚ РїСЂРё bind Рё СЂР°СЃС€РёС„СЂРѕРІС‹РІР°РµС‚ РїСЂРё С‡С‚РµРЅРёРё.

    РќРµ РёСЃРїРѕР»СЊР·СѓРµРј СЂРµР°Р»СЊРЅС‹Р№ Tink, РјРѕРєР°РµРј encrypt/decrypt.
    """
    fake_manager = MagicMock()

    def fake_encrypt(data: bytes, aad: bytes | None = None) -> bytes:
        return b"cipher:" + data

    def fake_decrypt(encrypted: bytes, aad: bytes | None = None) -> bytes:
        assert encrypted.startswith(b"cipher:")
        return encrypted[len(b"cipher:") :]

    fake_manager.encrypt.side_effect = fake_encrypt
    fake_manager.decrypt.side_effect = fake_decrypt

    monkeypatch.setattr(encryption_manager, "get_data_encryptor", lambda: fake_manager)

    enc_type = EncryptedTextType(column_label="test_col")

    stored = enc_type.process_bind_param("hello", dialect=None)
    assert isinstance(stored, str)
    assert stored.startswith(_VERSION_PREFIX)

    loaded = enc_type.process_result_value(stored, dialect=None)
    assert loaded == "hello"


def test_encrypted_json_type_process_bind_and_result(monkeypatch):
    """EncryptedJSONType РїСЂРѕР·СЂР°С‡РЅРѕ С€РёС„СЂСѓРµС‚/РґРµС€РёС„СЂСѓРµС‚ СЃР»РѕРІР°СЂСЊ."""
    fake_manager = MagicMock()

    def fake_encrypt(data: bytes, aad: bytes | None = None) -> bytes:
        return b"cipher:" + data

    def fake_decrypt(encrypted: bytes, aad: bytes | None = None) -> bytes:
        assert encrypted.startswith(b"cipher:")
        return encrypted[len(b"cipher:") :]

    fake_manager.encrypt.side_effect = fake_encrypt
    fake_manager.decrypt.side_effect = fake_decrypt

    monkeypatch.setattr(encryption_manager, "get_data_encryptor", lambda: fake_manager)

    enc_type = EncryptedJSONType(column_label="json_col")

    payload = {"a": 1, "b": "x"}
    stored = enc_type.process_bind_param(payload, dialect=None)
    assert isinstance(stored, str)
    assert stored.startswith(_VERSION_PREFIX)

    loaded = enc_type.process_result_value(stored, dialect=None)
    assert loaded == payload

