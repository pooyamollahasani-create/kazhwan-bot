from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from bot.handlers import admin as a
_old=a._trip_actions_keyboard
def install():
    if getattr(a,"_prebooking_installed",False):return
    def wrapped(trip):
        m=_old(trip);rows=[list(r) for r in m.inline_keyboard]
        rows.insert(min(3,len(rows)),[InlineKeyboardButton("🎟 پیش‌رزرو",callback_data=f"pa:view:{trip.id}")])
        return InlineKeyboardMarkup(rows)
    a._trip_actions_keyboard=wrapped;a._prebooking_installed=True
