"""Telegram-интерфейс aiogram: ручная анкета и AI сходятся в одном контракте."""
import json
import uuid
from datetime import datetime
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton,
                           InlineKeyboardMarkup, InlineKeyboardButton, LinkPreviewOptions)
from pydantic import ValidationError
from .models import FIELDS, LABELS, PACE_LABELS, TripRequest, empty_draft, normalize_city
from .engine import PlanningError, build_trip
from .ai import AIUnavailable

MANUAL = "🧭 Составить маршрут"
AI = "✨ Описать поездку ИИ"
HISTORY = "🗂 История поездок"
EDIT = "✏️ Изменить поездку"
HELP = "ℹ️ Помощь"
CANCEL = "Отмена"

WELCOME = (
    "Добро пожаловать в SmartTrip.\n\n"
    "Составьте персональный маршрут по Санкт-Петербургу на 1–5 дней. "
    "Сервис учтёт ваши интересы, бюджет и темп прогулок.\n\n"
    "Выберите способ: пошаговая анкета кнопками или описание поездки в свободной форме."
)
HELP_TEXT = (
    "SmartTrip — планировщик поездок по Санкт-Петербургу.\n\n"
    "«🧭 Составить маршрут» — заполнить анкету без ИИ.\n"
    "«✨ Описать поездку ИИ» — описать пожелания обычным сообщением.\n"
    "«✏️ Изменить поездку» — изменить параметры последнего маршрута.\n"
    "«🗂 История поездок» — открыть ранее составленные маршруты.\n\n"
    "Бюджет общий на одного человека: посещения, питание и местный транспорт. "
    "Дорога до города и проживание не включены. В расчёте заложено 800 ₽ в день "
    "на питание и местный транспорт. Все цены ориентировочные.\n\n"
    "/trip — анкета; /ai — описание; /history — история; /edit — изменение; "
    "/delete — очистить историю; /cancel — отмена; /menu — меню.\n"
    "Чтобы заменить маршрут описанием через ИИ, напишите новую поездку явно. "
    "Для изменения последней можно написать, например: «Оставь два дня и убери музеи»."
)

class Form(StatesGroup):
    ai_text = State()
    destination = State()
    days = State()
    budget = State()
    interests = State()
    exclude = State()
    pace = State()
    start_time = State()
    confirm = State()
    delete_history = State()

def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=MANUAL)], [KeyboardButton(text=AI)],
                  [KeyboardButton(text=HISTORY), KeyboardButton(text=EDIT)],
                  [KeyboardButton(text=HELP), KeyboardButton(text=CANCEL)]],
        resize_keyboard=True, is_persistent=True, input_field_placeholder="Выберите действие")

def inline(rows):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text,callback_data=callback) for text,callback in row] for row in rows])

def choice_keyboard(flow, field, draft):
    if field == "destination":
        values = [("Санкт-Петербург", "spb")]
    elif field == "days":
        values = [(str(x),str(x)) for x in range(1,6)]
    elif field == "budget":
        values = [(f"{x} ₽",str(x)) for x in (3000,5000,10000,20000)]
    elif field in ("interests","exclude"):
        selected = set(draft.get(field) or [])
        values = [(("✓ " if key in selected else "")+label,key) for key,label in LABELS.items()]
    elif field == "pace":
        values = [(label,key) for key,label in PACE_LABELS.items()]
    elif field == "start_time":
        values = [(time,time) for time in ("09:00","10:00","11:00","12:00")]
    else:
        raise ValueError(field)
    width = 3 if field=="days" else 2
    buttons = [(label,f"s:{flow}:{field}:{value}") for label,value in values]
    rows = [buttons[i:i+width] for i in range(0,len(buttons),width)]
    if field in ("interests","exclude"):
        rows.append([("Готово" if field=="interests" else "Готово / без исключений",f"done:{flow}:{field}")])
    return inline(rows)

def prompts(field):
    return {
        "destination":"Выберите город. В текущей версии доступен Санкт-Петербург.",
        "days":"Сколько дней продлится поездка? Выберите от 1 до 5.",
        "budget":"Укажите общий бюджет в рублях на одного человека. Нажмите кнопку или отправьте целое число. Минимум 800 ₽ на каждый день.",
        "interests":"Что вам интересно? Выберите несколько категорий и нажмите «Готово». Гастрономия представлена тематическими музеями; питание учитывается отдельным резервом.",
        "exclude":"Какие категории исключить? Выберите нужные или нажмите «Готово / без исключений».",
        "pace":"Выберите темп. Спокойный: до 3 мест и 5 км между ними в день; умеренный: до 4 и 8 км; активный: до 5 и 12 км.",
        "start_time":"Когда начинать каждый день? Нажмите кнопку или отправьте время от 07:00 до 16:59 в формате ЧЧ:ММ."
    }[field]

def summary(draft):
    def cats(key):
        return ", ".join(LABELS.get(x,x) for x in draft.get(key) or []) or "нет"
    return (
        f"Параметры поездки\n\nГород: {draft.get('destination')}\n"
        f"Дней: {draft.get('days')}\nОбщий бюджет: {draft.get('budget')} ₽\n"
        f"Интересы: {cats('interests')}\nИсключения: {cats('exclude')}\n"
        f"Темп: {PACE_LABELS.get(draft.get('pace'), 'не указан')}\n"
        f"Начало дня: {draft.get('start_time')}\n\n"
        "Посещения, питание и местный транспорт включены в оценку. "
        "Проживание и дорога до города не включены. Проверьте параметры перед построением."
    )

def review_keyboard(flow):
    labels={"days":"Дни","budget":"Бюджет","interests":"Интересы","exclude":"Исключения","pace":"Темп","start_time":"Начало дня"}
    rows = [[("Построить маршрут",f"build:{flow}")]]
    buttons=[(f"Изменить: {label}",f"edit:{flow}:{key}") for key,label in labels.items()]
    rows += [buttons[i:i+2] for i in range(0,len(buttons),2)]
    return inline(rows)

def route_messages(result, trip_id):
    messages = [
        f"Санкт-Петербург · поездка №{trip_id}\n"
        f"Дней: {len(result['days'])}\n"
        f"Оценочные расходы: {result['total']} ₽\n"
        f"Остаток бюджета: {result['remaining']} ₽\n\n"
        "Время и расходы ориентировочные. Проверьте часы работы и цены перед посещением."
    ]
    for day in result["days"]:
        lines=[f"День {day['day']}"]
        for visit in day["visits"]:
            if visit["break_before_minutes"]:
                lines.append(f"Перед следующим посещением: перерыв {visit['break_before_minutes']} мин на питание.")
            mode={"inside":"посещение","outdoor":"прогулка / внешний осмотр","market":"рынок"}[visit["visit_mode"]]
            lines.append(f"\n{visit['start']}–{visit['end']} — {visit['name']} ({mode})")
            lines.append(f"Посещение: ≈{visit['price']} ₽; переход: ≈{visit['walk_km']:.1f} км / {visit['travel_minutes']} мин")
            lines.append(visit["source_url"])
        lines.append(f"\nЗа день: ≈{day['total']} ₽, в том числе питание {day['food']} ₽ и транспорт {day['transport']} ₽.")
        lines.append(f"Пешком между местами: ≈{day['walk_km']:.1f} км. Путь от жилья и обратно не включён.")
        messages.append("\n".join(lines))
    messages.append("Что учесть\n\n"+"\n".join("• "+item for item in result["warnings"])+
                    "\n\nМеста и координаты: © OpenStreetMap contributors (ODbL). https://www.openstreetmap.org/copyright")
    return messages

async def send_route(message, result, trip_id):
    for text in route_messages(result, trip_id):
        await message.answer(text, reply_markup=main_keyboard(), link_preview_options=LinkPreviewOptions(is_disabled=True))

async def begin(message, state, mode="manual", draft=None):
    await state.clear()
    await state.set_data({"draft":draft or empty_draft(),"flow":uuid.uuid4().hex[:8],"mode":mode})
    await advance(message,state)

async def advance(message, state):
    data=await state.get_data()
    draft=data["draft"]
    for field in FIELDS:
        if draft.get(field) is None or (field=="interests" and not draft.get(field)):
            await state.set_state(getattr(Form,field))
            await message.answer(prompts(field),reply_markup=choice_keyboard(data["flow"],field,draft))
            return
    await state.set_state(Form.confirm)
    await message.answer(summary(draft),reply_markup=review_keyboard(data["flow"]))

def create_router(db, parser, settings):
    router=Router(name="smarttrip")

    async def command(message: Message, state: FSMContext):
        if message.chat.type!="private" or message.from_user is None:
            return
        text=message.text or ""
        aliases={MANUAL:"/trip",AI:"/ai",HISTORY:"/history",EDIT:"/edit",HELP:"/help",CANCEL:"/cancel"}
        cmd=aliases.get(text,text.split(maxsplit=1)[0].split("@")[0].lower() if text else "")
        uid=message.from_user.id
        if cmd in {"/start","/menu","/cancel"}:
            await state.clear()
            await message.answer(WELCOME if cmd=="/start" else
                "Действие отменено. Сохранённые поездки не изменены." if cmd=="/cancel" else "Главное меню.",
                reply_markup=main_keyboard())
        elif cmd=="/trip":
            await begin(message,state)
        elif cmd=="/ai":
            await state.clear()
            if not (settings.groq_key or settings.gemini_key):
                await message.answer("Ввод через ИИ сейчас недоступен. Выберите «🧭 Составить маршрут» — анкета и алгоритм работают без ИИ.",reply_markup=main_keyboard())
                return
            await state.set_state(Form.ai_text)
            await message.answer(
                "Опишите поездку одним сообщением: город, 1–5 дней, общий бюджет, интересы, "
                "исключения, темп и время начала дня. Например: «Петербург на 3 дня, "
                "10 000 рублей, архитектура и прогулки, без музеев, спокойный темп, после 10:00».\n\n"
                "Также можно попросить изменить последнюю поездку. Текст будет отправлен AI-сервису для разбора.",
                reply_markup=main_keyboard())
        elif cmd in {"/help","/about"}:
            await message.answer(HELP_TEXT,reply_markup=main_keyboard())
        elif cmd=="/myid":
            await message.answer(f"Ваш Telegram ID: {uid}")
        elif cmd in {"/admin","/status"}:
            if uid not in settings.admin_ids:
                await message.answer("Нет доступа.")
                return
            await message.answer(
                ("Владелец проекта" if uid==settings.owner_id else "Администратор проекта")+
                ". Доступ подтверждён.\n"+
                f"В каталоге: {len(db.places())} мест. Анкета, история и алгоритм доступны.\n"+
                f"Groq: {'настроен' if settings.groq_key else 'ключ не задан'}; Gemini: {'настроен' if settings.gemini_key else 'ключ не задан'}.\n"
                "Наличие ключа не подтверждает доступность API.")
        elif cmd=="/history":
            await state.clear()
            rows=db.history(uid)
            if not rows:
                await message.answer("История пуста. Составьте первую поездку.",reply_markup=main_keyboard())
                return
            buttons=[]
            for row in rows:
                req=json.loads(row["request"])
                date=datetime.fromisoformat(row["created_at"]).strftime("%d.%m.%Y")
                buttons.append([(f"№{row['id']} · {date} · {req['days']} дн. · {req['budget']} ₽",f"history:{row['id']}")])
            await message.answer("Последние поездки. Выберите маршрут:",reply_markup=inline(buttons))
        elif cmd=="/edit":
            old=db.trip(uid)
            if not old:
                await message.answer("Сначала составьте поездку.",reply_markup=main_keyboard())
                return
            await begin(message,state,"manual",old["request"])
        elif cmd=="/delete":
            await state.clear()
            flow=uuid.uuid4().hex[:8]
            await state.set_data({"flow":flow})
            await state.set_state(Form.delete_history)
            await message.answer("Удалить всю вашу историю поездок? Для отмены нажмите «Отмена».",
                                 reply_markup=inline([[("Удалить мою историю",f"wipe:{flow}")]]))

    router.message.register(command,CommandStart())
    router.message.register(command,Command("menu","cancel","trip","ai","history","edit","delete","help","about","myid","admin","status"))
    router.message.register(command,F.text.in_({MANUAL,AI,HISTORY,EDIT,HELP,CANCEL}))

    @router.callback_query()
    async def callback(query: CallbackQuery, state: FSMContext):
        if not isinstance(query.message,Message) or query.message.chat.type!="private":
            await query.answer()
            return
        raw=query.data or ""
        uid=query.from_user.id
        if raw.startswith("history:"):
            try:
                trip=db.trip(uid,int(raw.split(":")[1]))
            except (ValueError,IndexError):
                trip=None
            await query.answer()
            if trip is None:
                await query.message.answer("Поездка недоступна.")
            else:
                await state.clear()
                await send_route(query.message,trip["result"],trip["id"])
            return
        parts=raw.split(":",3)
        data=await state.get_data()
        if len(parts)<2 or parts[1]!=data.get("flow"):
            await query.answer("Эта кнопка устарела. Откройте меню.",show_alert=True)
            return
        action=parts[0]
        current=await state.get_state()
        if action=="wipe" and current==Form.delete_history.state:
            db.clear_history(uid)
            await state.clear()
            await query.answer()
            await query.message.answer("Ваша история удалена.",reply_markup=main_keyboard())
            return
        if action=="build" and current==Form.confirm.state:
            await query.answer("Составляем маршрут")
            try:
                request=TripRequest.model_validate(data["draft"])
                result=build_trip(request,db.places())
            except (PlanningError,ValidationError) as error:
                text=str(error) if isinstance(error,PlanningError) else "Проверьте параметры: интересы и исключения не должны совпадать."
                await query.message.answer(text,reply_markup=review_keyboard(data["flow"]))
                return
            trip_id=db.save_trip(uid,request,result,data.get("mode","manual"))
            await state.clear()
            await send_route(query.message,result,trip_id)
            return
        if action=="edit" and current==Form.confirm.state and len(parts)==3 and parts[2] in FIELDS:
            field=parts[2]
            draft=data["draft"]
            draft[field]=None
            await state.update_data(draft=draft)
            await query.answer()
            await advance(query.message,state)
            return
        if action not in {"s","done"} or len(parts)<3 or parts[2] not in FIELDS:
            await query.answer("Действие недоступно")
            return
        field=parts[2]
        if current!=getattr(Form,field).state:
            await query.answer("Этот этап уже завершён.",show_alert=True)
            return
        draft=data["draft"]
        if action=="done":
            if field not in {"interests","exclude"}:
                await query.answer()
                return
            if field=="interests" and not draft.get(field):
                await query.answer("Выберите хотя бы один интерес.",show_alert=True)
                return
            draft[field]=draft.get(field) or []
        elif len(parts)==4:
            value=parts[3]
            if field in {"interests","exclude"}:
                if value not in LABELS:
                    await query.answer()
                    return
                selected=list(draft.get(field) or [])
                selected.remove(value) if value in selected else selected.append(value)
                draft[field]=selected
                await state.update_data(draft=draft)
                await query.answer()
                await query.message.edit_reply_markup(reply_markup=choice_keyboard(data["flow"],field,draft))
                return
            allowed={"destination":{"spb"},"days":set("12345"),"budget":{"3000","5000","10000","20000"},
                     "pace":set(PACE_LABELS),"start_time":{"09:00","10:00","11:00","12:00"}}
            if value not in allowed.get(field,set()):
                await query.answer()
                return
            draft[field]="Санкт-Петербург" if field=="destination" else int(value) if field in {"days","budget"} else value
        else:
            await query.answer()
            return
        await state.update_data(draft=draft)
        await query.answer()
        await advance(query.message,state)

    @router.message()
    async def text(message: Message, state: FSMContext):
        if message.chat.type!="private" or message.from_user is None:
            return
        value=(message.text or "").strip()
        current=await state.get_state()
        if value.startswith("/"):
            await message.answer("Неизвестная команда. Используйте /help.")
            return
        if current==Form.ai_text.state:
            if not value or len(value)>4000:
                await message.answer("Отправьте текст длиной от 1 до 4000 символов.")
                return
            await message.answer("Разбираем пожелания…")
            previous=db.trip(message.from_user.id)
            try:
                parsed,provider=await parser.parse(value,previous["request"] if previous else None)
            except AIUnavailable as error:
                await state.clear()
                await message.answer(str(error),reply_markup=main_keyboard())
                return
            draft=parsed.model_dump()
            draft["destination"]=normalize_city(draft["destination"])
            if draft["destination"] not in {None,"Санкт-Петербург"}:
                await state.clear()
                await message.answer("В этой версии доступны поездки только по Санкт-Петербургу. Для другого города маршрут не будет подменён. Выберите анкету для Петербурга.",reply_markup=main_keyboard())
                return
            await message.answer("Описание разобрано. Уточните недостающие данные и проверьте параметры.")
            await begin(message,state,"ai:"+provider,draft)
            return
        field=next((name for name in FIELDS if current==getattr(Form,name).state),None)
        if field in {"budget","days","destination","start_time"}:
            data=await state.get_data()
            draft=data["draft"]
            try:
                if field=="destination":
                    parsed=normalize_city(value)
                    if parsed!="Санкт-Петербург": raise ValueError()
                elif field in {"days","budget"}:
                    normalized=value.replace(" ","").replace("\u00a0","")
                    if not normalized.isascii() or not normalized.isdigit(): raise ValueError()
                    parsed=int(normalized)
                    if field=="days" and not 1<=parsed<=5: raise ValueError()
                    if field=="budget" and not 0<=parsed<=1_000_000: raise ValueError()
                else:
                    from .models import Draft
                    parsed=Draft.model_validate({**empty_draft(),"start_time":value}).start_time
                draft[field]=parsed
            except (ValueError,ValidationError):
                await message.answer(prompts(field))
                return
            await state.update_data(draft=draft)
            await advance(message,state)
        elif field:
            await message.answer("Выберите варианты кнопками под вопросом. Для выхода используйте /cancel.")
        elif current==Form.confirm.state:
            await message.answer("Проверьте параметры и нажмите «Построить маршрут» или выберите изменение.")
        else:
            await message.answer("Выберите способ составления маршрута в меню.",reply_markup=main_keyboard())

    return router

