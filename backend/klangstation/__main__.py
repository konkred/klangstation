import argparse
import logging
import os

import uvicorn

from .config import DATA_DIR, HOST, PORT, Settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="klangstation")
    parser.add_argument("--reset-password", action="store_true",
                        help="Zugangsschutz der Weboberflaeche entfernen (vergessenes Passwort)")
    args = parser.parse_args()
    if args.reset_password:
        Settings(DATA_DIR / "settings.json").update({"auth_hash": ""})
        print("Zugangsschutz entfernt.")
        return

    level = os.environ.get("KS_LOG", "INFO").upper()
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")
    # httpx protokolliert jede Anfrage auf INFO - bei der UPnP-Abfrage (jede Sekunde) viel zu viel
    logging.getLogger("httpx").setLevel(max(logging.WARNING, logging.getLevelName(level)))
    uvicorn.run("klangstation.main:app", host=HOST, port=PORT, log_level=level.lower(),
                ws="websockets", proxy_headers=False)


if __name__ == "__main__":
    main()
