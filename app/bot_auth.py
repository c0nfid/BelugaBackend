import asyncio
import time
from typing import Dict
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from . import database, models

CODE_TTL = 300

login_attempts: Dict[str, dict] = {}

async def cleanup_task():
    """Фоновая задача: удаляет старые коды раз в минуту"""
    while True:
        try:
            now = time.time()
            to_delete = [
                code for code, data in login_attempts.items() 
                if now - data["created_at"] > CODE_TTL
            ]
            
            for code in to_delete:
                del login_attempts[code]
            
            if to_delete:
                print(f"🧹 Cleaned up {len(to_delete)} expired login codes.")
                
        except Exception as e:
            print(f"Error in cleanup task: {e}")
            
        await asyncio.sleep(60)

async def start_bot_polling(token: str):
    bot = Bot(token=token)
    dp = Dispatcher()

    @dp.message(CommandStart(deep_link=True))
    async def handler_start(message: Message, command: CommandObject):
        code = command.args
        
        if not code or code not in login_attempts:
            await message.answer("⚠️ Ссылка устарела или недействительна. Начните вход на сайте заново.")
            return

        if time.time() - login_attempts[code]["created_at"] > CODE_TTL:
            del login_attempts[code]
            await message.answer("⚠️ Время действия ссылки истекло (5 мин).")
            return

        tg_id = message.from_user.id
        
        with database.SessionLocal() as db:
            users = db.query(models.AuthTGUser).filter(models.AuthTGUser.chatid == tg_id).all()

        if not users:
            await message.answer("⛔ К вашему Telegram не привязан ни один игровой аккаунт.\nПерейдите в бота @BelugaVerification_bot и выполните привязку!")
            return

        if len(users) == 1:
            login_attempts[code]["status"] = "ready"
            login_attempts[code]["playername"] = users[0].playername
            await message.answer(f"✅ Вход выполнен как <b>{users[0].playername}</b>!", parse_mode="HTML")
            return

        builder = InlineKeyboardBuilder()
        for user in users:
            builder.button(text=f"👤 {user.playername}", callback_data=f"login:{code}:{user.playername}")
        builder.adjust(1)
        
        await message.answer(
            "🔐 <b>Выберите аккаунт:</b>",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )

    @dp.callback_query(F.data.startswith("login:"))
    async def handler_login_callback(callback: CallbackQuery):
        try:
            _, code, selected_playername = callback.data.split(":")
        except ValueError:
            return

        if code not in login_attempts:
            await callback.message.edit_text("⚠️ Сессия истекла.")
            return

        tg_id = callback.from_user.id

        with database.SessionLocal() as db:
            user = db.query(models.AuthTGUser).filter(
                models.AuthTGUser.chatid == tg_id,
                models.AuthTGUser.playername == selected_playername
            ).first()

        if not user:
            await callback.answer("⛔ Ошибка доступа!", show_alert=True)
            return


        login_attempts[code]["status"] = "ready"
        login_attempts[code]["playername"] = user.playername

        await callback.message.edit_text(f"✅ Успешный вход как <b>{user.playername}</b>!", parse_mode="HTML")
        await callback.answer()

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)
