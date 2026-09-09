# Troubleshooting

## Bridge is running, gateway is offline

```bash
curl -sS http://127.0.0.1:8095/health
curl -sS http://127.0.0.1:8095/status
```

If the HTTP service responds but `gateway_online=false`, the local bridge itself is working. Check network connectivity, KM200 power, VLAN/firewall rules, and gateway reachability.

## Bridge itself is unreachable

```bash
systemctl status buderus-km200-bridge.service
journalctl -u buderus-km200-bridge.service -n 100 --no-pager
ss -lntp | grep 8095
```

## Check the logger

```bash
systemctl status buderus-km200-logger.service
journalctl -u buderus-km200-logger.service -n 100 --no-pager
curl -sS 'http://127.0.0.1:8095/history/dhw?hours=1&step=5'
```

A brief `Connection refused` immediately after boot can occur if the logger starts before the bridge is ready. It should recover on the next logging cycle.

## Write rejected with HTTP 403

The client IP does not match `write_client_ip`. This is a security feature and should not be worked around by exposing the complete service more broadly.

## Write is not confirmed

The gateway may have accepted the request while the controller did not apply the requested value. Check the exact KM200 resource, allowed values, and current operating state of the heating system.

## After code changes

```bash
python3 -m py_compile bridge.py logger.py
sudo systemctl restart buderus-km200-bridge.service
sudo systemctl restart buderus-km200-logger.service
```

Then verify `/health`, `/status`, and at least one history request.
