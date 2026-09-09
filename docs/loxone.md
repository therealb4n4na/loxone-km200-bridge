# Loxone integration

## Reading values

For normal visualization, use the compact endpoint:

```text
http://<DIETPI-IP>:8095/loxone
```

The full `/status` endpoint is intended mainly for diagnostics and development.

A polling interval of roughly 30–60 seconds is reasonable for most heating values.

## Evaluating communication health

Do not evaluate individual temperatures alone. Important communication indicators include:

- `bridge_ok`
- `gateway_online`
- `poll_errors`
- `age_s`

Together they let you distinguish between:

1. the bridge process being unavailable,
2. the bridge running while the KM200 is unreachable,
3. data being present but stale,
4. normal operation.

## Writing values

Write requests should only originate from deliberate Loxone logic. The bridge additionally restricts writes to `write_client_ip`.

Avoid continuously re-sending the same setpoint. Write only when the requested state actually changes.

## Extra DHW

A typical control concept is to:

- keep the normal DHW setpoint separate,
- configure an extra-DHW stop temperature,
- enable extra DHW for a defined duration only,
- return the duration to 0 afterwards.

Exact temperatures and durations must be chosen for the specific heating system.
