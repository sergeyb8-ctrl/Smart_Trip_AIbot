"""Общий детерминированный алгоритм. Не обращается к LLM или сети."""
from math import asin, cos, radians, sin, sqrt, ceil
from .models import TripRequest

FOOD_PER_DAY = 600
TRANSPORT_PER_DAY = 200
PACE = {"calm": (3, 5.0, 3.5), "medium": (4, 8.0, 4.0), "active": (5, 12.0, 4.5)}

class PlanningError(ValueError):
    pass

def distance_km(a, b):
    lat1, lat2 = radians(a.latitude), radians(b.latitude)
    dlat, dlon = lat2-lat1, radians(b.longitude-a.longitude)
    return 6371 * 2 * asin(min(1, sqrt(sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlon/2)**2)))

def walk_km(a,b):
    # Оценка, а не маршрутизация по уличному графу.
    return distance_km(a,b) * 1.3

def rank_places(request, places):
    excluded, interests = set(request.exclude), set(request.interests)
    return sorted(
        [(p, 10*len(interests & set(p.tags)) + (2 if p.price == 0 else 0)) for p in places
         if not (excluded & set(p.tags)) and interests & set(p.tags)],
        key=lambda item: (-item[1], item[0].price, item[0].id))

def clock(minutes):
    return f"{minutes//60:02d}:{minutes%60:02d}"

def build_trip(request: TripRequest, places):
    request = TripRequest.model_validate(request)
    reserve = request.days * (FOOD_PER_DAY + TRANSPORT_PER_DAY)
    if request.budget < reserve:
        raise PlanningError(
            f"Для выбранного числа дней заложено минимум {reserve} ₽ на питание и местный транспорт "
            f"({FOOD_PER_DAY + TRANSPORT_PER_DAY} ₽ в день). Увеличьте бюджет или сократите поездку.")
    ranked = rank_places(request, places)
    if len(ranked) < request.days:
        raise PlanningError("В каталоге недостаточно подходящих мест на каждый день. Измените интересы, исключения или число дней.")
    max_points, walk_limit, speed = PACE[request.pace]
    remaining = request.budget - reserve
    used = set()
    days = []
    warnings = [
        "Стоимость посещений, питания и транспорта — учебная оценка, не актуальный прайс. Дорога до города и проживание не включены.",
        "Расстояния и время пешком оценены по координатам с коэффициентом 1,3; мосты, проходы и закрытия не проверяются.",
        "Время посещений рекомендательное. Перед поездкой проверьте часы работы и билеты по источникам; календарные даты в этой версии не учитываются.",
        "Питание и местный транспорт включены в расходы резервом, но бронирование и маршруты транспорта не выполняются.",
    ]
    for day_no in range(1, request.days+1):
        allowance = remaining // (request.days-day_no+1)
        spent, walked, visits, current = 0, 0.0, [], None
        h,m = map(int, request.start_time.split(":"))
        now = h*60+m
        lunch_added = False
        while len(visits) < max_points:
            candidates = []
            for place, score in ranked:
                if place.id in used or spent+place.price > allowance:
                    continue
                leg = walk_km(current,place) if current else 0.0
                travel = ceil(leg/speed*60)
                start = now+travel
                # Один перерыв на питание учитывается во временном плане.
                lunch = 45 if not lunch_added and now < 14*60 and start+place.duration > 13*60 else 0
                end = start+place.duration+lunch
                if walked+leg > walk_limit or end > 20*60:
                    continue
                utility = score/(1+leg)
                if current is None:
                    # Начинаем в районе с несколькими подходящими местами,
                    # чтобы изолированный объект не занял весь день.
                    neighbours = sorted(
                        walk_km(place, other) for other, _ in ranked
                        if other.id != place.id and other.id not in used
                        and other.price + place.price <= allowance
                    )[:max_points-1]
                    utility *= 1 + sum(1/(1+distance) for distance in neighbours if distance <= walk_limit)
                candidates.append((utility, -place.price, place.id, place, leg, travel, start, end, lunch))
            if not candidates:
                break
            chosen = max(candidates,key=lambda x:(x[0],x[1],x[2]))
            _,_,_,place,leg,travel,start,end,lunch = chosen
            if lunch:
                # Перерыв перед посещением сохраняет порядок и непрерывность времени.
                start += lunch
                lunch_added = True
            visits.append({"place_id": place.id, "name": place.name, "start": clock(start), "end": clock(end),
                           "price": place.price, "walk_km": round(leg,3), "travel_minutes":travel,
                           "break_before_minutes":lunch, "source_url": place.source_url,
                           "latitude":place.latitude,"longitude":place.longitude,"visit_mode":place.visit_mode})
            used.add(place.id)
            spent += place.price
            walked += leg
            now = end
            current = place
        if not visits:
            raise PlanningError("Не удалось заполнить все дни в пределах бюджета и времени. Увеличьте бюджет, начните день раньше или измените интересы.")
        remaining -= spent
        days.append({"day":day_no, "visits":visits, "visits_cost":spent, "food":FOOD_PER_DAY,
                     "transport":TRANSPORT_PER_DAY, "total":spent+FOOD_PER_DAY+TRANSPORT_PER_DAY,
                     "walk_km":round(walked,3)})
        if len(visits) < max_points:
            warnings.append(f"День {day_no}: меньше посещений из-за бюджета, времени, расстояния или доступного каталога.")
    total = sum(day["total"] for day in days)
    assert total <= request.budget
    return {"destination":request.destination,"days":days,"total":total,
            "remaining":request.budget-total,"warnings":list(dict.fromkeys(warnings)),
            "algorithm":"interest-score + dense-area anchor + nearest-neighbour utility + budget/time/walking constraints",
            "input":request.model_dump()}

