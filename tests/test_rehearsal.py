import asyncio
import json

import pytest

from app.config import Config
from app.sheets import Problem
from scripts import rehearse_voice as rehearsal


def test_live_rehearsal_cap_prevents_dispatch(tmp_path, monkeypatch):
    path = tmp_path / "spend.json"
    path.write_text(json.dumps(dict(reserved_usd=5, actual_reported_usd=0, attempts=[])))
    monkeypatch.setattr(rehearsal, "SPEND_PATH", path)
    async def forbidden(*args):
        pytest.fail("Cap must prevent dispatch")
    monkeypatch.setattr(rehearsal.CaptureAssistance, "interpret", forbidden)
    assert not asyncio.run(rehearsal.rehearse(Config(openai_api_key="fixture-only")))
    assert json.loads(path.read_text())["reserved_usd"] == 5


def test_uncertain_rehearsal_reservation_persists_before_call(tmp_path, monkeypatch):
    path = tmp_path / "spend.json"
    monkeypatch.setattr(rehearsal, "SPEND_PATH", path)
    calls = []
    async def failure(*args):
        value = json.loads(path.read_text())
        assert value["reserved_usd"] > 0 and value["attempts"][-1]["status"] == "dispatching"
        calls.append(value["reserved_usd"])
        raise Problem("fixture timeout")
    monkeypatch.setattr(rehearsal.CaptureAssistance, "interpret", failure)
    cfg = Config(openai_api_key="fixture-only")
    assert not asyncio.run(rehearsal.rehearse(cfg))
    assert not asyncio.run(rehearsal.rehearse(cfg))
    assert len(calls) == 2 and calls[1] > calls[0]
    assert all(a["status"] == "error" for a in json.loads(path.read_text())["attempts"])


def test_missing_key_prevents_rehearsal(tmp_path, monkeypatch):
    monkeypatch.setattr(rehearsal, "SPEND_PATH", tmp_path / "spend.json")
    with pytest.raises(Problem, match="locally"):
        asyncio.run(rehearsal.rehearse(Config()))
    assert not rehearsal.SPEND_PATH.exists()
