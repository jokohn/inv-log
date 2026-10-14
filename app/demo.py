"""Small Google-client boundary simulator. Demo data is separate from live state."""
import copy
import json
import os

from .sheets import INVENTORY, TRANSACTIONS, formula, typed_rows

PRODUCTS = [
    ["sapporo", "Sapporo Premium", "12 oz bottle", "000780000011", 48],
    ["tepache", "Tepache · Spiced Pineapple", "12 oz can", "008500395210", 24],
    ["perrier", "Perrier Sparkling Water", "330 ml bottle", "007478000011", 72],
    ["coke", "Coca-Cola Original", "12 oz can", "004900000634", 96],
    ["fever", "Fever-Tree Indian Tonic", "200 ml bottle", "089819500112", 18],
    ["orange", "Orange Juice", "10 oz bottle", "004850000123", 8],
]


def workbook(config, products=None, capacity=1001):
    products = PRODUCTS if products is None else products
    sheets = []
    for sid, title, headers, rows, row_count in [
        (1, config.inventory_tab, INVENTORY, products, max(100, len(products) + 1)),
        (2, config.transactions_tab, TRANSACTIONS, [], capacity),
        (3, config.metadata_tab, ["schema_version", "1"], [["counting_model", "whole_catalog_units"]], 10),
    ]:
        grid = typed_rows([headers] + rows)
        if sid == 1:
            for n, row in enumerate(grid[1:], 2):
                row["values"].append({"userEnteredValue": {"formulaValue": formula(n, capacity, config.transactions_tab)}})
        sheets.append(dict(properties=dict(sheetId=sid, title=title,
            gridProperties=dict(rowCount=row_count, columnCount=max(13, len(headers)))), data=[dict(rowData=grid)]))
    return dict(sheets=sheets)


class Call:
    def __init__(self, fn):
        self.fn = fn

    def execute(self, num_retries=0):
        return self.fn()


class DemoService:
    def __init__(self, config, path=None, data=None):
        self.config, self.path = config, path
        self.data = json.loads(path.read_text(encoding="utf-8")) if path and path.exists() else (data or workbook(config))
        self.write_count = 0
        self.fault = None
        self.persist()

    def spreadsheets(self):
        return self

    def persist(self):
        if self.path:
            tmp = self.path.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(self.data, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)

    def get(self, **kwargs):
        def read():
            data = copy.deepcopy(self.data)
            totals = {}
            for r in data["sheets"][1]["data"][0]["rowData"][1:]:
                vs = [next(iter(c.get("userEnteredValue", {}).values()), "") for c in r.get("values", [])]
                if len(vs) >= 7:
                    totals[vs[2]] = totals.get(vs[2], 0) + vs[6]
            for r in data["sheets"][0]["data"][0]["rowData"][1:]:
                v = r["values"]
                if len(v) >= 6 and "formulaValue" in v[5].get("userEnteredValue", {}):
                    v[5]["effectiveValue"] = {"numberValue": v[4]["userEnteredValue"]["numberValue"] + totals.get(v[0]["userEnteredValue"]["stringValue"], 0)}
            return data
        return Call(read)

    def batchUpdate(self, spreadsheetId, body):
        def write():
            if self.fault == "reject":
                from .sheets import DefinitiveRejection
                raise DefinitiveRejection("Simulated definitive rejection.")
            if self.fault == "timeout_before":
                raise TimeoutError()
            data = copy.deepcopy(self.data)
            for req in body["requests"]:
                if "appendDimension" in req:
                    op = req["appendDimension"]
                    target = next(s for s in data["sheets"] if s["properties"]["sheetId"] == op["sheetId"])
                    target["properties"]["gridProperties"]["rowCount"] += op["length"]
                elif "updateCells" in req:
                    op = req["updateCells"]
                    start = op["start"]
                    target = next(s for s in data["sheets"] if s["properties"]["sheetId"] == start["sheetId"])
                    grid = target["data"][0]["rowData"]
                    for offset, row in enumerate(op["rows"]):
                        idx = start["rowIndex"] + offset
                        while len(grid) <= idx:
                            grid.append({"values": []})
                        cells = grid[idx]["values"]
                        col = start["columnIndex"]
                        while len(cells) < col + len(row["values"]):
                            cells.append({})
                        cells[col:col + len(row["values"])] = row["values"]
                else:
                    raise ValueError("Unsupported demo operation")
            self.data = data
            self.write_count += 1
            self.persist()
            if self.fault == "timeout_after":
                raise TimeoutError()
            return {}
        return Call(write)
