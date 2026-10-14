"""Read-only connection check. Never prints credentials or writes to Sheets."""
import json

from app.config import Config
from app.sheets import Problem, Sheets, google_service


def main():
    cfg = Config.load()
    if cfg.mode != "google":
        print("The app is configured for demo mode.")
        return
    try:
        service = google_service(cfg)
        snapshot = Sheets(service, cfg).read()
        print(f"Connection and schema verified: {len(snapshot.products)} products.")
    except Problem as exc:
        print(str(exc))
    except Exception as exc:
        print("Error category:", type(exc).__name__)
        print("HTTP status:", getattr(getattr(exc, "resp", None), "status", None))
        if hasattr(exc, "content"):
            try:
                error = json.loads(exc.content).get("error", {})
                print("Google error message:", error.get("message", "Unavailable"))
            except (ValueError, TypeError, AttributeError):
                print("No structured provider response available.")
        else:
            print("No Google HTTP response. Check network or authentication transport.")


if __name__ == "__main__":
    main()
