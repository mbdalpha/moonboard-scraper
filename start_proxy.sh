#!/usr/bin/env bash
# Bring up mitmproxy in WireGuard mode and print a phone-importable config + QR.
#
# Why WireGuard and not a plain HTTP proxy: the Moon app is Flutter, and its
# Dart networking ignores the iOS/Android system HTTP proxy. A plain proxy
# captures nothing. WireGuard routes the phone at the network layer (L3), so the
# app's direct connections are captured too.
#
# --allow-hosts 'ems-x\.com' means we only MITM the Moon backend; everything
# else (Apple App Attest, Firebase App Check) tunnels through untouched, so the
# real device still passes attestation natively.
set -euo pipefail
cd "$(dirname "$0")"

WGCONF="$HOME/.mitmproxy/wireguard.conf"
OUT="data/moon-wg.conf"
mkdir -p data

# 1. firewall warning (NixOS blocks inbound UDP 51820 by default)
if command -v systemctl >/dev/null && systemctl is-active --quiet firewall 2>/dev/null; then
  echo "!! Your firewall is active. The phone won't reach the proxy until UDP 51820"
  echo "!! is open. Simplest: 'sudo systemctl stop firewall' (re-enable with start)."
  echo
fi

# 2. start mitmdump (WireGuard mode) if not already running
if ss -ulnp 2>/dev/null | grep -q ':51820'; then
  echo "mitmproxy already listening on UDP 51820."
else
  echo "Starting mitmproxy (WireGuard mode)..."
  nix-shell -p mitmproxy --run \
    "mitmdump --mode wireguard -s capture_addon.py --set block_global=false --allow-hosts 'ems-x\.com'" \
    > data/wg.log 2>&1 &
  disown || true
  for _ in $(seq 1 20); do
    [ -f "$WGCONF" ] && ss -ulnp 2>/dev/null | grep -q ':51820' && break
    sleep 1
  done
fi

# 3. build the phone client config from mitmproxy's generated keys
[ -f "$WGCONF" ] || { echo "mitmproxy didn't create $WGCONF — check data/wg.log"; exit 1; }
srv_priv=$(python3 -c "import json;print(json.load(open('$WGCONF'))['server_key'])")
cli_priv=$(python3 -c "import json;print(json.load(open('$WGCONF'))['client_key'])")
srv_pub=$(nix-shell -p wireguard-tools --run "echo '$srv_priv' | wg pubkey")
lan_ip=$(ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \K[0-9.]+' | head -1)

cat > "$OUT" <<EOF
[Interface]
PrivateKey = $cli_priv
Address = 10.0.0.1/32
DNS = 10.0.0.53

[Peer]
PublicKey = $srv_pub
AllowedIPs = 0.0.0.0/0
Endpoint = ${lan_ip:-<THIS_MACHINE_LAN_IP>}:51820
EOF

nix-shell -p qrencode --run "qrencode -o data/moon-wg-qr.png -s 8 -m 2 < $OUT" 2>/dev/null || true

echo
echo "WireGuard config written to $OUT  (Endpoint ${lan_ip:-?}:51820)"
echo "Scan this from the WireGuard app (+ -> Create from QR code):"
echo
nix-shell -p qrencode --run "qrencode -t ANSIUTF8 < $OUT" 2>/dev/null || cat "$OUT"
echo
echo "Then: install+trust the cert (http://mitm.it), toggle the tunnel ON,"
echo "open the Moon app, and run ./capture_and_fetch.sh"
