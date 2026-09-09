#!/usr/bin/env python3
"""
Buderus KM200 Bridge fuer Loxone
================================

Zweck
-----
Dauerhaft laufende HTTP-Bridge auf der konfigurierten DietPi-Adresse (Port 8095). Sie liest das KM200
regelmaessig aus, haelt den letzten Zustand im RAM und stellt daraus kompakte
HTTP-Endpunkte fuer Loxone und Diagnose bereit. Zusaetzlich existieren bewusst
eng begrenzte Schreib-Endpunkte fuer Warmwasser/HC1.

Datenfluss
----------
KM200 (konfigurierbare LAN-IP) -> verschluesselte HTTP-Abfragen -> poll_once() -> state ->
/status, /loxone, /health -> Loxone bzw. Diagnose

Der History-Logger ist ein eigener Dienst und liest /status alle 60 Sekunden.
Die History-Datenbank liegt unter /var/lib/buderus-km200-history/history.sqlite3.

Wichtige Endpunkte
------------------
/status                  -> kompletter aktueller Bridge-Zustand
/loxone                  -> reduzierte/numerische Werte fuer Loxone
/health                  -> 200 nur bei frischen, plausibel erfolgreichen Polls
/history/dhw             -> read-only Export der gespeicherten WW-Historie
/set/dhw_temp            -> WW-Solltemperatur schreiben
/set/dhw_mode            -> WW-Betriebsart schreiben
/set/extra_dhw           -> Extra-Warmwasser Stunden setzen
/set/hc1_mode            -> Heizkreis-1-Betriebsart schreiben

Code-Leseplan / Fehlersuche
---------------------------
ENDPOINTS                 -> Liste aller zyklisch gelesenen KM200-Pfade
read_value()              -> EINEN KM200-Pfad lesen und entschluesseln
poll_once()               -> alle Pfade lesen, Fehler sammeln, state aktualisieren
polling_task()            -> wiederholt poll_once() im POLL_INTERVAL
public_state()            -> interne Hilfsfelder vor HTTP-Ausgabe entfernen
write_allowed()           -> Schreibzugriffe auf Loxone-IP/localhost begrenzen
raw_put_verified()        -> schreiben UND denselben Pfad zur Kontrolle zuruecklesen
write_response()          -> gemeinsamer Fehler-/HTTP-Rahmen fuer Schreibbefehle
loxone_handler()          -> Loxone-spezifische reduzierte Darstellung
health_handler()          -> bewertet Bridge-Erfolg und Datenalter
dhw_history_handler()     -> liest die SQLite-Historie ausschliesslich read-only

Wichtig bei Fehlern
-------------------
- systemd "active" beweist nur, dass die Bridge selbst laeuft. Ist das KM200
  offline, bleibt der Prozess absichtlich aktiv und /health wird ungesund.
- gateway_online wird nur true, wenn /gateway/DateTime erfolgreich gelesen wird.
- bridge_ok verlangt zusaetzlich mindestens Aussentemperatur und WW-Isttemperatur.
- poll_errors zeigt, wie viele Einzel-Endpunkte im letzten Poll fehlgeschlagen sind.
- age_s zeigt das Alter des letzten erfolgreichen Datenupdates; hohe Werte sind ein
  klarer Hinweis auf Gateway-/Netzwerkprobleme.
- Schreibbefehle gelten erst als erfolgreich, wenn raw_put_verified() den Wert nach
  dem Schreiben nochmals gelesen und bestaetigt hat.
- Schreibzugriffe sind unabhaengig von der Firewall zusaetzlich per Client-IP im
  Script eingeschraenkt (WRITE_CLIENT_IP aus der lokalen Konfiguration).
- Zugangsdaten/Token stehen in /etc/buderus-km200.json, nicht im Script.

Hinweis: Dieser Dienst ist die KM200-IP-Bridge. Er hat nichts mit der separaten
WPS/Rego1000-CAN-Auswertung auf Port 8097 zu tun.
"""

import asyncio
import json
import math
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import aiohttp
from aiohttp import ClientSession, ClientTimeout, web

import bosch_thermostat_client as bosch
from bosch_thermostat_client.const import HTTP
from bosch_thermostat_client.const.ivt import IVT
from bosch_thermostat_client.encryption.ivt import IVTEncryption


CONFIG_FILE = Path("/etc/buderus-km200.json")

with CONFIG_FILE.open(encoding="utf-8") as f:
    CONFIG = json.load(f)


KM200_HOST = CONFIG["host"]
LISTEN_HOST = CONFIG.get("listen_host", "0.0.0.0")
LISTEN_PORT = int(CONFIG.get("listen_port", 8095))
POLL_INTERVAL = int(CONFIG.get("poll_interval", 30))
HISTORY_DB = "/var/lib/buderus-km200-history/history.sqlite3"

TOKEN = CONFIG["token"].replace("-", "").strip()
PASSWORD = CONFIG["password"]

WRITE_CLIENT_IP = CONFIG.get(
    "write_client_ip",
    "192.168.1.50"
)

ENC = IVTEncryption(TOKEN, PASSWORD)

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "TeleHeater/2.2.3",
}


ENDPOINTS = {
    # Gateway
    "gateway_datetime":
        "/gateway/DateTime",

    # System
    "outdoor_temp_c":
        "/system/sensors/outdoorTemperatures/t1",

    # Warmwasser
    "dhw_actual_temp_c":
        "/dhwCircuits/dhw1/actualTemp",

    "dhw_current_setpoint_c":
        "/dhwCircuits/dhw1/currentSetpoint",

    "dhw_set_temperature_c":
        "/dhwCircuits/dhw1/setTemperature",

    "dhw_operation_mode":
        "/dhwCircuits/dhw1/operationMode",

    "dhw_program":
        "/dhwCircuits/dhw1/activeDhwTimeProgram",

    "dhw_extra_activation_status":
        "/dhwCircuits/dhw1/extraDhw/activationStatus",

    "dhw_extra_status":
        "/dhwCircuits/dhw1/extraDhw/status",

    "dhw_extra_time_h":
        "/dhwCircuits/dhw1/extraDhw/time",

    "dhw_extra_stop_temp_c":
        "/dhwCircuits/dhw1/extraDhw/stopTemp",

    # Heizkreis 1
    "hc1_status":
        "/heatingCircuits/hc1/status",

    "hc1_operation_mode":
        "/heatingCircuits/hc1/operationMode",

    "hc1_program":
        "/heatingCircuits/hc1/activeSwitchProgram",

    "hc1_supply_setpoint_c":
        "/heatingCircuits/hc1/supplyTemperatureSetpoint",

    "hc1_curve_percent":
        "/heatingCircuits/hc1/heatingCurveSetting/percentage",
}


state = {
    "gateway_online": False,
    "bridge_ok": False,
    "updated_at": None,
    "age_s": None,
    "poll_errors": 0,
}


KM_LOCK = asyncio.Lock()


async def read_value(session, path):
    url = f"http://{KM200_HOST}{path}"

    async with session.get(
        url,
        headers=HEADERS
    ) as response:

        if response.status != 200:
            raise RuntimeError(
                f"HTTP {response.status}"
            )

        raw = (await response.text()).strip()

        data = ENC.json_decrypt(raw)

        if not isinstance(data, dict):
            raise RuntimeError(
                "Ungueltige KM200-Antwort"
            )

        if "value" not in data:
            raise RuntimeError(
                "Kein value-Feld"
            )

        return data["value"]


async def poll_once(session):
    values = {}
    errors = {}

    for name, path in ENDPOINTS.items():

        try:
            async with KM_LOCK:
                values[name] = await read_value(
                    session,
                    path
                )

        except Exception as exc:
            errors[name] = str(exc)

        await asyncio.sleep(0.05)

    now = time.time()

    if values:
        state.update(values)

        state["_last_success_epoch"] = now

        state["updated_at"] = (
            datetime.now()
            .astimezone()
            .isoformat(timespec="seconds")
        )

    state["poll_errors"] = len(errors)

    state["gateway_online"] = (
        "gateway_datetime" in values
    )

    required = (
        "gateway_datetime",
        "outdoor_temp_c",
        "dhw_actual_temp_c",
    )

    state["bridge_ok"] = all(
        x in values
        for x in required
    )

    state["hc1_active"] = (
        str(
            state.get(
                "hc1_status",
                ""
            )
        ).upper()
        == "ACTIVE"
    )

    state["dhw_extra_active"] = (
        str(
            state.get(
                "dhw_extra_activation_status",
                ""
            )
        ).upper()
        == "ON"
    )

    state["_errors"] = errors


async def polling_task(app):
    timeout = ClientTimeout(total=8)

    async with ClientSession(
        timeout=timeout
    ) as session:

        while True:

            try:
                await poll_once(session)

            except Exception as exc:
                state["bridge_ok"] = False
                state["gateway_online"] = False

                state["_errors"] = {
                    "poll": str(exc)
                }

            await asyncio.sleep(
                POLL_INTERVAL
            )


def public_state():
    result = {
        key: value
        for key, value in state.items()
        if not key.startswith("_")
    }

    last = state.get(
        "_last_success_epoch"
    )

    if last:
        result["age_s"] = round(
            time.time() - last,
            1
        )

    return result


def write_allowed(request):
    remote = request.remote

    return remote in {
        WRITE_CLIENT_IP,
        "127.0.0.1",
        "::1",
    }


def forbidden_response(request):
    return web.json_response(
        {
            "ok": False,
            "error": "write_access_denied",
            "client_ip": request.remote,
        },
        status=403,
    )


def equal_values(a, b):
    if isinstance(a, (int, float)) and isinstance(
        b,
        (int, float)
    ):
        return math.isclose(
            float(a),
            float(b),
            abs_tol=0.01
        )

    return str(a) == str(b)


async def raw_put_verified(
    path,
    value
):
    timeout = ClientTimeout(total=10)

    async with KM_LOCK:

        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:

            Gateway = bosch.gateway_chooser(
                device_type=IVT
            )

            gateway = Gateway(
                session=session,
                session_type=HTTP,
                host=KM200_HOST,
                access_token=TOKEN,
                password=PASSWORD,
            )

            result = await gateway.raw_put(
                path,
                value
            )

            await asyncio.sleep(0.5)

            check = await gateway.raw_query(
                path
            )

    actual = check.get("value")

    verified = (
        bool(result)
        and equal_values(
            value,
            actual
        )
    )

    return {
        "ok": verified,
        "requested": value,
        "value": actual,
        "path": path,
    }


async def write_response(
    request,
    path,
    value,
    state_key=None
):
    if not write_allowed(request):
        return forbidden_response(
            request
        )

    try:
        result = await raw_put_verified(
            path,
            value
        )

        if result["ok"] and state_key:
            state[state_key] = result["value"]

        return web.json_response(
            result,
            status=(
                200
                if result["ok"]
                else 502
            )
        )

    except Exception as exc:

        return web.json_response(
            {
                "ok": False,
                "error": str(exc),
                "path": path,
            },
            status=500,
        )


async def set_dhw_temp(request):
    raw = request.query.get(
        "value"
    )

    try:
        value = float(raw)

    except (TypeError, ValueError):
        return web.json_response(
            {
                "ok": False,
                "error":
                    "value muss eine Zahl sein"
            },
            status=400,
        )

    if not 37.0 <= value <= 57.0:
        return web.json_response(
            {
                "ok": False,
                "error":
                    "Erlaubter Bereich: 37-57 C"
            },
            status=400,
        )

    return await write_response(
        request,
        "/dhwCircuits/dhw1/setTemperature",
        value,
        "dhw_set_temperature_c"
    )


async def set_dhw_mode(request):
    value = request.query.get(
        "value",
        ""
    )

    allowed = {
        "Automatic",
        "Always_On",
        "Always_Off",
    }

    if value not in allowed:
        return web.json_response(
            {
                "ok": False,
                "error":
                    "Erlaubt: Automatic, Always_On, Always_Off"
            },
            status=400,
        )

    return await write_response(
        request,
        "/dhwCircuits/dhw1/operationMode",
        value,
        "dhw_operation_mode"
    )


async def set_extra_dhw(request):
    raw = request.query.get(
        "hours"
    )

    try:
        value = int(raw)

    except (TypeError, ValueError):
        return web.json_response(
            {
                "ok": False,
                "error":
                    "hours muss 0-48 sein"
            },
            status=400,
        )

    if not 0 <= value <= 48:
        return web.json_response(
            {
                "ok": False,
                "error":
                    "Erlaubter Bereich: 0-48 h"
            },
            status=400,
        )

    return await write_response(
        request,
        "/dhwCircuits/dhw1/extraDhw/time",
        float(value),
        "dhw_extra_time_h"
    )


async def set_hc1_mode(request):
    value = request.query.get(
        "value",
        ""
    )

    allowed = {
        "automatic",
        "normal",
        "exception",
        "heating_off",
    }

    if value not in allowed:
        return web.json_response(
            {
                "ok": False,
                "error":
                    "Erlaubt: automatic, normal, exception, heating_off"
            },
            status=400,
        )

    return await write_response(
        request,
        "/heatingCircuits/hc1/operationMode",
        value,
        "hc1_operation_mode"
    )


async def status_handler(request):
    return web.json_response(
        public_state(),
        headers={
            "Cache-Control": "no-store"
        }
    )


async def loxone_handler(request):
    s = public_state()

    dhw_modes = {
        "Automatic": 0,
        "Always_On": 1,
        "Always_Off": 2,
    }

    hc1_modes = {
        "automatic": 0,
        "normal": 1,
        "exception": 2,
        "heating_off": 3,
    }

    data = {
        "bridge_ok":
            int(bool(s.get("bridge_ok"))),

        "gateway_online":
            int(bool(s.get("gateway_online"))),

        "poll_errors":
            s.get("poll_errors"),

        "age_s":
            s.get("age_s"),

        "outdoor_temp_c":
            s.get("outdoor_temp_c"),

        "dhw_actual_temp_c":
            s.get("dhw_actual_temp_c"),

        "dhw_set_temperature_c":
            s.get("dhw_set_temperature_c"),

        "dhw_extra_stop_temp_c":
            s.get("dhw_extra_stop_temp_c"),

        "dhw_extra_time_h":
            s.get("dhw_extra_time_h"),

        "dhw_extra_active":
            int(
                bool(
                    s.get(
                        "dhw_extra_active"
                    )
                )
            ),

        "dhw_mode_code":
            dhw_modes.get(
                s.get(
                    "dhw_operation_mode"
                ),
                -1
            ),

        "hc1_active":
            int(
                bool(
                    s.get(
                        "hc1_active"
                    )
                )
            ),

        "hc1_supply_setpoint_c":
            s.get(
                "hc1_supply_setpoint_c"
            ),

        "hc1_curve_percent":
            s.get(
                "hc1_curve_percent"
            ),

        "hc1_mode_code":
            hc1_modes.get(
                s.get(
                    "hc1_operation_mode"
                ),
                -1
            ),
    }

    return web.json_response(
        data,
        headers={
            "Cache-Control": "no-store"
        }
    )


async def health_handler(request):
    result = public_state()

    age = result.get("age_s")

    healthy = (
        result.get("bridge_ok") is True
        and age is not None
        and age <= POLL_INTERVAL * 3
    )

    return web.json_response(
        {
            "ok": healthy,
            "gateway_online":
                result.get(
                    "gateway_online"
                ),
            "age_s": age,
            "poll_errors":
                result.get(
                    "poll_errors"
                ),
        },
        status=(
            200
            if healthy
            else 503
        ),
        headers={
            "Cache-Control": "no-store"
        }
    )


async def dhw_history_handler(request):
    """Read-only, bounded export of recorded DHW history for diagnostics."""
    try:
        hours = int(request.query.get("hours", "72"))
        step = int(request.query.get("step", "5"))
    except ValueError:
        return web.json_response({"ok": False, "error": "hours/step must be integers"}, status=400)

    hours = max(1, min(hours, 168))
    step = max(1, min(step, 60))
    cutoff = int(time.time()) - (hours * 3600)

    try:
        db = sqlite3.connect(f"file:{HISTORY_DB}?mode=ro", uri=True, timeout=5)
        db.row_factory = sqlite3.Row

        meta = db.execute(
            """
            SELECT MIN(sample_epoch) AS first_epoch,
                   MAX(sample_epoch) AS last_epoch,
                   COUNT(*) AS samples,
                   SUM(CASE WHEN bridge_ok=1 AND age_s<=120 THEN 1 ELSE 0 END) AS valid_samples
            FROM samples
            """
        ).fetchone()

        rows = db.execute(
            """
            SELECT id, sampled_at, sample_epoch, bridge_ok, age_s,
                   outdoor_temp_c, dhw_actual_temp_c,
                   dhw_current_setpoint_c, dhw_set_temperature_c,
                   dhw_extra_active, circ_return_temp_c
            FROM samples
            WHERE sample_epoch >= ?
              AND (id % ?) = 0
            ORDER BY sample_epoch
            """,
            (cutoff, step),
        ).fetchall()
        db.close()

        return web.json_response({
            "ok": True,
            "hours": hours,
            "step_minutes_approx": step,
            "history": dict(meta) if meta else {},
            "rows": [dict(row) for row in rows],
        }, headers={"Cache-Control": "no-store"})

    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


async def root_handler(request):
    return web.json_response(
        {
            "service":
                "Buderus KM200 Bridge",

            "mode":
                "read + restricted write",

            "write_client_ip":
                WRITE_CLIENT_IP,

            "status":
                "/status",

            "loxone":
                "/loxone",

            "health":
                "/health",

            "dhw_history":
                "/history/dhw?hours=72&step=5",
        }
    )


async def on_startup(app):
    app["poller"] = asyncio.create_task(
        polling_task(app)
    )


async def on_cleanup(app):
    task = app.get("poller")

    if task:
        task.cancel()

        try:
            await task

        except asyncio.CancelledError:
            pass


app = web.Application()

app.router.add_get(
    "/",
    root_handler
)

app.router.add_get(
    "/status",
    status_handler
)

app.router.add_get(
    "/loxone",
    loxone_handler
)

app.router.add_get(
    "/health",
    health_handler
)

app.router.add_get(
    "/history/dhw",
    dhw_history_handler
)

app.router.add_get(
    "/set/dhw_temp",
    set_dhw_temp
)

app.router.add_get(
    "/set/dhw_mode",
    set_dhw_mode
)

app.router.add_get(
    "/set/extra_dhw",
    set_extra_dhw
)

app.router.add_get(
    "/set/hc1_mode",
    set_hc1_mode
)

app.on_startup.append(
    on_startup
)

app.on_cleanup.append(
    on_cleanup
)


if __name__ == "__main__":
    web.run_app(
        app,
        host=LISTEN_HOST,
        port=LISTEN_PORT,
        access_log=None
    )
