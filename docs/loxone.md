# Loxone-Einbindung

## Lesen

Für die normale Visualisierung sollte Loxone den kompakten Endpunkt verwenden:

```text
http://<DIETPI-IP>:8095/loxone
```

Der ausführliche `/status`-Endpunkt ist für Diagnose und Entwicklung gedacht.

Ein Polling-Intervall von etwa 30–60 Sekunden ist für die meisten Heizungswerte sinnvoll.

## Zustandsbewertung

Nicht nur einzelne Temperaturen auswerten. Für die Kommunikationsqualität sind insbesondere relevant:

- `bridge_ok`
- `gateway_online`
- `poll_errors`
- `age_s`

Damit lässt sich unterscheiden zwischen:

1. Bridge-Prozess ausgefallen,
2. Bridge läuft, KM200 aber nicht erreichbar,
3. Daten vorhanden, aber veraltet,
4. normalem Betrieb.

## Schreiben

Schreibbefehle sollten nur aus bewusst aufgebauten Loxone-Logiken kommen. Die Bridge begrenzt Writes zusätzlich auf `write_client_ip`.

Nach Möglichkeit keine dauernden Sollwert-Wiederholungen senden. Nur bei einer tatsächlichen Zustandsänderung schreiben.

## Extra-Warmwasser

Ein typisches Konzept ist:

- normale WW-Solltemperatur separat belassen,
- Extra-Warmwasser Stopptemperatur konfigurieren,
- Extra-Warmwasser nur für eine definierte Dauer aktivieren,
- danach automatisch wieder auf Dauer 0 zurückkehren lassen.

Die konkreten Temperaturen und Laufzeiten müssen zur jeweiligen Anlage passen.
