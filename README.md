# Loxone Buderus KM200 Bridge

<!-- project-meta -->
> **Status:** Stable · **Current release:** `v1.0.0` · **License:** MIT · **Documentation:** Deutsch · **Issues/PRs:** Deutsch or English

[Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [Loxone-Doku](docs/loxone.md) · [Troubleshooting](docs/troubleshooting.md) · [Project collection](https://github.com/therealb4n4na/loxone-smart-home-projects)
<!-- /project-meta -->

Lokale Python-Bridge zwischen einem Buderus/Bosch KM200 Gateway und Loxone. Die Bridge liest ausgewählte Heizungs- und Warmwasserwerte zyklisch aus, stellt sie über HTTP bereit und erlaubt bewusst nur wenige, verifizierte Schreiboperationen.

## Ziele

- KM200 lokal auslesen
- Daten für Loxone vereinfachen
- Schreibzugriffe auf klar definierte Funktionen beschränken
- jeden Schreibbefehl durch Rücklesen verifizieren
- Gateway-Ausfall und Bridge-Ausfall getrennt darstellen
- ausgewählte Werte lokal historisieren

## Architektur

```text
Buderus WPS / KM200
        │
        │ verschlüsselte KM200-Kommunikation
        ▼
bridge.py :8095
  ├─ zyklischer Poll
  ├─ Cache
  ├─ Loxone-Ausgabe
  ├─ kontrollierte Writes
  └─ History-API
        │
        ├────────────> Loxone
        │
        └─ logger.py -> SQLite-History
```

Dieses Projekt ist vom separaten Rego1000/CAN-Projekt unabhängig. Die KM200-Bridge verwendet ausschließlich das Netzwerk-Gateway.

## Voraussetzungen

- Linux, getestet auf DietPi/Debian
- Python 3
- ein im LAN erreichbares KM200
- KM200 private key/token und das zugehörige Passwort
- optional Loxone Miniserver

## Konfiguration

Die produktive Konfiguration liegt außerhalb des Repositorys unter:

```text
/etc/buderus-km200.json
```

Vorlage: [`config.example.json`](config.example.json)

Beispielstruktur:

```json
{
  "host": "192.168.x.x",
  "token": "YOUR_KM200_TOKEN",
  "password": "YOUR_KM200_PASSWORD",
  "listen_host": "0.0.0.0",
  "listen_port": 8095,
  "poll_interval": 30,
  "write_client_ip": "192.168.x.x"
}
```

Die echte Datei darf nicht veröffentlicht werden.

## Aktuell genutzte Datenpunkte

Die Bridge liest unter anderem:

- Gateway-Zeit
- Außentemperatur
- Warmwasser Ist-Temperatur
- Warmwasser Soll-Temperatur
- Warmwasser-Betriebsart/Programm
- Extra-Warmwasser Stopptemperatur
- Extra-Warmwasser Dauer
- Heizkreis 1 Betriebsart und ausgewählte Sollwerte

Welche Endpunkte auf einem konkreten Buderus-System existieren, hängt von Regler, Anlage und Firmware ab.

## HTTP-API

### Vollständiger Bridge-Status

```text
GET http://<HOST>:8095/status
```

### Kompakte Loxone-Ausgabe

```text
GET http://<HOST>:8095/loxone
```

### Health

```text
GET http://<HOST>:8095/health
```

Wichtig: Ein laufender Python-Prozess ist nicht dasselbe wie ein erreichbares KM200. Deshalb enthält die Bridge getrennte Informationen wie `bridge_ok`, `gateway_online`, `poll_errors` und `age_s`.

### History

```text
GET http://<HOST>:8095/history/dhw?hours=72&step=5
```

Die History wird vom separaten `logger.py` in SQLite geschrieben und über die Bridge lesbar gemacht.

## Schreiboperationen

Die Bridge unterstützt bewusst nur definierte, getestete Schreibpfade, darunter:

- Warmwasser-Solltemperatur
- Warmwasser-Betriebsart
- Extra-Warmwasser
- Heizkreis-1-Betriebsart

Schreibzugriffe werden auf die konfigurierte `write_client_ip` begrenzt. Nach einem PUT liest die Bridge den Zielwert erneut ein. Erst wenn Soll und Ist zusammenpassen, gilt der Befehl als bestätigt.

## Warum Schreibverifikation?

Bei Heizungssteuerungen ist ein HTTP-Erfolg allein nicht ausreichend. Ein Gateway kann einen Request entgegennehmen, obwohl ein Wert nicht wie erwartet übernommen wurde. Deshalb folgt auf jeden vorgesehenen Write ein Readback.

## History Logger

`logger.py` fragt zyklisch den lokalen `/status`-Endpunkt ab und speichert Snapshots in SQLite.

Der früher in diesem privaten Setup verwendete DS18B20-Zirkulationssensor ist im aktuellen Logger bewusst deaktiviert. Die historische Datenbankspalte bleibt aus Kompatibilitätsgründen bestehen.

## systemd

Typisch sind zwei dauerhafte Units:

```text
buderus-km200-bridge.service
buderus-km200-logger.service
```

Der Logger sollte nach der Bridge starten, darf aber auch einen kurzfristig noch nicht erreichbaren lokalen Endpunkt überleben.

## Loxone

Loxone sollte für die Visualisierung bevorzugt `/loxone` verwenden. Schreibbefehle nur gezielt über die dafür vorgesehenen Endpunkte senden.

Mehr dazu: [`docs/loxone.md`](docs/loxone.md).

## Fehlersuche

Siehe [`docs/troubleshooting.md`](docs/troubleshooting.md).

## Sicherheits- und Haftungshinweis

Dieses Projekt kann Sollwerte einer Heizungsanlage verändern. Vor Verwendung müssen Endpunkte und Werte am eigenen System geprüft werden. Sicherheitsfunktionen des Heizungsreglers dürfen nicht umgangen werden. Änderungen erfolgen auf eigenes Risiko.

## Lizenz

MIT License – siehe [`LICENSE`](LICENSE).
