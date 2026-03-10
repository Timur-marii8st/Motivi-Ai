from aiogram.fsm.state import StatesGroup, State

class Onboarding(StatesGroup):
    name = State()
    timezone = State()
    wake_time = State()
    bed_time = State()
    occupation = State()
    confirm = State()

class HabitCreation(StatesGroup):
    name = State()
    cadence = State()
    reminder = State()

class ProfileEdit(StatesGroup):
    name = State()
    age = State()
    timezone = State()
    wake_time = State()
    bed_time = State()
    goals = State()

class TriggerCreation(StatesGroup):
    name = State()
    prompt = State()
    schedule = State()
    weekdays = State()

class UserBotSetup(StatesGroup):
    """FSM states for connecting a personal Telegram account (MTProto userbot)."""
    waiting_phone = State()     # waiting for E.164 phone number
    waiting_code = State()      # waiting for the OTP sent by Telegram
    waiting_password = State()  # waiting for 2FA cloud password (if enabled)


class HabitStacking(StatesGroup):
    """FSM for confirming habit stacking suggestions."""
    confirm_stack = State()


class PersonaCustomization(StatesGroup):
    """FSM for persona customization flow."""
    select_tone = State()
    select_emoji = State()
    select_length = State()