import json
import pytest
from smarttrip.settings import Settings, ROOT
from smarttrip import settings as config
from smarttrip.models import Draft
from smarttrip.evaluate_ai import equal

def test_secrets_loaded_from_dotenv_only(tmp_path,monkeypatch):
    monkeypatch.setattr(config,"ROOT",tmp_path)
    (tmp_path/".env").write_text("BOT_TOKEN=123:fake-local\nGROQ_API_KEY=local-only\nADMIN_IDS=1136439707,1902707865\n")
    monkeypatch.setenv("GROQ_API_KEY","outside-value")
    result=Settings.load()
    assert result.groq_key=="local-only"
    assert result.admin_ids=={1136439707,1902707865}
    assert "local-only" not in repr(result)

def test_ai_developer_does_not_need_telegram_token(tmp_path,monkeypatch):
    monkeypatch.setattr(config,"ROOT",tmp_path)
    (tmp_path/".env").write_text("GROQ_API_KEY=local-only\n")
    assert Settings.load(require_bot=False).bot_token==""
    with pytest.raises(ValueError):
        Settings.load()

def test_missing_env_is_explained(tmp_path,monkeypatch):
    monkeypatch.setattr(config,"ROOT",tmp_path)
    with pytest.raises(ValueError,match=".env"):
        Settings.load()

def test_labelled_examples_match_contract():
    data=json.loads((ROOT/"data"/"ai_examples.json").read_text())
    assert len(data)==12
    for item in data:
        Draft.model_validate(item["expected"])

def test_evaluation_compares_categories_without_order():
    assert equal("interests",["parks","art"],["art","parks"])
    assert not equal("interests",[],None)

