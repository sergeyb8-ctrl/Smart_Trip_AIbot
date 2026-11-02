import json
import httpx
import pytest
from smarttrip.ai import AIParser, AIUnavailable
from smarttrip.settings import Settings
from smarttrip.models import empty_draft

VALID={"destination":"Санкт-Петербург","days":3,"budget":10000,"interests":["architecture"],
       "exclude":["museums"],"pace":"calm","start_time":"10:00"}

def settings(**changes):
    return Settings(bot_token="123:test",groq_key=changes.get("groq_key","fake-groq"),
                    gemini_key=changes.get("gemini_key","fake-gemini"))

def groq(data=VALID):
    return {"choices":[{"message":{"content":json.dumps(data)}}]}

def gemini(data=VALID):
    return {"candidates":[{"content":{"parts":[{"text":json.dumps(data)}]}}]}

async def test_primary_success_does_not_call_fallback():
    seen=[]
    def responder(request):
        seen.append(request)
        assert request.headers["Authorization"]=="Bearer fake-groq"
        payload=json.loads(request.content)
        assert payload["response_format"]["json_schema"]["strict"] is True
        return httpx.Response(200,json=groq())
    async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as client:
        draft,provider=await AIParser(settings(),client).parse("Петербург")
    assert provider=="Groq" and draft.days==3 and len(seen)==1

@pytest.mark.parametrize("failure",["rate","invalid","timeout","empty"])
async def test_gemini_fallback_for_http_timeout_and_schema(failure):
    seen=[]
    def responder(request):
        seen.append(request.url.host)
        if request.url.host=="api.groq.com":
            if failure=="rate":return httpx.Response(429,json={"error":{}})
            if failure=="invalid":return httpx.Response(200,json=groq({**VALID,"budget":"bad"}))
            if failure=="empty":return httpx.Response(200,json={"choices":[]})
            raise httpx.ReadTimeout("mock",request=request)
        assert "key" not in request.url.params
        assert request.headers["x-goog-api-key"]=="fake-gemini"
        payload=json.loads(request.content)
        assert payload["generationConfig"]["responseFormat"]["text"]["mimeType"]=="APPLICATION_JSON"
        return httpx.Response(200,json=gemini())
    async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as client:
        draft,provider=await AIParser(settings(),client).parse("Петербург")
    assert provider=="Gemini" and draft.budget==10000
    assert seen==["api.groq.com","generativelanguage.googleapis.com"]

async def test_both_services_unavailable():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(503))) as client:
        with pytest.raises(AIUnavailable,match="кнопками"):
            await AIParser(settings(),client).parse("Запрос")

async def test_no_keys_does_not_contact_network():
    def fail(request):raise AssertionError("network must not be called")
    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
        with pytest.raises(AIUnavailable):
            await AIParser(settings(groq_key="",gemini_key=""),client).parse("Запрос")

async def test_missing_data_remains_null():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=groq(empty_draft())))) as client:
        draft,_=await AIParser(settings(),client).parse("Хочу погулять")
    assert all(value is None for value in draft.model_dump().values())

async def test_previous_parameters_are_passed_as_data():
    def responder(request):
        payload=json.loads(request.content)
        user=json.loads(payload["messages"][1]["content"])
        assert user["previous_trip"]==VALID
        assert user["user_text"]=="Убери музеи"
        return httpx.Response(200,json=groq())
    async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as client:
        await AIParser(settings(),client).parse("Убери музеи",VALID)

def test_settings_repr_does_not_expose_keys():
    value=repr(settings())
    assert "fake-groq" not in value and "fake-gemini" not in value and "123:test" not in value

