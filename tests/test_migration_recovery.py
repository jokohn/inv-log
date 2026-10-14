import copy

import pytest

from app.config import Config
from app.demo import workbook
from app.sheets import Problem, formula, formula_matches, typed_rows
from scripts.migrate import digest, prepare_legacy, stage_requests
from scripts.repair_migration import repair_requests


@pytest.fixture
def staged():
    cfg = Config()
    old = {"sheets": [
        {"properties": {"title":"Inventory"}, "data":[{"rowData":typed_rows([
            ["Product Name","Unit Size","UPC","Count"], ["Bottle","12 oz","00123",7]])}]},
        {"properties": {"title":"Transactions"}, "data":[{"rowData":typed_rows([
            ["Product Name","Unit Size","UPC","Unit Change","Change datetime","Changing device","Voice or barcode"]])}]},
    ]}
    backup = {"workbook":old, "sha256":digest(old), "spreadsheet_id":cfg.spreadsheet_id}
    products, _ = prepare_legacy(old, cfg.spreadsheet_id)
    live = copy.deepcopy(old)
    new = workbook(cfg, products)
    new["sheets"][2]["data"][0]["rowData"].extend(typed_rows([["baseline_sha256",backup["sha256"]]]))
    live["sheets"].extend(new["sheets"])
    return cfg, backup, live, products


def test_all_referenced_tabs_exist_before_any_formula_write(staged):
    cfg, _, _, products = staged
    requests = stage_requests(cfg, products, [1,2], "hash")
    assert all("addSheet" in req for req in requests[:3])
    assert all("addSheet" not in req for req in requests[3:])


def test_google_canonicalized_quotes_are_equivalent():
    expected = formula(2,1001,"Transactions_v1")
    assert formula_matches(expected.replace("'", ""),2,1001,"Transactions_v1")
    assert not formula_matches(expected.replace("1001", "1000"),2,1001,"Transactions_v1")
    assert not formula_matches(expected + "+1",2,1001,"Transactions_v1")


def test_repair_changes_only_formula_cells(staged):
    cfg, backup, live, products = staged
    requests, found = repair_requests(cfg, backup, live)
    assert found == products
    assert len(requests) == 1
    update = requests[0]["updateCells"]
    assert update["start"]["columnIndex"] == 5
    assert update["start"]["rowIndex"] == 1
    assert update["fields"] == "userEnteredValue"
    assert len(update["rows"]) == len(products)
    assert all(list(r["values"][0]["userEnteredValue"]) == ["formulaValue"] for r in update["rows"])


@pytest.mark.parametrize("change", ["ledger", "opening", "legacy", "formula", "provenance"])
def test_repair_refuses_changed_data(staged, change):
    cfg, backup, live, _ = staged
    if change == "ledger": live["sheets"][3]["data"][0]["rowData"].extend(typed_rows([["new withdrawal"]]))
    if change == "opening": live["sheets"][2]["data"][0]["rowData"][1]["values"][4]["userEnteredValue"]["numberValue"] = 8
    if change == "legacy": live["sheets"][0]["data"][0]["rowData"][1]["values"][3]["userEnteredValue"]["numberValue"] = 8
    if change == "formula": live["sheets"][2]["data"][0]["rowData"][1]["values"][5]["userEnteredValue"]["formulaValue"] = "=7"
    if change == "provenance": live["sheets"][4]["data"][0]["rowData"][-1]["values"][1]["userEnteredValue"]["stringValue"] = "wrong"
    with pytest.raises(Problem): repair_requests(cfg, backup, live)
