from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import Config
from app.demo import DemoService, workbook
from app.inventory import Inventory
from app.main import create_app
from app.recovery import Journal
from app.sheets import Problem, Sheets, cell, typed_rows
from scripts.migrate import prepare_legacy, stage_requests


@pytest.fixture
def system(tmp_path):
    cfg = Config(state_dir=tmp_path)
    provider = DemoService(cfg)
    journal = Journal(tmp_path / "journal.sqlite", cfg.identity)
    return Inventory(Sheets(provider, cfg), journal, cfg), provider, cfg


def request(quantity=1, rid=None, pid="sapporo"):
    return {"request_id": rid or str(uuid4()), "lines": [{"product_id":pid, "quantity":quantity}]}


def test_verified_save_repeat_and_intentional_new_request(system):
    inv, provider, _ = system
    req = request(3)
    first = inv.submit(req)
    assert first["lines"][0]["remaining"] == 45
    assert inv.submit(req) == first
    inv.submit(request(3))
    assert provider.write_count == 2
    assert inv.status()["products"][0]["count"] == 42
    assert inv.submit(req) == first  # later legitimate saves do not invalidate receipts


@pytest.mark.parametrize("quantity", [0,-1,1.5,True,"2",None,1000001])
def test_invalid_quantity_never_dispatches(system, quantity):
    inv, provider, _ = system
    with pytest.raises(Problem): inv.submit(request(quantity))
    assert provider.write_count == 0


def test_empty_unknown_and_conflicting_payload(system):
    inv, provider, _ = system
    with pytest.raises(Problem): inv.submit({"request_id":str(uuid4()), "lines":[]})
    with pytest.raises(Problem): inv.submit(request(pid="missing"))
    req = request()
    inv.submit(req)
    req["lines"][0]["quantity"] = 2
    with pytest.raises(Problem, match="different basket"): inv.submit(req)
    assert provider.write_count == 1


def test_all_or_nothing_and_exact_stock(system):
    inv, provider, _ = system
    req = request(1)
    req["lines"].append({"product_id":"tepache", "quantity":25})
    with pytest.raises(Problem, match="Nothing was recorded"): inv.submit(req)
    assert provider.write_count == 0
    assert inv.submit(request(48))["lines"][0]["remaining"] == 0
    with pytest.raises(Problem, match="Not enough"): inv.submit(request())


def test_consolidation_and_exact_barcode(system):
    inv, provider, _ = system
    req = request()
    req["lines"].append({"product_id":"sapporo", "quantity":2})
    receipt = inv.submit(req)
    assert receipt["total_units"] == 3
    assert len(inv.sheets.read().ledger) == 1
    assert inv.sheets.read().ledger[0][5] == "000780000011"


@pytest.mark.parametrize("fault", ["timeout_before", "timeout_after"])
def test_uncertain_dispatch_recovery_and_restart(system, fault):
    inv, provider, cfg = system
    req = request(2)
    provider.fault = fault
    with pytest.raises(Problem): inv.submit(req)
    assert inv.pending()
    provider.fault = None
    restarted = Inventory(Sheets(provider, cfg), Journal(inv.journal.path, cfg.identity), cfg)
    restarted.recover()
    if fault == "timeout_after":
        assert not restarted.pending()
        assert restarted.submit(req)["total_units"] == 2
        assert provider.write_count == 1
    else:
        with pytest.raises(Problem, match="paused"): restarted.submit(request())
        assert provider.write_count == 0
        assert restarted.pending()


def test_definitive_rejection_can_retry_same_request(system):
    inv, provider, _ = system
    req = request()
    provider.fault = "reject"
    with pytest.raises(Problem): inv.submit(req)
    assert not inv.pending()
    provider.fault = None
    inv.submit(req)
    assert provider.write_count == 1


def test_two_tabs_serialized(system):
    inv, provider, _ = system
    req = request(30)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: inv.submit(req), range(2)))
    assert results[0] == results[1]
    assert provider.write_count == 1
    with pytest.raises(Problem): inv.submit(request(30))


@pytest.mark.parametrize("mutation", ["upc", "id", "formula", "opening", "numeric_barcode"])
def test_catalog_corruption_blocks_writes(system, mutation):
    inv, provider, _ = system
    rows = provider.data["sheets"][0]["data"][0]["rowData"]
    if mutation == "upc": rows[2]["values"][3] = rows[1]["values"][3]
    if mutation == "id": rows[2]["values"][0] = rows[1]["values"][0]
    if mutation == "formula": rows[1]["values"][5] = cell(48)
    if mutation == "opening": rows[1]["values"][4] = cell(-1)
    if mutation == "numeric_barcode": rows[1]["values"][3] = cell(780000011)
    with pytest.raises(Problem): inv.submit(request())
    assert provider.write_count == 0


def test_capacity_extension_updates_formula_with_write(system):
    inv, provider, cfg = system
    provider.data = workbook(cfg, capacity=2)
    inv.submit(request())
    inv.submit(request())
    snapshot = inv.sheets.read()
    assert snapshot.capacity == 1002
    assert len(snapshot.ledger) == 2
    assert snapshot.products["sapporo"]["count"] == 46


def test_saved_then_modified_history_pauses_all_writes(system):
    inv, provider, _ = system
    req = request()
    inv.submit(req)
    rows = provider.data["sheets"][1]["data"][0]["rowData"]
    rows[1]["values"][6] = cell(-2)
    with pytest.raises(Problem, match="history changed"): inv.submit(req)
    with pytest.raises(Problem, match="paused"): inv.submit(request())
    assert provider.write_count == 1


def test_journal_failure_prevents_dispatch(system, monkeypatch):
    inv, provider, _ = system
    def fail(*args): raise OSError("Disk unavailable")
    monkeypatch.setattr(inv.journal, "intent", fail)
    with pytest.raises(OSError): inv.submit(request())
    assert provider.write_count == 0


def test_local_server_boundary_and_submission(system):
    _, provider, cfg = system
    with TestClient(create_app(cfg, provider), base_url="http://127.0.0.1:8765") as client:
        status = client.get("/api/status").json()
        assert status["connected"]
        assert client.post("/api/withdrawals", json=request()).status_code == 403
        headers = {"origin":"https://evil.example", "x-session-token":status["token"]}
        assert client.post("/api/withdrawals", json=request(), headers=headers).status_code == 403
        headers["origin"] = "http://127.0.0.1:8765"
        assert client.post("/api/withdrawals", json=request(), headers=headers).status_code == 200
        assert client.get("/", headers={"host":"evil.example"}).status_code == 400
        assert client.get("/").status_code == 200


def test_instance_and_workbook_identity_guards(system):
    inv, provider, cfg = system
    with pytest.raises(Problem): Journal(inv.journal.path, "another-workbook")
    with TestClient(create_app(cfg, provider), base_url="http://127.0.0.1:8765"):
        with pytest.raises(RuntimeError, match="Another"):
            with TestClient(create_app(cfg, provider)): pass


def test_migration_baseline_excludes_old_history(system):
    _, _, cfg = system
    legacy = {"sheets":[
        {"properties":{"title":"Inventory"}, "data":[{"rowData":typed_rows([
            ["Product Name","Unit Size","UPC","Count"], ["Beer","12 oz bottle","00123",7]])}]},
        {"properties":{"title":"Transactions"}, "data":[{"rowData":typed_rows([
            ["Product Name","Unit Size","UPC","Unit Change","Change datetime","Changing device","Voice or barcode"],
            ["Beer","12 oz bottle","00123",-3,"old date","device","barcode"]])}]},
    ]}
    products, count = prepare_legacy(legacy, "sheet")
    assert products[0][3:] == ["00123",7]
    assert count == 1
    requests = stage_requests(cfg, products, [1,2], "approved-hash")
    ledger_write = next(r["updateCells"] for r in requests if "updateCells" in r and r["updateCells"]["start"]["sheetId"] == 4)
    assert len(ledger_write["rows"]) == 1  # header only; no double-counting
    assert all("deleteSheet" not in r for r in requests)


def test_crash_after_commit_before_readback(system, monkeypatch):
    inv, provider, cfg = system
    req = request(2)
    original_write = inv.sheets.write
    def crash(snapshot, rows):
        original_write(snapshot, rows)
        raise KeyboardInterrupt("simulated process termination")
    monkeypatch.setattr(inv.sheets, "write", crash)
    with pytest.raises(KeyboardInterrupt): inv.submit(req)
    restarted = Inventory(Sheets(provider, cfg), Journal(inv.journal.path, cfg.identity), cfg)
    restarted.recover()
    assert not restarted.pending()
    assert restarted.submit(req)["total_units"] == 2
    assert provider.write_count == 1


def test_known_saved_readback_failure_then_recovery(system, monkeypatch):
    inv, provider, _ = system
    req = request()
    read = inv.sheets.read
    def unavailable_after_write():
        if provider.write_count: raise ConnectionError()
        return read()
    monkeypatch.setattr(inv.sheets, "read", unavailable_after_write)
    with pytest.raises(Problem, match="readback is unavailable"): inv.submit(req)
    assert inv.pending()[0]["state"] == "saved_unverified"
    with pytest.raises(Problem, match="paused"): inv.submit(request())
    monkeypatch.setattr(inv.sheets, "read", read)
    inv.recover()
    assert not inv.pending()
    assert provider.write_count == 1


def test_partial_request_blocks_recovery(system):
    inv, provider, _ = system
    req = request()
    req["lines"].append({"product_id":"tepache", "quantity":1})
    provider.fault = "timeout_after"
    with pytest.raises(Problem): inv.submit(req)
    provider.fault = None
    provider.data["sheets"][1]["data"][0]["rowData"].pop()
    inv.recover()
    assert inv.pending()
    with pytest.raises(Problem, match="paused"): inv.submit(request())
    assert provider.write_count == 1


def test_product_text_is_never_written_as_formula(system):
    inv, provider, _ = system
    provider.data["sheets"][0]["data"][0]["rowData"][1]["values"][1] = cell('=IMPORTDATA("example")')
    inv.submit(request())
    name_cell = provider.data["sheets"][1]["data"][0]["rowData"][1]["values"][3]
    assert name_cell == {"userEnteredValue":{"stringValue":'=IMPORTDATA("example")'}}
