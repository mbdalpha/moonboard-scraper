# moonboard-2024-fetcher

Pull the **complete MoonBoard 2024** problem catalog into local JSON, and
convert it for [moonlink-pwa](https://github.com/mbdalpha/moonlink-pwa) so you
can light problems on a physical LED board.

> **Why this is more involved than a normal scraper.** Most MoonBoard scrapers
> hit `moonboard.com`. That website is being retired and **no longer serves
> 2024-board data**. The data now lives only inside the **Moon Climbing mobile
> app**, which talks to a Bubble.io backend (`grn-climbing.ems-x.com`) protected
> by **Apple App Attest / Firebase App Check** device attestation. You can't mint
> those attestation tokens from a script — they're cryptographically bound to a
> genuine device. So instead of faking attestation, this tool **borrows a real
> phone's already-attested session**: you intercept one authenticated request
> from the app, then replay its sync endpoint to page through the whole catalog.
>
> Full reverse-engineering writeup: [`APP_API_NOTES.md`](APP_API_NOTES.md).

---

## Table of contents
1. [What you need](#1-what-you-need)
2. [The big picture](#2-the-big-picture)
3. [One-time setup](#3-one-time-setup)
4. [Step A — start the intercepting proxy](#step-a--start-the-intercepting-proxy)
5. [Step B — point your phone at it (VPN + cert)](#step-b--point-your-phone-at-it-vpn--cert)
6. [Step C — capture a request and fetch everything](#step-c--capture-a-request-and-fetch-everything)
7. [Step D — convert for moonlink-pwa](#step-d--convert-for-moonlink-pwa)
8. [Step E — use it in moonlink-pwa](#step-e--use-it-in-moonlink-pwa)
9. [Running it again later](#running-it-again-later)
10. [Troubleshooting](#troubleshooting)
11. [File reference](#file-reference)
12. [Legal](#legal)

---

## 1. What you need

- A **MoonBoard account** and the **Moon Climbing app** installed on a **real
  phone** (iPhone or Android). A real device is important — it passes Apple/Google
  attestation natively. Emulators generally do **not** (that was a dead end; see
  `APP_API_NOTES.md`). This guide is written for **iPhone**; Android is the same
  idea with a different cert-install UI.
- A **computer on the same Wi-Fi network** as the phone. The phone will route its
  traffic through this computer.
- **`nix`** (used to run `mitmproxy`, `wireguard-tools`, `qrencode` without
  installing them globally) and **`python3`** (standard library only — no pip
  installs needed for the fetch/convert).
- The free **WireGuard** app on the phone (App Store / Play Store). On iPhone
  you'll also want the **Bluefy** browser later for the LED-board step, because
  Safari has no Web Bluetooth.

This was developed on NixOS; the scripts assume `nix-shell` is available. On
other distros, install `mitmproxy`, `wireguard-tools`, and `qrencode` however you
like and adjust the two `nix-shell` wrappers (`start_proxy.sh`, `run.sh`).

## 2. The big picture

```
  [ Moon app on your phone ]
            |  (all traffic, via a WireGuard VPN)
            v
  [ mitmproxy on your computer ]  --MITM only ems-x.com, tunnel everything else-->  internet
            |  writes decrypted request (with auth headers) to
            v
  data/captured_requests.jsonl  ->  data/auth_headers.json
            |  replayed by
            v
  fetch_problems.py  ->  data/moonboard2024_40.json  ->  to_moonlink.py  ->  *_moonlink.json
```

Two non-obvious things make this work, and both bit us:

- **A plain HTTP proxy captures nothing.** The app is built with Flutter, and
  Flutter's networking **ignores the phone's system HTTP-proxy setting**. So we
  use mitmproxy's **WireGuard mode**, which captures at the network layer (L3) —
  proxy-ignoring apps included.
- **We must NOT intercept the attestation traffic.** If mitmproxy tries to MITM
  Apple App Attest / Firebase App Check, those pinned handshakes break and the
  app hangs forever on "please wait" before it ever calls its own backend. So we
  pass `--allow-hosts 'ems-x\.com'`: only the Moon backend is decrypted;
  Apple/Firebase tunnel straight through and the real phone passes them normally.

## 3. One-time setup

```bash
git clone <your-repo-url> moonboard-2024-fetcher
cd moonboard-2024-fetcher
chmod +x *.sh
```

`credentials.json` is **only** needed by the legacy website scraper
(`pull_moonboard.py`), which no longer returns 2024 data — you can ignore it for
the app-based flow. If you do want it: `cp credentials.example.json
credentials.json` and fill it in. It is git-ignored.

## Step A — start the intercepting proxy

```bash
./start_proxy.sh
```

This script:
1. Warns if your **firewall** is active (on NixOS the default firewall blocks
   inbound **UDP 51820**, which WireGuard needs — the phone will show "no
   connection" until it's open). Simplest fix:
   ```bash
   sudo systemctl stop firewall      # re-enable later with: sudo systemctl start firewall
   ```
2. Starts `mitmdump --mode wireguard -s capture_addon.py --allow-hosts 'ems-x\.com'`
   in the background (logs to `data/wg.log`).
3. Derives a phone-importable WireGuard config from mitmproxy's keys, fills in
   **this machine's LAN IP** as the endpoint, writes it to `data/moon-wg.conf`,
   and prints a **QR code** in the terminal (also saved to `data/moon-wg-qr.png`).

Leave this running. To stop the proxy later: `pkill -f mitmdump`.

## Step B — point your phone at it (VPN + cert)

On the **phone**, two parts — both required:

**B1. Import and enable the WireGuard tunnel**
1. Install the **WireGuard** app.
2. **+** → **Create from QR code** → scan the QR from Step A (or AirDrop/copy
   `data/moon-wg.conf` and use **Create from file**).
3. Toggle the tunnel **ON**. Approve the iOS VPN prompt. You'll see a small `VPN`
   badge in the status bar.

**B2. Install AND trust the mitmproxy CA certificate** (so HTTPS can be
decrypted). This is the step everyone half-finishes:
1. In **Safari**, open **`http://mitm.it`** → tap the **Apple / iOS** download →
   Allow.
2. Settings → General → **VPN & Device Management** → tap the **mitmproxy**
   profile → **Install** (enter passcode).
3. **Turn on full trust** (without this, iOS installs the cert but still rejects
   it): Settings → General → **About** → scroll to the very bottom →
   **Certificate Trust Settings** → toggle **ON** next to **mitmproxy**.

> Apple system services like `gateway.icloud.com` are certificate-pinned and will
> keep failing in `data/wg.log` even after this. That's normal and harmless — we
> only care about `ems-x.com`.

## Step C — capture a request and fetch everything

The auth tokens (a bearer JWT + a Firebase App Check token) **expire within
minutes**, so capturing and fetching happen back-to-back in one script:

```bash
./capture_and_fetch.sh
```

It prints "Waiting for a fresh request…". Now, on the phone, **open the Moon app
and load the MoonBoard 2024 / 40° problem list** (pull-to-refresh; log out/in if
nothing happens). The script:
1. Watches `data/captured_requests.jsonl` for a fresh `ems-x.com` request.
2. Extracts its auth headers to `data/auth_headers.json`.
3. Immediately runs `fetch_problems.py`, which replays the sync endpoint
   ```
   GET /_bs_api/v1/problems/get/21/0/{maxDateInserted}/{maxDateUpdated}/{maxDateDeleted}?api-version=3.0
   ```
   (board `21` = MoonBoard 2024) starting from the year 2000 and advancing all
   three sync watermarks. The server caps each response at 25,000 rows, so it
   pages until a response is under the cap and adds no new problem ids — about
   **3 calls** for the full catalog.

Expected output:
```
  page 1: 25000 rows (25000 new), total unique 25000
  page 2: 10777 rows (10777 new), total unique 35777
  page 3: 5 rows (0 new), total unique 35777

Total 2024 problems:        35777
  at 40°:                   35773  -> data/moonboard2024_40.json
  at 40° benchmarks:        411    -> data/moonboard2024_40_benchmarks.json
  at 25°:                   35233
```

Outputs (all git-ignored):
- `data/moon2024_all.json` — every 2024 problem (both angles)
- `data/moonboard2024_40.json` — all 40° problems
- `data/moonboard2024_40_benchmarks.json` — 40° benchmarks only

## Step D — convert for moonlink-pwa

Our `moves` are stored as a packed string (`"s~D5~|l~G11~|e~J18~"`); moonlink-pwa
expects an array of `{Description, IsStart, IsEnd}` objects. Reshape it:

```bash
python3 to_moonlink.py
```

Produces:
- `data/moonboard2024_40_moonlink.json` — all 35,773 40° problems
- `data/moonboard2024_40_benchmarks_moonlink.json` — the 411 benchmarks

## Step E — use it in moonlink-pwa

1. Open moonlink-pwa over **HTTPS or as a local file** (not inside an app
   preview). Web Bluetooth requires **Chrome/Edge** on desktop or Android; on
   **iPhone use the Bluefy browser** (Safari can't do Web Bluetooth).
2. Use its **Import problems file** button and select one of the
   `*_moonlink.json` files.
   - Start with the **benchmarks** file (~290 KB) — it loads instantly and is
     what you'll usually want on the board.
   - The full file (~25 MB / 35k problems) works but is heavy on a phone (it
     renders the first 200 matches and filters in memory).
3. Filter by grade / benchmark / search, pick a problem, connect to your board,
   and it lights up over Bluetooth.

## Running it again later

The catalog grows as people set new problems. To refresh:

```bash
./start_proxy.sh            # if the proxy isn't still running
# phone: toggle the WireGuard tunnel ON, make sure the cert is still trusted
./capture_and_fetch.sh      # load the 2024/40 list in the app when prompted
python3 to_moonlink.py
```

When you're done, on the phone toggle the WireGuard tunnel **OFF** (you can leave
the tunnel + cert installed for next time, or remove them under VPN & Device
Management). On the computer: `pkill -f mitmdump`, and re-enable your firewall if
you stopped it (`sudo systemctl start firewall`).

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Phone says "no internet" the moment the VPN/proxy is on | Firewall blocking UDP 51820. `sudo systemctl stop firewall` (or open the port). |
| `http://mitm.it` won't load | Tunnel not ON, or you're using a plain HTTP proxy that's blocked. Make sure the WireGuard tunnel is connected. |
| Every site fails with "certificate unknown" in `data/wg.log` | Cert not trusted yet — finish **B2 step 3** (Certificate Trust Settings). |
| App hangs forever on "please wait" | The proxy is intercepting attestation. Confirm you started via `start_proxy.sh` (it sets `--allow-hosts 'ems-x\.com'`). Without that, Apple/Firebase handshakes break. |
| App works but `data/captured_requests.jsonl` stays empty | You're on a plain **HTTP proxy**, which Flutter ignores. You must use **WireGuard mode** (`start_proxy.sh`), not a Wi-Fi proxy. Turn the Wi-Fi proxy **Off**. |
| `fetch_problems.py` exits `HTTP 401`/`403` | Tokens expired. Just re-run `./capture_and_fetch.sh` and reload the app — capture and fetch must happen within a couple of minutes. |
| `gateway.icloud.com` handshake failures spamming the log | Normal. Apple pins those; we don't intercept them. Ignore. |

## File reference

| File | Purpose |
|---|---|
| `start_proxy.sh` | starts mitmproxy in WireGuard mode; prints the phone config + QR |
| `capture_addon.py` | mitmproxy addon that logs `ems-x.com` traffic to `data/captured_requests.jsonl` |
| `capture_and_fetch.sh` | waits for a fresh captured request, extracts its headers, runs the fetch |
| `fetch_problems.py` | replays the app's sync API and pages the full catalog |
| `to_moonlink.py` | converts the dataset into moonlink-pwa's import schema |
| `pull_moonboard.py` | legacy `moonboard.com` website scraper (kept for reference; no longer returns 2024 data) |
| `run.sh` | `nix-shell` wrapper for `pull_moonboard.py` |
| `APP_API_NOTES.md` | the reverse-engineered backend, endpoints, and auth flow |
| `credentials.example.json` | template for the legacy website scraper only |

## Legal

For personal use with your own MoonBoard account. Respect Moon Climbing's Terms
of Service. Don't redistribute the scraped problem database — share the code and
let people pull their own (that's why the `data/` outputs are git-ignored).
