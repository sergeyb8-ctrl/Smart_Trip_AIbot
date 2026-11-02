"""Проверка маршрута без Telegram, токена и AI API."""
import argparse
import tempfile
from pathlib import Path
from .settings import ROOT
from .database import Database
from .models import TripRequest
from .engine import build_trip, PlanningError
from .telegram import route_messages

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--days",type=int,default=3)
    parser.add_argument("--budget",type=int,default=10000)
    args=parser.parse_args()
    with tempfile.TemporaryDirectory() as temp:
        db=Database(Path(temp)/"demo.sqlite3",ROOT/"data"/"places_spb.json")
        request=TripRequest(destination="Санкт-Петербург",days=args.days,budget=args.budget,
                            interests=["architecture","parks"],exclude=["museums"],pace="medium",start_time="10:00")
        try:
            result=build_trip(request,db.places())
        except PlanningError as error:
            print(error)
            raise SystemExit(1)
        print("\n\n".join(route_messages(result,0)))

if __name__=="__main__":
    main()

