#!/usr/bin/env bash
# Wait for a fresh ems-x request from the phone, extract its auth headers,
# then immediately run the full catalog fetch before the token expires.
cd "$(dirname "$0")"
CAP=data/captured_requests.jsonl

before=$(grep -c . "$CAP" 2>/dev/null || echo 0)
echo "Reload the 2024/40 list in the Moon app now. Waiting for a fresh request..."
for i in $(seq 1 60); do
  now=$(grep -c . "$CAP" 2>/dev/null || echo 0)
  if [ "$now" -gt "$before" ]; then
    echo "Fresh request captured. Extracting headers + fetching immediately..."
    python3 - <<'PY'
import json
recs=[json.loads(l) for l in open('data/captured_requests.jsonl')]
# newest ems-x request that carries an authorization header
for r in reversed(recs):
    h={k.lower():v for k,v in r['req_headers'].items()}
    if 'authorization' in h and 'ems-x' in r['url']:
        keep=('authorization','transfer-bid','transfer-purpose','transfer-ver',
              'transfer-osver','user-agent','accept-encoding')
        json.dump({k:h[k] for k in keep if k in h}, open('data/auth_headers.json','w'), indent=2)
        break
PY
    exec python3 fetch_problems.py
  fi
  sleep 1
done
echo "No fresh request seen in 60s — is the WireGuard tunnel toggled ON and the app reloading?"
