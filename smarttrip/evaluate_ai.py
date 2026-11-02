"""Опциональная оценка живого NLP на размеченных примерах; требует .env."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from .ai import AIParser, AIUnavailable
from .models import FIELDS
from .settings import Settings, ROOT

def equal(field, actual, expected):
    if field in {"interests","exclude"} and actual is not None and expected is not None:
        return set(actual)==set(expected)
    return actual==expected

async def run(limit):
    settings=Settings.load(require_bot=False)
    cases=json.loads((ROOT/"data"/"ai_examples.json").read_text(encoding="utf-8"))[:limit]
    parser=AIParser(settings)
    records=[]
    for case in cases:
        try:
            draft,provider=await parser.parse(case["text"],case.get("previous"))
            actual=draft.model_dump()
            scores={field:equal(field,actual[field],case["expected"][field]) for field in FIELDS}
            records.append({"id":case["id"],"provider":provider,"actual":actual,"correct":scores,"error":None})
            print(case["id"],"—",sum(scores.values()),"/",len(FIELDS))
        except AIUnavailable:
            records.append({"id":case["id"],"provider":None,"actual":None,"correct":dict.fromkeys(FIELDS,False),"error":"unavailable"})
            print(case["id"],"— API недоступен")
    total=len(records)*len(FIELDS)
    report={"created_at":datetime.now(timezone.utc).isoformat(),"groq_model":settings.groq_model,
            "gemini_model":settings.gemini_model,"case_count":len(records),
            "field_accuracy":sum(sum(row["correct"].values()) for row in records)/total,
            "fully_correct":sum(all(row["correct"].values()) for row in records),"records":records,
            "note":"Малый стартовый набор, не статистически устойчивая оценка качества."}
    path=ROOT/"runtime"/"ai_evaluation.json"
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print("Отчёт сохранён в runtime/ai_evaluation.json. Не публикуйте реальные пользовательские запросы.")

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--limit",type=int,default=3)
    args=parser.parse_args()
    if not 1<=args.limit<=12:
        parser.error("--limit: от 1 до 12")
    try:
        asyncio.run(run(args.limit))
    except ValueError:
        print("Проверьте .env; Telegram-токен для этой команды не нужен.")
        raise SystemExit(1)

if __name__=="__main__":
    main()

