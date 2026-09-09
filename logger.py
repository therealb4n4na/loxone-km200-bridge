#!/usr/bin/env python3
"""
Buderus KM200 History Logger
============================

Zweck
-----
Separater Hintergrunddienst fuer Langzeitdaten. Er fragt alle 60 Sekunden den
lokalen KM200-Bridge-Endpunkt http://127.0.0.1:8095/status ab und schreibt
einen Snapshot in SQLite. Der frueher verwendete DS18B20 an der Zirkulations-
Ruecklaufleitung ist derzeit bewusst deaktiviert und nicht mehr angeschlossen.

Datenfluss
----------
KM200-Bridge :8095/status -> save() ->
/var/lib/buderus-km200-history/history.sqlite3

Code-Leseplan / Fehlersuche
---------------------------
read_circ_temp()  -> optionalen DS18B20 lesen; derzeit deaktiviert => None
open_db()         -> SQLite/WAL initialisieren, Tabelle/Index bei Bedarf anlegen
get_status()      -> lokalen /status-Endpunkt der KM200-Bridge lesen
save()            -> genau einen Messdatensatz inkl. Zirkulationstemperatur speichern
main()            -> Endlosschleife; versucht alle INTERVAL=60 s einen Snapshot

Wichtig bei Fehlern
-------------------
- Ein "Connection refused" direkt nach gemeinsamem Neustart von Bridge+Logger
  kann entstehen, wenn der Logger schneller startet als Port 8095 lauscht. Der
  Logger beendet sich deshalb NICHT, sondern versucht es beim naechsten Zyklus erneut.
- Ist das KM200/Gateway offline, bleibt der Logger ebenfalls aktiv; entscheidend
  ist dann, ob /status erreichbar ist und welche bridge_ok/age_s-Werte gespeichert
  werden. Gateway-Ausfall und Logger-Ausfall sind zwei verschiedene Dinge.
- Der DS18B20 ist derzeit nicht angeschlossen. circ_return_temp_c bleibt deshalb
  absichtlich None; die historische Spalte bleibt für eine spätere Nutzung erhalten.
- Die Datenbank nutzt WAL + synchronous=NORMAL, damit zyklische Writes robust sind.
- Dieses Script schreibt KEINE Werte zur Heizung und greift NICHT direkt auf das
  KM200 zu; es liest ausschliesslich die lokale Bridge.
"""

import json
import sqlite3
import time
import urllib.request
from datetime import datetime

URL = "http://127.0.0.1:8095/status"
DB = "/var/lib/buderus-km200-history/history.sqlite3"
INTERVAL = 60

# Der frühere Zirkulations-DS18B20 wurde abgebaut. None deaktiviert den Zugriff
# sauber, ohne die bestehende History-Spalte entfernen zu müssen.
W1_SENSOR = None


def bool_int(value):
    if value is None:
        return None
    return 1 if bool(value) else 0


def read_circ_temp():
    if not W1_SENSOR:
        return None

    try:
        with open(W1_SENSOR, "r", encoding="utf-8") as f:
            lines = f.readlines()

        if len(lines) < 2:
            return None

        if "YES" not in lines[0]:
            return None

        pos = lines[1].find("t=")
        if pos == -1:
            return None

        return round(float(lines[1][pos + 2:].strip()) / 1000.0, 3)

    except Exception:
        return None


def open_db():
    db = sqlite3.connect(DB)

    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")

    db.execute("""
        CREATE TABLE IF NOT EXISTS samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sampled_at TEXT NOT NULL,
            sample_epoch INTEGER NOT NULL,

            gateway_online INTEGER,
            bridge_ok INTEGER,
            poll_errors INTEGER,
            age_s REAL,

            outdoor_temp_c REAL,

            dhw_actual_temp_c REAL,
            dhw_current_setpoint_c REAL,
            dhw_set_temperature_c REAL,
            dhw_operation_mode TEXT,
            dhw_program TEXT,

            dhw_extra_activation_status TEXT,
            dhw_extra_status TEXT,
            dhw_extra_active INTEGER,
            dhw_extra_time_h REAL,
            dhw_extra_stop_temp_c REAL,

            hc1_status TEXT,
            hc1_operation_mode TEXT,
            hc1_program TEXT,
            hc1_active INTEGER,
            hc1_supply_setpoint_c REAL,
            hc1_curve_percent REAL,

            circ_return_temp_c REAL
        )
    """)

    columns = {
        row[1]
        for row in db.execute("PRAGMA table_info(samples)")
    }

    if "circ_return_temp_c" not in columns:
        db.execute("""
            ALTER TABLE samples
            ADD COLUMN circ_return_temp_c REAL
        """)

    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_samples_epoch
        ON samples(sample_epoch)
    """)

    db.commit()
    return db


def get_status():
    req = urllib.request.Request(
        URL,
        headers={"User-Agent": "buderus-history/1.1"}
    )

    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(
            response.read().decode("utf-8")
        )


def save(db, d):
    now = datetime.now().astimezone()
    circ_temp = read_circ_temp()

    db.execute("""
        INSERT INTO samples (
            sampled_at,
            sample_epoch,

            gateway_online,
            bridge_ok,
            poll_errors,
            age_s,

            outdoor_temp_c,

            dhw_actual_temp_c,
            dhw_current_setpoint_c,
            dhw_set_temperature_c,
            dhw_operation_mode,
            dhw_program,

            dhw_extra_activation_status,
            dhw_extra_status,
            dhw_extra_active,
            dhw_extra_time_h,
            dhw_extra_stop_temp_c,

            hc1_status,
            hc1_operation_mode,
            hc1_program,
            hc1_active,
            hc1_supply_setpoint_c,
            hc1_curve_percent,

            circ_return_temp_c
        )
        VALUES (
            ?, ?,
            ?, ?, ?, ?,
            ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?,
            ?
        )
    """, (
        now.isoformat(timespec="seconds"),
        int(now.timestamp()),

        bool_int(d.get("gateway_online")),
        bool_int(d.get("bridge_ok")),
        d.get("poll_errors"),
        d.get("age_s"),

        d.get("outdoor_temp_c"),

        d.get("dhw_actual_temp_c"),
        d.get("dhw_current_setpoint_c"),
        d.get("dhw_set_temperature_c"),
        d.get("dhw_operation_mode"),
        d.get("dhw_program"),

        d.get("dhw_extra_activation_status"),
        d.get("dhw_extra_status"),
        bool_int(d.get("dhw_extra_active")),
        d.get("dhw_extra_time_h"),
        d.get("dhw_extra_stop_temp_c"),

        d.get("hc1_status"),
        d.get("hc1_operation_mode"),
        d.get("hc1_program"),
        bool_int(d.get("hc1_active")),
        d.get("hc1_supply_setpoint_c"),
        d.get("hc1_curve_percent"),

        circ_temp,
    ))

    db.commit()


def main():
    db = open_db()

    while True:
        started = time.monotonic()

        try:
            save(db, get_status())

        except Exception as exc:
            print(
                datetime.now().astimezone().isoformat(timespec="seconds"),
                "ERROR:",
                exc,
                flush=True
            )

        duration = time.monotonic() - started
        time.sleep(max(1, INTERVAL - duration))


if __name__ == "__main__":
    main()
