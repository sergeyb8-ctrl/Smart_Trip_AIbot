import json
from datetime import datetime, timezone
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import SimpleEventIsolation
from aiogram.types import CallbackQuery, Chat, Message, Update, User
import pytest
from smarttrip.database import SQLiteStorage
from smarttrip.models import Draft, empty_draft
from smarttrip.settings import Settings
from smarttrip.telegram import create_router, Form, MANUAL, AI, HISTORY, EDIT
from smarttrip.ai import AIUnavailable
from test_ai import VALID

BOT_ID=123456
OWNER=1136439707

class Session(BaseSession):
    def __init__(self):
        super().__init__()
        self.sent=[]
        self.edited=[]
    async def close(self):pass
    async def make_request(self,bot,method,timeout=None):
        name=method.__api_method__
        if name=="getMe":
            return User(id=BOT_ID,is_bot=True,first_name="SmartTrip",username="Itpi2611SergeyandArtur_bot")
        if name=="sendMessage":
            self.sent.append(method)
            return Message(message_id=len(self.sent),date=datetime.now(timezone.utc),chat=Chat(id=int(method.chat_id),type="private"),text=method.text)
        if name=="editMessageReplyMarkup":
            self.edited.append(method)
            return Message(message_id=method.message_id,date=datetime.now(timezone.utc),chat=Chat(id=int(method.chat_id),type="private"))
        if name=="answerCallbackQuery":return True
        raise AssertionError(name)
    async def stream_content(self,*args,**kwargs):
        if False:yield b""

class Parser:
    def __init__(self,value=VALID,error=False):
        self.value=value; self.error=error; self.calls=0
    async def parse(self,text,previous=None):
        self.calls+=1
        if self.error:raise AIUnavailable("Временно недоступно. Заполните параметры кнопками.")
        return Draft.model_validate(self.value),"Groq"

class Harness:
    def __init__(self,db,parser=None,keys=False):
        self.db=db
        self.session=Session()
        self.bot=Bot("123456:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",session=self.session)
        self.storage=SQLiteStorage(db)
        self.dp=Dispatcher(storage=self.storage,events_isolation=SimpleEventIsolation())
        self.parser=parser or Parser()
        self.dp.include_router(create_router(db,self.parser,Settings(bot_token="fake",groq_key="fake" if keys else "")))
        self.n=0
    async def data(self,user=OWNER):
        return await self.storage.get_data(StorageKey(bot_id=BOT_ID,chat_id=user,user_id=user))
    async def state(self,user=OWNER):
        return await self.storage.get_state(StorageKey(bot_id=BOT_ID,chat_id=user,user_id=user))
    async def send(self,text,user=OWNER):
        self.n+=1
        message=Message(message_id=self.n,date=datetime.now(timezone.utc),chat=Chat(id=user,type="private"),
                        from_user=User(id=user,is_bot=False,first_name="Tester"),text=text)
        await self.dp.feed_update(self.bot,Update(update_id=self.n,message=message))
    async def click(self,payload,user=OWNER):
        self.n+=1
        message=Message(message_id=1,date=datetime.now(timezone.utc),chat=Chat(id=user,type="private"),
                        from_user=User(id=BOT_ID,is_bot=True,first_name="SmartTrip"),text="Prompt")
        query=CallbackQuery(id=str(self.n),from_user=User(id=user,is_bot=False,first_name="Tester"),
                            chat_instance="test",message=message,data=payload)
        await self.dp.feed_update(self.bot,Update(update_id=self.n,callback_query=query))
    async def select(self,field,value):
        flow=(await self.data())["flow"]
        await self.click(f"s:{flow}:{field}:{value}")
    async def done(self,field):
        flow=(await self.data())["flow"]
        await self.click(f"done:{flow}:{field}")
    async def build(self):
        await self.click("build:"+(await self.data())["flow"])
    async def manual(self):
        await self.send(MANUAL)
        await self.select("destination","spb")
        await self.select("days","3")
        await self.send("10 000")
        await self.select("interests","architecture")
        await self.done("interests")
        await self.select("exclude","museums")
        await self.done("exclude")
        await self.select("pace","calm")
        await self.select("start_time","10:00")
    async def close(self):
        await self.dp.storage.close()
        await self.bot.session.close()

async def test_manual_full_path_without_ai_keys(db):
    h=Harness(db)
    await h.send("/start")
    assert "Добро пожаловать" in h.session.sent[-1].text
    assert MANUAL in h.session.sent[-1].reply_markup.keyboard[0][0].text
    await h.manual()
    assert await h.state()==Form.confirm.state
    await h.build()
    trip=db.trip(OWNER)
    assert trip and trip["input_mode"]=="manual"
    assert len(trip["result"]["days"])==3
    assert h.parser.calls==0
    assert await h.state() is None
    await h.close()

async def test_ai_and_manual_have_same_engine_result(db):
    h=Harness(db,keys=True)
    await h.manual()
    await h.build()
    manual=db.trip(OWNER)["result"]
    await h.send(AI)
    await h.send("Питер три дня, десять тысяч, архитектура, без музеев, спокойно после десяти")
    assert await h.state()==Form.confirm.state
    await h.build()
    ai=db.trip(OWNER)
    assert ai["result"]==manual
    assert ai["input_mode"]=="ai:Groq"
    await h.close()

async def test_missing_ai_fields_trigger_same_manual_questions(db):
    h=Harness(db,Parser({**empty_draft(),"destination":"Питер","days":2}),keys=True)
    await h.send(AI);await h.send("Два дня в Питере")
    assert await h.state()==Form.budget.state
    assert (await h.data())["draft"]["destination"]=="Санкт-Петербург"
    await h.close()

async def test_ai_unavailable_and_unconfigured_offer_manual(db):
    for keys in (False,True):
        h=Harness(db,Parser(error=True),keys=keys)
        await h.send(AI)
        if keys: await h.send("Поездка")
        assert await h.state() is None
        assert MANUAL in h.session.sent[-1].reply_markup.keyboard[0][0].text
        await h.manual();await h.build()
        assert db.trip(OWNER)
        await h.close()

async def test_other_city_not_silently_replaced(db):
    h=Harness(db,Parser({**VALID,"destination":"Казань"}),keys=True)
    await h.send(AI);await h.send("Казань")
    assert "не будет подменён" in h.session.sent[-1].text
    assert db.trip(OWNER) is None
    await h.close()

async def test_edit_history_delete_and_ownership(db):
    h=Harness(db)
    await h.manual();await h.build()
    original=db.trip(OWNER)
    await h.send(EDIT)
    flow=(await h.data())["flow"]
    await h.click(f"edit:{flow}:budget")
    await h.send("5000")
    await h.build()
    assert db.trip(OWNER)["request"]["budget"]==5000
    assert db.trip(OWNER,original["id"])["request"]["budget"]==10000
    # Someone else cannot open a trip by guessing its numeric id.
    await h.click(f"history:{original['id']}",user=999)
    assert h.session.sent[-1].text=="Поездка недоступна."
    await h.send(HISTORY)
    assert "Последние поездки" in h.session.sent[-1].text
    await h.send("/delete")
    assert len(db.history(OWNER))==2
    flow=(await h.data())["flow"]
    await h.send("/cancel")
    await h.click(f"wipe:{flow}")
    assert len(db.history(OWNER))==2
    await h.send("/delete")
    flow=(await h.data())["flow"]
    await h.click(f"wipe:{flow}")
    assert not db.history(OWNER)
    await h.close()

async def test_stale_buttons_and_cancel_do_not_overwrite_new_draft(db):
    h=Harness(db)
    await h.send(MANUAL)
    old=(await h.data())["flow"]
    await h.send("/cancel");await h.send(MANUAL)
    current=await h.data()
    await h.click(f"s:{old}:destination:spb")
    assert await h.data()==current
    await h.close()

async def test_closed_admin_commands_for_both_and_denial(db):
    h=Harness(db)
    for user in (1136439707,1902707865):
        await h.send("/admin",user=user)
        assert "Доступ подтверждён" in h.session.sent[-1].text
    await h.send("/status",user=999)
    assert h.session.sent[-1].text=="Нет доступа."
    await h.close()

async def test_sqlite_fsm_survives_new_dispatcher(db):
    h=Harness(db)
    await h.send(MANUAL);await h.select("destination","spb");await h.select("days","2")
    data=await h.data()
    await h.close()
    h2=Harness(db)
    assert await h2.data()==data
    assert await h2.state()==Form.budget.state
    await h2.send("8000")
    assert await h2.state()==Form.interests.state
    await h2.close()

async def test_empty_interests_conflicts_and_low_budget_dont_save(db):
    h=Harness(db)
    await h.manual()
    data=await h.data()
    data["draft"]["budget"]=10
    await h.storage.set_data(StorageKey(bot_id=BOT_ID,chat_id=OWNER,user_id=OWNER),data)
    await h.build()
    assert "минимум" in h.session.sent[-1].text
    assert db.trip(OWNER) is None
    data["draft"]["budget"]=10000
    data["draft"]["exclude"]=["architecture"]
    await h.storage.set_data(StorageKey(bot_id=BOT_ID,chat_id=OWNER,user_id=OWNER),data)
    await h.build()
    assert "не должны совпадать" in h.session.sent[-1].text
    assert db.trip(OWNER) is None
    await h.close()

