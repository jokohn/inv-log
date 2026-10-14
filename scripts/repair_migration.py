"""Recover staged balance formulas without replaying migration or changing stock."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock

from app.config import Config
from app.sheets import INVENTORY, TRANSACTIONS, Problem, Sheets, formula, formula_matches, google_service
from scripts.migrate import digest, durable_json, prepare_legacy


def entered_rows(sheet):
    """Logical cell contents, excluding computed values and formatting."""
    result = []
    for grid in sheet.get("data", []):
        for row_index, row in enumerate(grid.get("rowData", []), grid.get("startRow", 0)):
            for col, cell in enumerate(row.get("values", []), grid.get("startColumn", 0)):
                value = cell.get("userEnteredValue", {})
                if value:
                    result.append((row_index, col, value))
    return result


def repair_requests(cfg, backup, live):
    if backup.get("spreadsheet_id") != cfg.spreadsheet_id or digest(backup["workbook"]) != backup.get("sha256"):
        raise Problem("Backup identity or fingerprint does not match. No repair allowed.")
    old_tabs = {s["properties"]["title"]: s for s in backup["workbook"]["sheets"]}
    tabs = {s["properties"]["title"]: s for s in live["sheets"]}
    for title, old in old_tabs.items():
        if title not in tabs or entered_rows(old) != entered_rows(tabs[title]):
            raise Problem("Original workbook contents changed since baseline approval. Reconcile before repair.")
    required = [cfg.inventory_tab, cfg.transactions_tab, cfg.metadata_tab]
    if len(set(required)) != 3 or any(t not in tabs for t in required) or any(t in old_tabs for t in required):
        raise Problem("Expected three new staging tabs are missing or overlap baseline tabs.")
    products, _ = prepare_legacy(backup["workbook"], cfg.spreadsheet_id)
    from app.sheets import typed_rows
    meta = {r: {} for r, _, _ in entered_rows(tabs[cfg.metadata_tab])}
    for r, col, value in entered_rows(tabs[cfg.metadata_tab]):
        meta[r][col] = value.get("stringValue")
    metadata = {v.get(0): v.get(1) for v in meta.values()}
    if metadata.get("baseline_sha256") != backup["sha256"] or metadata.get("schema_version") != "1" or metadata.get("counting_model") != "whole_catalog_units":
        raise Problem("Staged metadata does not match the approved baseline.")
    expected_ledger = {"data": [{"rowData": typed_rows([TRANSACTIONS])}]}
    if entered_rows(tabs[cfg.transactions_tab]) != entered_rows(expected_ledger):
        raise Problem("Staged ledger is not empty or its header changed. Repair must not run after withdrawals.")
    inv = tabs[cfg.inventory_tab]
    expected_inv = {"data": [{"rowData": typed_rows([INVENTORY] + products)}]}
    actual = [(r, c, v) for r, c, v in entered_rows(inv) if not (r > 0 and c == 5)]
    if actual != entered_rows(expected_inv):
        raise Problem("Staged catalog differs from approved IDs, text barcodes, or opening counts.")
    cap = tabs[cfg.transactions_tab]["properties"]["gridProperties"]["rowCount"]
    formulas = {r: v.get("formulaValue") for r, c, v in entered_rows(inv) if r > 0 and c == 5}
    if set(formulas) != set(range(1, len(products) + 1)) or any(
        not formula_matches(f, r + 1, cap, cfg.transactions_tab) for r, f in formulas.items()
    ):
        raise Problem("Unexpected balance formulas. This repair only rebinds the original migration formulas.")
    requests = [{"updateCells": {"start": {"sheetId": inv["properties"]["sheetId"],
        "rowIndex": 1, "columnIndex": 5}, "fields": "userEnteredValue", "rows": [
        {"values": [{"userEnteredValue": {"formulaValue": formula(r + 2, cap, cfg.transactions_tab)}}]}
        for r in range(len(products))]}}]
    return requests, products


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="Rewrite only validated staged balance formulas")
    args = parser.parse_args()
    cfg = Config.load()
    if cfg.mode != "google":
        parser.error("Google mode is required.")
    backup = json.loads(args.backup.read_text(encoding="utf-8"))
    intent = json.loads(args.backup.with_suffix(".stage-intent.json").read_text(encoding="utf-8"))
    if intent.get("spreadsheet_id") != cfg.spreadsheet_id or intent.get("sha256") != backup.get("sha256"):
        raise Problem("Migration intent does not match this backup.")
    state = cfg.state_dir / cfg.mode
    state.mkdir(parents=True, exist_ok=True)
    with FileLock(state / "instance.lock", timeout=0):
        # Require the app to be stopped and the local journal to have no work.
        from app.recovery import Journal
        journal = Journal(state / "requests.sqlite", cfg.identity)
        with journal.connect() as db:
            if db.execute("SELECT COUNT(*) FROM requests").fetchone()[0]:
                raise Problem("Journal contains withdrawal activity. Reconcile before a migration repair.")
        service = google_service(cfg)
        api = service.spreadsheets()
        live = api.get(spreadsheetId=cfg.spreadsheet_id, includeGridData=True).execute(num_retries=2)
        requests, products = repair_requests(cfg, backup, live)
        print(f"Verified baseline fingerprint, original tabs, {len(products)} staged products, and empty ledger.")
        if not args.apply:
            print("Read-only check passed. --apply will rewrite only the staged Current Count formulas.")
            return
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        evidence = args.backup.parent / f"formula-repair-{stamp}.json"
        durable_json(evidence, {"spreadsheet_id":cfg.spreadsheet_id, "before":live, "requests":requests})
        api.batchUpdate(spreadsheetId=cfg.spreadsheet_id, body={"requests":requests}).execute(num_retries=0)
        snapshot = Sheets(service, cfg).read()
        if snapshot.ledger or {p[0]:p[4] for p in products} != {p["id"]:p["count"] for p in snapshot.products.values()}:
            raise Problem("Repair readback did not match the baseline. Keep capture stopped and inspect the saved evidence.")
        after = api.get(spreadsheetId=cfg.spreadsheet_id, includeGridData=True).execute(num_retries=2)
        repair_requests(cfg, backup, after)  # recheck all protected baseline invariants
        durable_json(evidence.with_suffix(".verified.json"), {"verified_at":stamp, "products":len(products),
            "baseline_sha256":backup["sha256"], "balances":{p["id"]:p["count"] for p in snapshot.products.values()}})
        print(f"Repair verified in Google Sheets: {len(products)} balances match approved opening counts; ledger empty; original tabs unchanged.")


if __name__ == "__main__":
    main()
