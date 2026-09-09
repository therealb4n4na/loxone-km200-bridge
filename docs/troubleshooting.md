# Fehlersuche

## Bridge läuft, Gateway offline

```bash
curl -sS http://127.0.0.1:8095/health
curl -sS http://127.0.0.1:8095/status
```

Wenn der HTTP-Dienst antwortet, aber `gateway_online=false` ist, funktioniert die lokale Bridge grundsätzlich. Dann Netzwerk, KM200-Stromversorgung, VLAN/Firewall und Erreichbarkeit des Gateways prüfen.

## Bridge selbst nicht erreichbar

```bash
systemctl status buderus-km200-bridge.service
journalctl -u buderus-km200-bridge.service -n 100 --no-pager
ss -lntp | grep 8095
```

## Logger prüfen

```bash
systemctl status buderus-km200-logger.service
journalctl -u buderus-km200-logger.service -n 100 --no-pager
curl -sS 'http://127.0.0.1:8095/history/dhw?hours=1&step=5'
```

Ein kurzer `Connection refused` direkt nach einem gemeinsamen Boot kann entstehen, wenn der Logger schneller startet als die Bridge. Er sollte beim nächsten 60-s-Zyklus selbständig weiterarbeiten.

## Write wird mit 403 abgewiesen

Die Client-IP stimmt nicht mit `write_client_ip` überein. Das ist eine Sicherheitsfunktion und sollte nicht durch generelles Öffnen des Ports umgangen werden.

## Write wird nicht bestätigt

Der Request wurde möglicherweise vom Gateway angenommen, aber der gewünschte Wert nicht übernommen. In diesem Fall die konkrete KM200-Ressource, zulässigen Werte und den Zustand der Heizungsanlage prüfen.

## Nach Codeänderungen

```bash
python3 -m py_compile bridge.py logger.py
sudo systemctl restart buderus-km200-bridge.service
sudo systemctl restart buderus-km200-logger.service
```

Danach immer `/health`, `/status` und mindestens einen History-Aufruf kontrollieren.
