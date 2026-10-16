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


@pytest.mark.parametrize("kind", ["withdrawal", "receiving"])
@pytest.mark.parametrize("quantity", [0, -1, 1.5, True, "2", None, 1000001])
def test_direction_invalid_quantity(system, kind, quantity):
    inv, provider, _ = system
    with pytest.raises(Problem): inv.submit(request(quantity), kind)
    assert provider.write_count == 0


def test_receiving_balance_identity_and_mixed_history(system):
    inv, provider, _ = system
    inv.submit(request(38))  # 10 on hand
    req = request(48)
    receipt = inv.submit(req, "receiving")
    assert receipt["movement_type"] == "receiving"
    assert receipt["total_units"] == 48
    assert receipt["lines"][0]["remaining"] == 58
    row = inv.sheets.read().ledger[-1]
    assert row[5:7] == ["000780000011", 48]
    assert row[10:] == ["receiving", "", ""]
    with pytest.raises(Problem, match="different basket"): inv.submit(req)
    inv.submit(request(48), "receiving")
    inv.submit(request(6))
    assert inv.submit(req, "receiving") == receipt
    assert provider.write_count == 4
    assert inv.sheets.read().products["sapporo"]["count"] == 100


def test_receiving_zero_stock_consolidation_and_stale_product(system):
    inv, provider, _ = system
    inv.submit(request(48))
    with pytest.raises(Problem): inv.submit(request())
    req = request(49)
    req["lines"].append({"product_id":"missing", "quantity":1})
    with pytest.raises(Problem): inv.submit(req, "receiving")
    assert provider.write_count == 1
    req["lines"][-1] = {"product_id":"sapporo", "quantity":2}
    receipt = inv.submit(req, "receiving")
    assert receipt["total_units"] == receipt["lines"][0]["remaining"] == 51
    assert len(receipt["lines"]) == 1


@pytest.mark.parametrize("fault", ["timeout_before", "timeout_after", "reject", "crash", "readback", "partial", "balance", "journal"])
def test_receiving_failure_and_restart(system, monkeypatch, fault):
    inv, provider, cfg = system
    req = request(2)
    req["lines"].append({"product_id":"tepache", "quantity":1})
    original_read, original_write = inv.sheets.read, inv.sheets.write
    if fault in ("timeout_before", "timeout_after", "reject", "partial", "balance"):
        provider.fault = "timeout_after" if fault in ("partial", "balance") else fault
    if fault == "crash":
        def crash(snapshot, rows):
            original_write(snapshot, rows)
            raise KeyboardInterrupt()
        monkeypatch.setattr(inv.sheets, "write", crash)
    if fault == "readback":
        def unavailable():
            if provider.write_count: raise ConnectionError()
            return original_read()
        monkeypatch.setattr(inv.sheets, "read", unavailable)
    if fault == "journal":
        def unavailable(*args): raise OSError()
        monkeypatch.setattr(inv.journal, "intent", unavailable)
    with pytest.raises((Problem, KeyboardInterrupt, OSError)): inv.submit(req, "receiving")
    if fault == "journal":
        assert provider.write_count == 0
        return
    if fault != "reject":
        assert inv.pending()[0]["movement_type"] == "receiving"
        assert inv.pending()[0]["lines"] == req["lines"]
    if fault == "partial": provider.data["sheets"][1]["data"][0]["rowData"].pop()
    if fault == "balance":
        # A legitimate external movement still prevents verification of the expected post-save balance.
        provider.fault = None
        row = original_read().ledger[0].copy()
        row[0], row[1], row[6] = str(uuid4()), 1, 1
        original_write(original_read(), [row])
    provider.fault = None
    restarted = Inventory(Sheets(provider, cfg), Journal(inv.journal.path, cfg.identity), cfg)
    restarted.recover()
    if fault in ("timeout_before", "partial", "balance"):
        writes = provider.write_count
        for kind in ("withdrawal", "receiving"):
            with pytest.raises(Problem, match="paused"): restarted.submit(request(), kind)
        assert provider.write_count == writes
    else:
        assert not restarted.pending()
        assert restarted.submit(req, "receiving")["total_units"] == 3
        assert provider.write_count == 1


@pytest.mark.parametrize("state", ["pending", "verified"])
def test_actual_legacy_payload_and_receipt_are_preserved(system, state):
    import json
    inv, provider, _ = system
    req = request(2)
    receipt = inv.submit(req)
    receipt.pop("movement_type")
    legacy_payload = '{"sapporo":2}'
    with inv.journal.connect() as db:
        db.execute("UPDATE requests SET payload=?, state=?, receipt=? WHERE id=?",
                   (legacy_payload, state, json.dumps(receipt) if state == "verified" else None, req["request_id"]))
    before = inv.journal.get(req["request_id"])
    if state == "pending":
        assert inv.pending()[0]["movement_type"] == "withdrawal"
        assert inv.pending()[0]["lines"] == req["lines"]
        inv.recover()
    else:
        inv.submit(request(3), "receiving")
    recovered = inv.submit(req)
    assert recovered["lines"] == receipt["lines"]
    if state == "verified": assert recovered == receipt
    after = inv.journal.get(req["request_id"])
    for field in ("id", "payload", "evidence", "created"):
        assert after[field] == before[field]
    with pytest.raises(Problem, match="different basket"): inv.submit(req, "receiving")
    assert provider.write_count == (1 if state == "pending" else 2)


@pytest.mark.parametrize("kind,change,method,note,related", [
    ("receiving", -1, "barcode", "", ""), ("receiving", 1, "manual", "", ""),
    ("receiving", 1, "barcode", "note", ""), ("receiving", 1, "barcode", "", "id"),
    ("withdrawal", 1, "barcode", "", ""), ("unknown", 1, "barcode", "", "")])
def test_invalid_movement_ledger_blocks_both_directions(system, kind, change, method, note, related):
    inv, provider, _ = system
    inv.submit(request(), "receiving")
    row = provider.data["sheets"][1]["data"][0]["rowData"][1]["values"]
    for index, value in ((6, change), (9, method), (10, kind), (11, note), (12, related)):
        row[index] = cell(value)
    for direction in ("withdrawal", "receiving"):
        with pytest.raises(Problem): inv.submit(request(), direction)
    assert provider.write_count == 1


def test_receiving_expansion_and_concurrent_withdrawal(system):
    inv, provider, cfg = system
    provider.data = workbook(cfg, capacity=2)
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(inv.submit, request(10), kind) for kind in ("receiving", "withdrawal")]
        assert all(f.result()["total_units"] == 10 for f in futures)
    snapshot = inv.sheets.read()
    assert snapshot.products["sapporo"]["count"] == 48
    assert snapshot.capacity == 1002
    assert provider.write_count == 2


def test_receiving_api_boundary_and_contradictions(system):
    _, provider, cfg = system
    with TestClient(create_app(cfg, provider), base_url="http://127.0.0.1:8765") as client:
        status = client.get("/api/status").json()
        assert client.post("/api/receiving", json=request()).status_code == 403
        headers = {"origin":"https://evil.example", "x-session-token":status["token"]}
        assert client.post("/api/receiving", json=request(), headers=headers).status_code == 403
        headers["origin"] = "http://127.0.0.1:8765"
        for route, kind in (("receiving", "withdrawal"), ("withdrawals", "receiving"), ("receiving", "unknown"), ("receiving", None)):
            req = dict(request(), movement_type=kind)
            assert client.post('/api/' + route, json=req, headers=headers).status_code == 422
        assert provider.write_count == 0
        assert client.post("/api/receiving", json=request(), headers=headers).json()["lines"][0]["remaining"] == 49
        assert client.post("/api/withdrawals", json=request(), headers=headers).json()["lines"][0]["remaining"] == 48



def test_receiving_duplicate_concurrent_requests_and_changed_payload(system):
    inv, provider, _ = system
    req = request(3)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: inv.submit(req, "receiving"), range(2)))
    assert results[0] == results[1]
    assert provider.write_count == 1
    assert inv.sheets.read().products["sapporo"]["count"] == 51
    for replacement in (request(4, req["request_id"]), request(3, req["request_id"], "tepache")):
        with pytest.raises(Problem, match="different basket"): inv.submit(replacement, "receiving")
    assert provider.write_count == 1


def test_mixed_adjustments_and_receiving_preserve_literal_product_text(system):
    inv, provider, _ = system
    provider.data["sheets"][0]["data"][0]["rowData"][1]["values"][1] = cell('=IMPORTDATA("example")')
    inv.submit(request(), "receiving")
    snapshot = inv.sheets.read()
    row = snapshot.ledger[0].copy()
    row[0], row[6], row[9], row[10], row[11] = str(uuid4()), -2, "manual", "adjustment", "Count correction"
    inv.sheets.write(snapshot, [row])
    inv.submit(request())
    assert inv.sheets.read().products["sapporo"]["count"] == 46
    name = provider.data["sheets"][1]["data"][0]["rowData"][1]["values"][3]
    assert name == cell('=IMPORTDATA("example")')
