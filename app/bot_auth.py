import asyncio
from typing import Dict
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import Message

login_attempts: Dict[str, dict] = {}

async def start_bot_polling(token: str):
    """
    Запускает бесконечный цикл опроса серверов Telegram (Long Polling).
    """
    bot = Bot(token=token)
    dp = Dispatcher()

    @dp.message(CommandStart(deep_link=True))
    async def handler_start(message: Message, command: CommandObject):
        code = command.args
        
        if code and code in login_attempts:
            
            login_attempts[code] = {
                "status": "ready",
                "tg_id": message.from_user.id,
                "username": message.from_user.username
            }
            
            await message.answer(
                "✅ <b>Вход подтвержден!</b>\n\n"
                "Вы успешно авторизовались. Можете возвращаться в браузер.",
                parse_mode="HTML"
            )
        else:
            await message.answer("⚠️ Ссылка устарела или неверна. Попробуйте нажать кнопку «Войти» на сайте еще раз.")

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)