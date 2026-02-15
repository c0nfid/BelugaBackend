import asyncio
import time
import uuid
import os
from typing import Dict
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from . import database, models, auth_utils

CODE_TTL = 300

# Хранилище кодов входа
login_attempts: Dict[str, dict] = {}

# Хранилище подтверждений
pending_confirmations: Dict[str, dict] = {}

async def cleanup_task():
    while True:
        try:
            now = time.time()
            to_delete_login = [code for code, data in login_attempts.items() if now - data["created_at"] > CODE_TTL]
            for code in to_delete_login: del login_attempts[code]
            
            to_delete_confirm = [rid for rid, data in pending_confirmations.items() if now - data["created_at"] > CODE_TTL]
            for rid in to_delete_confirm: del pending_confirmations[rid]
        except Exception as e:
            print(f"Error in cleanup task: {e}") 
        await asyncio.sleep(60)

async def send_confirmation_request(bot: Bot, chat_id: int, action_type: str, data: dict = None) -> str:
    request_id = str(uuid.uuid4())
    
    pending_confirmations[request_id] = {
        "type": action_type,
        "chat_id": chat_id,
        "data": data or {},
        "status": "pending",
        "created_at": time.time()
    }
    
    if action_type == "unlink":
        text = "⚠️ <b>Внимание!</b>\nПоступил запрос на отвязку Telegram.\nПодтвердите действие."
        btn_text = "confirm_unlink"
    elif action_type == "change_password":
        text = "🔐 <b>Безопасность</b>\nПоступил запрос на смену пароля.\nПодтвердите смену."
        btn_text = "confirm_pass"
    else:
        text = "Подтвердите действие"
        btn_text = "confirm_generic"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"act:{request_id}:{btn_text}")]
    ])
    
    try:
        await bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="HTML")
        return request_id
    except Exception as e:
        print(f"Error sending msg: {e}")
        return None

async def register_handlers(dp: Dispatcher):
    
    @dp.callback_query(F.data.startswith("act:"))
    async def action_confirmation_handler(callback: CallbackQuery):
        try:
            _, request_id, action_code = callback.data.split(":")
        except ValueError:
            return

        if request_id not in pending_confirmations:
            await callback.message.edit_text("⏳ Срок действия запроса истек.")
            return

        req = pending_confirmations[request_id]
        
        # Используем контекстный менеджер для надежности
        with database.SessionLocal() as db:
            user = db.query(models.AuthTGUser).filter(models.AuthTGUser.chatid == req["chat_id"]).first()
            
            if not user:
                await callback.answer("Ошибка: Пользователь не найден")
                return

            msg = "Действие подтверждено."

            if action_code == "confirm_unlink":
                user.activeTG = False
                user.chatid = None
                user.username = None
                user.firstname = None
                user.twofactor = 0
                db.add(user) # Явное добавление
                db.commit()
                msg = "❌ Telegram успешно отвязан."
            
            elif action_code == "confirm_pass":
                new_pass = req["data"].get("new_password")
                if new_pass:
                    # Хешируем и сохраняем
                    hashed_password = auth_utils.get_password_hash(new_pass)
                    user.password = hashed_password
                    db.add(user) # Явное добавление для фиксации изменений
                    db.commit()
                    print(f"Password changed via Telegram for user {user.playername}")
                    msg = "🔑 Пароль успешно изменен."
                else:
                    msg = "❌ Ошибка: данные пароля не найдены."

        pending_confirmations[request_id]["status"] = "approved"
        await callback.message.edit_text(msg)
        await callback.answer("Готово!")

async def start_bot_polling(token: str):
    bot = Bot(token=token)
    dp = Dispatcher()
    await register_handlers(dp)

    @dp.message(CommandStart(deep_link=True))
    async def handler_start(message: Message, command: CommandObject):
        code = command.args
        if not code or code not in login_attempts:
            await message.answer("⚠️ Ссылка устарела. Начните вход на сайте заново.")
            return

        if time.time() - login_attempts[code]["created_at"] > CODE_TTL:
            del login_attempts[code]
            await message.answer("⚠️ Время действия ссылки истекло.")
            return

        tg_id = message.from_user.id
        with database.SessionLocal() as db:
            users = db.query(models.AuthTGUser).filter(models.AuthTGUser.chatid == tg_id).all()

        if not users:
            await message.answer("⛔ Нет привязанных аккаунтов. Используйте @BelugaVerification_bot")
            return

        if len(users) == 1:
            login_attempts[code]["status"] = "ready"
            login_attempts[code]["playername"] = users[0].playername
            await message.answer(f"✅ Вход выполнен: <b>{users[0].playername}</b>", parse_mode="HTML")
            return

        builder = InlineKeyboardBuilder()
        for user in users:
            builder.button(text=f"👤 {user.playername}", callback_data=f"login:{code}:{user.playername}")
        builder.adjust(1)
        await message.answer("🔐 <b>Выберите аккаунт:</b>", reply_markup=builder.as_markup(), parse_mode="HTML")

    @dp.callback_query(F.data.startswith("login:"))
    async def handler_login_callback(callback: CallbackQuery):
        try: _, code, selected_playername = callback.data.split(":")
        except: return

        if code not in login_attempts:
            await callback.message.edit_text("⚠️ Сессия истекла.")
            return

        tg_id = callback.from_user.id
        with database.SessionLocal() as db:
            user = db.query(models.AuthTGUser).filter(models.AuthTGUser.chatid == tg_id, models.AuthTGUser.playername == selected_playername).first()

        if not user:
            await callback.answer("⛔ Ошибка доступа!", show_alert=True)
            return

        login_attempts[code]["status"] = "ready"
        login_attempts[code]["playername"] = user.playername
        await callback.message.edit_text(f"✅ Успешный вход: <b>{user.playername}</b>", parse_mode="HTML")
        await callback.answer()

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)