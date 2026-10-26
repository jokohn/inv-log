import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class Config:
    mode: str = "demo"
    port: int = 8765
    state_dir: Path = Path(".state")
    device: str = "MacBook storeroom"
    spreadsheet_id: str = "demo"
    credentials: str = ""
    inventory_tab: str = "Inventory_v1"
    transactions_tab: str = "Transactions_v1"
    metadata_tab: str = "InvFlow_v1"
    openai_api_key: str = ""
    voice_model: str = "gpt-6.1-sol"

    @property
    def identity(self):
        return "|".join((self.mode, self.spreadsheet_id, self.inventory_tab,
                         self.transactions_tab, self.metadata_tab))

    @classmethod
    def load(cls):
        load_dotenv()
        cfg = cls(**{key: os.environ["INV_" + key.upper()] for key in
                    cls.__dataclass_fields__ if "INV_" + key.upper() in os.environ})
        cfg.port = int(cfg.port)
        cfg.state_dir = Path(cfg.state_dir).expanduser().resolve()
        if cfg.mode not in {"demo", "google"} or not 1024 <= cfg.port <= 65535:
            raise ValueError("Use INV_MODE=demo or google and a port between 1024 and 65535.")
        if cfg.mode == "demo":
            cfg.spreadsheet_id = "demo"
        elif not cfg.credentials or cfg.spreadsheet_id == "demo":
            raise ValueError("Google mode requires INV_CREDENTIALS and INV_SPREADSHEET_ID.")
        return cfg
