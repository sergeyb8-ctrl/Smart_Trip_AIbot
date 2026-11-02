import random
import pytest
from pydantic import ValidationError
from smarttrip.models import TripRequest, Draft, empty_draft
from smarttrip.engine import build_trip, PlanningError, rank_places, PACE, walk_km
from smarttrip.telegram import route_messages

def request(**changes):
    data=dict(destination="Санкт-Петербург",days=3,budget=10000,
              interests=["architecture","parks","museums"],exclude=[],pace="medium",start_time="10:00")
    return TripRequest.model_validate({**data,**changes})

@pytest.mark.parametrize("days",[1,2,3,4,5])
@pytest.mark.parametrize("pace",["calm","medium","active"])
def test_routes_respect_budget_walk_time_and_uniqueness(db,days,pace):
    req=request(days=days,pace=pace,budget=5000*days)
    places={p.id:p for p in db.places()}
    result=build_trip(req,list(places.values()))
    ids=[v["place_id"] for day in result["days"] for v in day["visits"]]
    assert len(ids)==len(set(ids))
    assert len(result["days"])==days
    assert result["total"]<=req.budget
    assert result["remaining"]==req.budget-result["total"]
    assert result["total"]==sum(day["total"] for day in result["days"])
    for day in result["days"]:
        previous=None
        walked=0
        end=10*60
        assert 1<=len(day["visits"])<=PACE[pace][0]
        for visit in day["visits"]:
            start=sum(int(x)*factor for x,factor in zip(visit["start"].split(":"),(60,1)))
            next_end=sum(int(x)*factor for x,factor in zip(visit["end"].split(":"),(60,1)))
            assert start>=end+visit["travel_minutes"]+visit["break_before_minutes"]
            assert next_end-start==places[visit["place_id"]].duration
            assert next_end<=20*60
            place=places[visit["place_id"]]
            if previous: walked+=walk_km(previous,place)
            previous=place
            end=next_end
        assert walked<=PACE[pace][1]+0.001
        assert day["total"]==day["food"]+day["transport"]+sum(v["price"] for v in day["visits"])
    for message in route_messages(result,1):
        assert len(message.encode("utf-16-le"))//2<=4096

def test_low_budget_explained_not_overspent(db):
    with pytest.raises(PlanningError,match="минимум"):
        build_trip(request(budget=100),db.places())

def test_exclusions_are_hard_filter(db):
    req=request(interests=["architecture","parks"],exclude=["museums"])
    result=build_trip(req,db.places())
    tags={p.id:p.tags for p in db.places()}
    assert all("museums" not in tags[v["place_id"]] for day in result["days"] for v in day["visits"])

def test_insufficient_catalog_is_not_filled_with_fake_places(db):
    with pytest.raises(PlanningError):
        build_trip(request(),db.places()[:1])

def test_geographic_order_stays_in_one_cluster():
    from smarttrip.models import Place
    def p(id,lat,lon):
        return Place(id=id,name=id,latitude=lat,longitude=lon,tags=["parks"],price=0,duration=30,
                     source_url="https://www.openstreetmap.org/node/1",opening_hours=None,
                     visit_mode="outdoor",price_note="estimate",source_date="2026-10-19")
    places=[p("a",59.93,30.30),p("b",59.931,30.301),p("z",60.00,30.45),p("d",59.932,30.302)]
    result=build_trip(request(days=1,interests=["parks"],pace="calm"),places)
    ids={v["place_id"] for v in result["days"][0]["visits"]}
    assert ids=={"a","b","d"} # farthest tie anchor must not make the route strand itself

@pytest.mark.parametrize("changes",[
    {"days":0},{"days":6},{"days":True},{"days":"3"},{"budget":-1},{"budget":"5000"},
    {"destination":"Казань"},{"start_time":"25:00"},{"interests":[]},
    {"interests":["museums"],"exclude":["museums"]}
])
def test_invalid_requests_rejected(changes):
    with pytest.raises(ValidationError):
        request(**changes)

def test_untrusted_extra_ai_fields_rejected():
    with pytest.raises(ValidationError):
        Draft.model_validate({**empty_draft(),"route":["invented place"]})

def test_seed_catalog_has_real_provenance(db):
    places=db.places()
    assert len(places)==60
    assert len({p.id for p in places})==60
    assert all(p.source_url.startswith("https://www.openstreetmap.org/") for p in places)
    assert all(p.price_note for p in places)

def test_history_is_scoped_and_persistent(db):
    req=request()
    result=build_trip(req,db.places())
    id=db.save_trip(1,req,result,"manual")
    assert db.trip(2,id) is None
    assert not db.history(2)
    assert db.trip(1,id)["result"]==result
    db.clear_history(2)
    assert db.trip(1,id)
    db.clear_history(1)
    assert db.trip(1,id) is None

def test_repeat_generation_is_deterministic(db):
    assert build_trip(request(),db.places())==build_trip(request(),db.places())

