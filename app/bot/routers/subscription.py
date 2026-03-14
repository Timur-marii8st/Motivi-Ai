from aiogram import Router, F
from aiogram.types import Message, LabeledPrice, PreCheckoutQuery, ContentType
from loguru import logger
from datetime import datetime, timezone
from redis.asyncio import Redis

from ...config import settings
from ...services.profile_services import get_or_create_user
from ...services.subscription_service import SubscriptionService

router = Router(name="subscription")

@router.message(F.text == "/subscribe")
async def cmd_subscribe(message: Message, session):
    """Sends an invoice for Telegram Stars."""
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)
    status = await SubscriptionService.get_user_status(user)
    
    # Status Message
    text = f"<b>💎 Motivi Премиум</b>\n\n"
    
    if user.subscription_ends_at:
        # Формат даты изменен на привычный для РФ: ДД.ММ.ГГГГ
        text += f"Статус: <b>ПРЕМИУМ</b>\nДействует до: {user.subscription_ends_at.strftime('%d.%m.%Y')}\n\n"
    elif status == "trial":
        days_left = settings.TRIAL_DAYS - (datetime.now(timezone.utc) - user.created_at).days
        text += f"Статус: <b>ПРОБНЫЙ</b>\nОсталось дней: {max(0, days_left)}\n\n"
    else:
        text += f"Статус: <b>ЗАВЕРШЕН</b>\n\n"

    text += (
        f"<b>Преимущества подписки:</b>\n"
        f"✅ {settings.LIMIT_DAILY_PREMIUM} сообщений в день (вместо {settings.LIMIT_DAILY_TRIAL})\n"
        f"✅ Неограниченная работа с памятью\n"
        f"✅ Приоритетная поддержка\n\n"
        f"<b>Цена: {settings.SUBSCRIPTION_PRICE_STARS} Звезд (XTR) / месяц</b>"
    )

    # Send Invoice (XTR = Telegram Stars)
    # provider_token is empty for Stars
    await message.answer_invoice(
        title="Motivi Премиум (1 месяц)",
        description="Полный доступ: больше сообщений + умная память",
        payload=f"sub_{user.id}_1m",
        provider_token="", 
        currency="XTR",
        prices=[LabeledPrice(label="1 месяц", amount=settings.SUBSCRIPTION_PRICE_STARS)],
        start_parameter="subscribe"
    )

@router.pre_checkout_query()
async def pre_checkout_handler(query: PreCheckoutQuery):
    """
    Telegram checks if the bot is ready to accept payment.
    We must answer with ok=True within 10 seconds.
    """
    await query.answer(ok=True)

@router.message(F.successful_payment)
async def successful_payment_handler(message: Message, session):
    """Handle successful payment."""
    payment = message.successful_payment
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)
    
    logger.info(f"Payment received: {payment.total_amount} {payment.currency} from user {user.id}")

    # Add 1 month subscription
    await SubscriptionService.add_subscription_time(session, user, months=1)
    await session.commit()

    # Invalidate cached subscription status so rate limiter immediately
    # recognises the user as premium (cache TTL is 5 min otherwise).
    try:
        redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        await redis.delete(f"sub_cache:{message.from_user.id}")
        await redis.aclose()
    except Exception as e:
        logger.warning("Failed to invalidate sub cache for user {}: {}", user.id, e)

    await message.answer(
        f"🎉 <b>Оплата прошла успешно!</b>\n\n"
        f"Теперь ты Премиум-пользователь. Твой новый лимит: {settings.LIMIT_DAILY_PREMIUM} сообщений в день.\n"
        f"Спасибо, что поддерживаешь развитие Motivi! 💖"
    )