"""Explicit, additive staging only. Never edits or replays the legacy ledger."""
import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from app.config import Config
from app.demo import workbook
from app.sheets import Problem, Sheets, google_service, integer, text


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def prepare_legacy(data, spreadsheet_id, inventory_tab="Inventory", transaction_tab="Transactions"):
    tabs = {s["properties"]["title"]: s for s in data["sheets"]}
    if inventory_tab not in tabs or transaction_tab not in tabs:
        raise Problem("Legacy Inventory and Transactions tabs are required.")
    def rows(tab):
        return tab.get("data", [{}])[0].get("rowData", [])
    def value(c):
        v = c.get("effectiveValue", c.get("userEnteredValue", {}))
        if "errorValue" in v:
            raise Problem("Legacy formula error. Reconcile before migration.")
        return next(iter(v.values()), "")
    catalog = rows(tabs[inventory_tab])
    header = [value(c) for c in catalog[0].get("values", [])] if catalog else []
    if header[:4] != ["Product Name", "Unit Size", "UPC", "Count"]:
        raise Problem("Legacy Inventory headers do not match the expected four columns.")
    history = rows(tabs[transaction_tab])
    hist_header = [value(c) for c in history[0].get("values", [])] if history else []
    if hist_header[:7] != ["Product Name", "Unit Size", "UPC", "Unit Change", "Change datetime", "Changing device", "Voice or barcode"]:
        raise Problem("Legacy Transactions headers do not match. Review before migration.")
    products, seen = [], set()
    for row in catalog[1:]:
        vals = [value(c) for c in row.get("values", [])]
        if not any(v != "" for v in vals):
            continue
        if len(vals) < 4 or any(v != "" for v in vals[4:]):
            raise Problem("Unexpected occupied Inventory columns.")
        name, unit, upc, count = vals[:4]
        for v, label in [(name, "Name"), (unit, "Unit size"), (upc, "UPC")]:
            text(v, label)
        if upc in seen:
            raise Problem("Duplicate legacy barcode. Resolve before staging.")
        seen.add(upc)
        pid = str(uuid5(NAMESPACE_URL, spreadsheet_id + "/" + upc))
        products.append([pid, name, unit, upc, integer(count, "Cutover count", 0)])
    if not products:
        raise Problem("Legacy catalog is empty.")
    occupied = 0
    for row in history[1:]:
        vals = [value(c) for c in row.get("values", [])]
        if any(v != "" for v in vals):
            occupied += 1
            if len(vals) < 7 or any(v != "" for v in vals[7:]):
                raise Problem("Malformed legacy history. Review before staging.")
            integer(vals[3], "Historical unit change")
            text(vals[2], "Historical barcode")
    return products, occupied


def stage_requests(config, products, existing_ids, provenance):
    data = workbook(config, products)
    next_id = max(existing_ids, default=0) + 1
    # Google resolves references when each request is processed. Create every
    # target tab before installing any cross-tab formulas in the same batch.
    creates, writes = [], []
    for offset, sheet in enumerate(data["sheets"]):
        props = sheet["properties"]
        props["sheetId"] = next_id + offset
        props["gridProperties"]["frozenRowCount"] = 1
        if offset == 2:
            from app.sheets import typed_rows
            sheet["data"][0]["rowData"].extend(typed_rows([["baseline_sha256", provenance],
                ["cutover_utc", datetime.now(timezone.utc).isoformat()],
                ["baseline_source", "Approved reconciled legacy counts; legacy history excluded"]]))
        creates.append({"addSheet": {"properties": props}})
        writes.extend([
            {"updateCells": {"start": {"sheetId": props["sheetId"], "rowIndex": 0, "columnIndex": 0},
                             "rows": sheet["data"][0]["rowData"], "fields": "userEnteredValue"}},
            {"addProtectedRange": {"protectedRange": {"range": {"sheetId": props["sheetId"]},
                "description": "inv_flow managed schema: use controlled maintenance only", "warningOnly": True}}},
        ])
    return creates + writes


def durable_json(path, data):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", type=Path, required=True, help="New backup path for inspect; existing reviewed backup for stage")
    parser.add_argument("--stage", action="store_true")
    parser.add_argument("--approved-baseline-sha256", default="")
    parser.add_argument("--exclusive-maintenance", action="store_true")
    args = parser.parse_args()
    cfg = Config.load()
    if cfg.mode != "google":
        parser.error("Set INV_MODE=google and credentials first. This utility never migrates demo data.")
    service = google_service(cfg)
    api = service.spreadsheets()
    data = api.get(spreadsheetId=cfg.spreadsheet_id, includeGridData=True).execute(num_retries=2)
    products, history_count = prepare_legacy(data, cfg.spreadsheet_id)
    sha = digest(data)
    if not args.stage:
        durable_json(args.backup, {"spreadsheet_id":cfg.spreadsheet_id, "sha256":sha, "workbook":data})
        backup = json.loads(args.backup.read_text(encoding="utf-8"))
        if digest(backup["workbook"]) != sha:
            raise Problem("Backup readback failed.")
        print(f"Verified backup: {args.backup}\nBaseline SHA256: {sha}\nProducts: {len(products)}; legacy history rows: {history_count} (will remain excluded).")
        print("Review every current count against a reconciled/physical baseline. Inspection made no changes.")
        return
    backup = json.loads(args.backup.read_text(encoding="utf-8"))
    if not args.exclusive_maintenance or args.approved_baseline_sha256 != sha or backup["spreadsheet_id"] != cfg.spreadsheet_id or digest(backup["workbook"]) != sha:
        raise Problem("Stage requires an exclusive maintenance window, verified unchanged backup, and explicitly approved baseline hash.")
    existing = [s["properties"] for s in data["sheets"]]
    if any(p["title"] in {cfg.inventory_tab, cfg.transactions_tab, cfg.metadata_tab} for p in existing):
        raise Problem("A target staging tab already exists. Inspect it; never rerun an uncertain migration.")
    marker = args.backup.with_suffix(".stage-intent.json")
    durable_json(marker, {"state":"sending", "sha256":sha, "spreadsheet_id":cfg.spreadsheet_id})
    requests = stage_requests(cfg, products, [p["sheetId"] for p in existing], sha)
    api.batchUpdate(spreadsheetId=cfg.spreadsheet_id, body={"requests":requests}).execute(num_retries=0)
    result = Sheets(service, cfg).read()
    if result.ledger or {p[0]:p[4] for p in products} != {p["id"]:p["count"] for p in result.products.values()}:
        raise Problem("Staging verification failed. Keep the app stopped and reconcile; do not rerun migration.")
    print("Staging verified: every opening balance matches; new ledger empty; original tabs preserved.")
    print("Record cutover and stop old writers before launching the app with these configured tabs.")


if __name__ == "__main__":
    main()
