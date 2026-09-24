# Loxone Buderus KM200 Bridge

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python 3](https://img.shields.io/badge/Python-3.x-blue.svg)
![Platform](https://img.shields.io/badge/Linux-DietPi%20%2F%20Debian-informational.svg)
![Write model](https://img.shields.io/badge/Writes-readback%20verified-success.svg)

<!-- project-meta -->
> **Status:** Stable · **Current release:** `v1.0.0` · **License:** MIT · **Documentation:** English · **Issues/PRs:** English preferred

[Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [Loxone integration](docs/loxone.md) · [Troubleshooting](docs/troubleshooting.md) · [Project collection](https://github.com/therealb4n4na/loxone-smart-home-projects)
<!-- /project-meta -->

A local Python bridge between a Buderus/Bosch KM200 gateway and Loxone. It periodically reads selected heating and domestic-hot-water values, exposes them through a compact HTTP API, and deliberately supports only a limited set of verified write operations.

## What this project gives you

- read KM200 data locally
- simplify selected values for Loxone
- restrict write access to explicitly supported functions
- verify every supported write by reading the target value back
- distinguish bridge failure from gateway failure
- optionally store selected values in a local history database

## Architecture

```text
Buderus heating system / KM200
        │
        │ encrypted KM200 communication
        ▼
bridge.py :8095
  ├─ periodic polling
  ├─ state cache
  ├─ compact Loxone output
  ├─ controlled writes
  └─ history API
        │
        ├────────────> Loxone
        │
        └─ logger.py -> SQLite history
```

This project is independent of any separate Rego1000/CAN reverse-engineering work. The KM200 bridge communicates only through the network gateway.

## Tested hardware

This project is developed and operated with a **Buderus/Bosch KM200 network gateway** connected to a real heating installation.

The KM200 resource tree depends on the connected controller, system configuration, and firmware. The project therefore exposes only resources and write operations that were explicitly verified instead of assuming that every KM200 installation provides the same endpoints.

## Requirements

- Linux; developed and tested on DietPi / Debian
- Python 3
- a KM200 reachable on the local network
- the KM200 private key/token and associated password
- optional Loxone Miniserver

## Configuration

The production configuration is stored outside the repository, for example:

```text
/etc/buderus-km200.json
```

Template: [`config.example.json`](config.example.json)

Example structure:

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

Never publish the real configuration file.

## Currently used data points

The bridge reads values such as:

- gateway time
- outdoor temperature
- actual domestic-hot-water temperature
- DHW target temperature
- DHW operating mode/program
- extra-DHW stop temperature
- extra-DHW duration
- heating-circuit 1 operating mode and selected setpoints

Available resources depend on the heating controller, system configuration, and firmware.

## HTTP API

### Full bridge status

```text
GET http://<HOST>:8095/status
```

### Compact Loxone output

```text
GET http://<HOST>:8095/loxone
```

### Health

```text
GET http://<HOST>:8095/health
```

A running Python process is not the same as a reachable KM200. The bridge therefore exposes separate indicators such as `bridge_ok`, `gateway_online`, `poll_errors`, and `age_s`.

### History

```text
GET http://<HOST>:8095/history/dhw?hours=72&step=5
```

History data is written by the separate `logger.py` process to SQLite and exposed read-only through the bridge.

## Write operations

The bridge intentionally supports only defined, tested write paths, including selected operations for:

- DHW target temperature
- DHW operating mode
- extra DHW
- heating-circuit 1 operating mode

Write requests are restricted to the configured `write_client_ip`. After a PUT, the bridge reads the target resource again. The command is considered successful only when the requested and actual values match.

## Why verify writes?

For heating controls, an HTTP success response alone is not sufficient proof that a value was actually accepted. A gateway may accept a request while the underlying controller rejects or normalizes the value. Readback verification makes that distinction visible.

## History logger

`logger.py` periodically reads the bridge's local `/status` endpoint and stores snapshots in SQLite.

The generic public logger does not require an external temperature sensor. Existing database columns from older installations may remain for compatibility without being populated.

## systemd

A typical installation uses two long-running units:

```text
buderus-km200-bridge.service
buderus-km200-logger.service
```

The logger should start after the bridge, but it should also tolerate the local bridge endpoint being temporarily unavailable after boot.

## Loxone

For visualization, Loxone should normally use `/loxone`. Send write commands only through explicitly supported endpoints.

See [`docs/loxone.md`](docs/loxone.md).

## Troubleshooting

See [`docs/troubleshooting.md`](docs/troubleshooting.md).

## Safety notice

This project can modify heating-system setpoints. Verify resources and allowed values on your own installation before enabling writes. Do not bypass safety functions implemented by the heating controller. Use at your own risk.

## License

MIT License – see [`LICENSE`](LICENSE).
