from dataclasses import dataclass, field
from pathlib import Path
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent

@dataclass(frozen=True)
class Settings:
    bot_token: str = field(repr=False)
    groq_key: str = field(default="", repr=False)
    gemini_key: str = field(default="", repr=False)
    groq_model: str = "openai/gpt-oss-120b"
    gemini_model: str = "gemini-3.8-flash"
    bot_username: str = "Itpi2611SergeyandArtur_bot"
    owner_id: int = 1136439707
    admin_ids: frozenset[int] = frozenset({1136439707, 1902707865})
    database: Path = ROOT / "runtime" / "smarttrip.sqlite3"

    @classmethod
    def load(cls, require_bot=True):
        path = ROOT / ".env"
        if not path.is_file():
            raise ValueError("Создайте .env из .env.example и заполните BOT_TOKEN.")
        values = dotenv_values(path)
        token = (values.get("BOT_TOKEN") or "").strip()
        if require_bot and (not token or ":" not in token):
            raise ValueError("Укажите настоящий BOT_TOKEN в .env.")
        owner = int(values.get("OWNER_ID") or "1136439707")
        admins = frozenset({owner} | {int(x.strip()) for x in (values.get("ADMIN_IDS") or "1136439707,1902707865").split(",") if x.strip()})
        return cls(bot_token=token, groq_key=values.get("GROQ_API_KEY") or "",
                   gemini_key=values.get("GEMINI_API_KEY") or "",
                   groq_model=values.get("GROQ_MODEL") or "openai/gpt-oss-120b",
                   gemini_model=values.get("GEMINI_MODEL") or "gemini-3.8-flash",
                   bot_username=values.get("BOT_USERNAME") or "Itpi2611SergeyandArtur_bot",
                   owner_id=owner, admin_ids=admins)

