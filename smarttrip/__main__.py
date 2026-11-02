import asyncio
import fcntl
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import SimpleEventIsolation
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeChat, ErrorEvent
from aiogram.exceptions import TelegramAPIError
from .settings import Settings, ROOT
from .database import Database, SQLiteStorage
from .ai import AIParser
from .telegram import create_router

PUBLIC = [
    ("start","Начать работу"), ("trip","Маршрут без ИИ"), ("ai","Описать поездку ИИ"),
    ("history","История поездок"), ("edit","Изменить последнюю поездку"),
    ("delete","Удалить мою историю"), ("cancel","Отменить действие"), ("menu","Главное меню"),
    ("help","Помощь"), ("about","О сервисе"), ("myid","Мой Telegram ID")
]

async def run():
    settings=Settings.load()
    settings.database.parent.mkdir(parents=True,exist_ok=True)
    # Предотвращает второй процесс с той же папкой runtime на macOS/Linux.
    with (settings.database.parent/"bot.lock").open("w") as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            print("В этой папке бот уже запущен. Остановите предыдущую копию.")
            return
        db=Database(settings.database,ROOT/"data"/"places_spb.json")
        bot=Bot(settings.bot_token)
        try:
            account=await bot.get_me()
            if (account.username or "").lower()!=settings.bot_username.lower():
                print("BOT_TOKEN относится к другому боту. Проверьте BOT_USERNAME и BOT_TOKEN в .env.")
                return
            if (await bot.get_webhook_info()).url:
                print("У бота настроен webhook. Остановите прежний способ запуска; настройки автоматически не изменены.")
                return
            public=[BotCommand(command=c,description=d) for c,d in PUBLIC]
            try:
                await bot.set_my_commands(public,scope=BotCommandScopeAllPrivateChats())
                for uid in settings.admin_ids:
                    try:
                        await bot.set_my_commands(public+[BotCommand(command="admin",description="Проверить права"),BotCommand(command="status",description="Состояние сервиса")],
                                                  scope=BotCommandScopeChat(chat_id=uid))
                    except TelegramAPIError:
                        pass
            except TelegramAPIError:
                print("Меню команд не обновлено. Команды можно вводить вручную.")
            dp=Dispatcher(storage=SQLiteStorage(db),events_isolation=SimpleEventIsolation())
            dp.include_router(create_router(db,AIParser(settings),settings))

            @dp.errors()
            async def error_handler(event: ErrorEvent):
                # Не выводим сообщения, HTTP-заголовки, .env или объект исключения.
                logging.error("Ошибка обработки: %s",type(event.exception).__name__)
                message=event.update.message
                if message and message.chat.type=="private":
                    try:
                        await message.answer("Не удалось завершить действие. Попробуйте снова или откройте /menu.")
                    except TelegramAPIError:
                        pass
                return True

            print(f"SmartTrip @{settings.bot_username}: {len(db.places())} мест. Остановка: Ctrl+C.")
            await dp.start_polling(bot,allowed_updates=dp.resolve_used_update_types())
        finally:
            await bot.session.close()

def main():
    logging.basicConfig(level=logging.WARNING,format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.CRITICAL)
    logging.getLogger("httpcore").setLevel(logging.CRITICAL)
    try:
        asyncio.run(run())
    except ValueError:
        print("Проверьте .env: токен, числовые ID и названия моделей. Ключи не выводятся.")
        raise SystemExit(1)
    except TelegramAPIError:
        print("Не удалось подключиться к Telegram. Проверьте токен, интернет и отсутствие другой запущенной копии.")
        raise SystemExit(1)
    except (KeyboardInterrupt,SystemExit):
        pass

if __name__=="__main__":
    main()

