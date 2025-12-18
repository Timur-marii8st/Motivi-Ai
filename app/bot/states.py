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