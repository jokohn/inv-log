import json
import threading
from datetime import datetime, timezone
from uuid import UUID

from .sheets import DefinitiveRejection, Problem


def canonical(request):
    if not isinstance(request, dict) or set(request) != {"request_id", "lines"}:
        raise Problem("Submit a request identity and basket lines.")
    try:
        rid = str(UUID(request["request_id"]))
    except (ValueError, TypeError, AttributeError):
        raise Problem("Request identity must be a UUID.")
    lines = request["lines"]
    if not isinstance(lines, list) or not 1 <= len(lines) <= 200:
        raise Problem("Basket must contain between 1 and 200 products.")
    combined = {}
    for line in lines:
        if not isinstance(line, dict) or set(line) != {"product_id", "quantity"}:
            raise Problem("Each basket line requires a product and quantity.")
        pid, qty = line["product_id"], line["quantity"]
        if not isinstance(pid, str) or not 1 <= len(pid) <= 100 or type(qty) is not int or not 1 <= qty <= 1000000:
            raise Problem("Quantities must be positive whole numbers up to 1,000,000.")
        combined[pid] = combined.get(pid, 0) + qty
        if combined[pid] > 1000000:
            raise Problem("Consolidated quantity is too large.")
    return rid, json.dumps(combined, sort_keys=True, separators=(",", ":")), combined


class Inventory:
    def __init__(self, sheets, journal, config):
        self.sheets, self.journal, self.config = sheets, journal, config
        self.lock = threading.RLock()

    def verify(self, record, snapshot):
        evidence = json.loads(record["evidence"])
        found = [r for r in snapshot.ledger if r[0] == record["id"]]
        expected = evidence["rows"]
        if sorted(found, key=lambda r: r[1]) != expected:
            self.journal.state(record["id"], "pending")
            raise Problem("Save outcome is unresolved. New withdrawals are paused; check recovery. Do not submit under a new ID.", 409)
        if any(snapshot.products[pid]["count"] != count for pid, count in evidence["after"].items()):
            self.journal.state(record["id"], "saved_unverified")
            raise Problem("Transaction rows are saved but balances could not be verified. Reconciliation is required.", 409)
        receipt = dict(request_id=record["id"], timestamp=expected[0][7],
                       total_units=sum(-r[6] for r in expected),
                       lines=[dict(product_id=r[2], name=r[3], unit=r[4], quantity=-r[6], remaining=evidence["after"][r[2]]) for r in expected])
        self.journal.state(record["id"], "verified", receipt)
        return receipt

    def recover(self):
        with self.lock:
            pending = self.journal.unresolved()
            for record in pending:
                try:
                    self.verify(record, self.sheets.read())
                except Exception:
                    # An unavailable provider, malformed ledger, or absent rows cannot prove failure.
                    if self.journal.get(record["id"])["state"] == "sending":
                        self.journal.state(record["id"], "pending")
            return self.pending()

    def pending(self):
        return [dict(request_id=r["id"], state=r["state"],
                     lines=[dict(product_id=p, quantity=q) for p, q in json.loads(r["payload"]).items()])
                for r in self.journal.unresolved()]

    def status(self):
        with self.lock:
            snapshot = self.sheets.read()
            return dict(products=list(snapshot.products.values()), pending=self.pending(), recent=self.journal.recent())

    def submit(self, request):
        rid, payload, lines = canonical(request)
        with self.lock:
            old = self.journal.get(rid)
            if old and old["payload"] != payload:
                raise Problem("This request ID already belongs to a different basket.", 409)
            if old and old["state"] == "verified":
                # Recheck exact saved rows; later legitimate withdrawals may have changed stock.
                snapshot = self.sheets.read()
                found = sorted([r for r in snapshot.ledger if r[0] == rid], key=lambda r: r[1])
                if found != json.loads(old["evidence"])["rows"]:
                    self.journal.state(rid, "saved_unverified")
                    raise Problem("Previously verified history changed. Reconciliation is required.", 409)
                return json.loads(old["receipt"])
            self.recover()
            if self.pending():
                raise Problem("A previous save is unresolved. New withdrawals are paused until recovery is verified.", 409)
            old = self.journal.get(rid)
            if old and old["state"] == "verified":
                return json.loads(old["receipt"])
            snapshot = self.sheets.read()
            if any(r[0] == rid for r in snapshot.ledger):
                raise Problem("Request exists in Sheets without matching local evidence. Reconcile on the original device.", 409)
            for pid, qty in lines.items():
                if pid not in snapshot.products:
                    raise Problem("A basket product no longer exists in the catalog. Refresh and review your basket.")
                p = snapshot.products[pid]
                if qty > p["count"]:
                    raise Problem(f"Not enough {p['name']}: requested {qty}, available {p['count']}. Nothing was recorded.")
            timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            rows, after = [], {}
            for n, (pid, qty) in enumerate(sorted(lines.items()), 1):
                p = snapshot.products[pid]
                rows.append([rid, n, pid, p["name"], p["unit"], p["upc"], -qty, timestamp,
                             self.config.device, "barcode", "withdrawal", "", ""])
                after[pid] = p["count"] - qty
            self.journal.intent(rid, payload, dict(rows=rows, after=after))
            try:
                self.sheets.write(snapshot, rows)
            except DefinitiveRejection as exc:
                self.journal.state(rid, "rejected")
                raise Problem(str(exc), 422) from None
            except Exception:
                self.journal.state(rid, "pending")
                raise Problem("Connection interrupted during saving. Basket is locked until recovery verifies the result.", 409) from None
            self.journal.state(rid, "saved_unverified")
            try:
                return self.verify(self.journal.get(rid), self.sheets.read())
            except Problem:
                raise
            except Exception:
                raise Problem("Write was accepted, but readback is unavailable. Use Check recovery; do not resubmit.", 409) from None
