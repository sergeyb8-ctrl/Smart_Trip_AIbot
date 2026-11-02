from pathlib import Path
import pytest
from smarttrip.database import Database
from smarttrip.settings import ROOT

@pytest.fixture
def db(tmp_path):
    return Database(tmp_path/"test.sqlite3",ROOT/"data"/"places_spb.json")

