"""Отдельная разработка NLP не требует Telegram-токена и запущенного бота."""
import argparse
import asyncio
from .settings import Settings
from .ai import AIParser, AIUnavailable

async def run(text):
    settings=Settings.load(require_bot=False)
    draft,provider=await AIParser(settings).parse(text)
    print("Провайдер:",provider)
    print(draft.model_dump_json(indent=2))

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("text")
    args=parser.parse_args()
    try:
        asyncio.run(run(args.text))
    except (AIUnavailable,ValueError):
        print("Не удалось разобрать запрос. Проверьте ключи и доступность API; секреты не выводятся.")
        raise SystemExit(1)

if __name__=="__main__":
    main()

