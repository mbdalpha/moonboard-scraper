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
4. [Choosing what to download — config.json](#4-choosing-what-to-download--configjson)
5. [Step A — start the intercepting proxy](#step-a--start-the-intercepting-proxy)
6. [Step B — point your phone at it (VPN + cert)](#step-b--point-your-phone-at-it-vpn--cert)
7. [Step C — capture a request and fetch everything](#step-c--capture-a-request-and-fetch-everything)
8. [Step D — convert for moonlink-pwa](#step-d--convert-for-moonlink-pwa)
9. [Step E — use it in moonlink-pwa](#step-e--use-it-in-moonlink-pwa)
10. [Running it again later](#running-it-again-later)
11. [Troubleshooting](#troubleshooting)
12. [File reference](#file-reference)
13. [Legal](#legal)

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

## 4. Choosing what to download — config.json

`config.json` controls which part of the catalog `fetch_problems.py` downloads
and which subsets it (and `to_moonlink.py`) write to disk. The checked-in
default reproduces the classic behaviour — MoonBoard 2024 at 40°, plus a
benchmarks file:

```json
{
  "boards": [
    { "id": 21, "name": "MoonBoard 2024", "angles": ["40°"] }
  ],
  "benchmarks_only": false,
  "min_grade": null,
  "max_grade": null,
  "setter": null,
  "output_dir": "data",
  "write_benchmark_files": true,
  "moonlink_pwa_dir": null
}
```

| Key | Meaning |
|---|---|
| `boards` | Which boards to download. `id` is the `{board}` segment of the app's sync URL (`/problems/get/{board}/...`). Confirmed ids (probed live 2026-06-11): **15** = MoonBoard 2017 (25°/40°), **17** = MoonBoard 2019 (25°/40°), **19** = MoonBoard Mini 2020 (40°), **21** = MoonBoard 2024 (25°/40°), **22** = MoonBoard Mini 2024 (40°). Ids 16, 18, 20, 23–25 return empty catalogs — the 2016 board is not in the app backend at all. `angles` picks which wall angles get their own output files — a list like `["40°", "25°"]` (plain `"40"` works too) or `"all"` for every angle found in the data. |
| `benchmarks_only` | `true` → only benchmark problems are written. |
| `min_grade` / `max_grade` | Inclusive Font-grade range, e.g. `"6B+"` … `"7C"`. |
| `setter` | Only problems whose setter name contains this string (case-insensitive), e.g. `"Ben Moon"`. |
| `output_dir` | Where dataset files are written (relative to the repo). |
| `write_benchmark_files` | Also write a `*_benchmarks` subset next to each full per-angle file. |
| `moonlink_pwa_dir` | If set to a [moonlink-pwa](https://github.com/mbdalpha/moonlink-pwa) checkout, `to_moonlink.py` also merges everything it converted into one compact `problems.json` there. Serve the PWA from that directory and it auto-loads the library on startup — no drag-and-drop needed. |

Note the sync API always returns a board's **complete catalog** in one go, so
`boards` is what controls the actual download; the other keys filter what gets
written. Output names are derived from the board name and angle:
`data/moonboard2024_all.json` (raw catalog), `data/moonboard2024_40.json`,
`data/moonboard2024_40_benchmarks.json`, and after Step D the matching
`*_moonlink.json` files.

Example — everything on both 2024 angles, no extra benchmark files:

```json
{ "boards": [{ "id": 21, "name": "MoonBoard 2024", "angles": "all" }],
  "write_benchmark_files": false }
```

Example — just the 40° benchmarks from 7A up:

```json
{ "boards": [{ "id": 21, "name": "MoonBoard 2024", "angles": ["40°"] }],
  "benchmarks_only": true, "min_grade": "7A" }
```

If `config.json` is missing, the defaults above are used.

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
   GET /_bs_api/v1/problems/get/{board}/0/{maxDateInserted}/{maxDateUpdated}/{maxDateDeleted}?api-version=3.0
   ```
   for each board in `config.json` (board `21` = MoonBoard 2024) starting from
   the year 2000 and advancing all three sync watermarks. The server caps each
   response at 25,000 rows, so it pages until a response is under the cap and
   adds no new problem ids — about **3 calls** for the full catalog.

Expected output (with the default config):
```
Fetching full MoonBoard 2024 catalog (board id 21)...
  page 1: 25000 rows (25000 new), total unique 25000
  page 2: 10777 rows (10777 new), total unique 35777
  page 3: 5 rows (0 new), total unique 35777

Total MoonBoard 2024 problems: 35777  -> data/moonboard2024_all.json
  at 40°:                 35773  -> data/moonboard2024_40.json
  at 40° benchmarks:      411  -> data/moonboard2024_40_benchmarks.json
```

Outputs (all git-ignored; names derive from the config's board name + angles):
- `data/moonboard2024_all.json` — every problem on the board, unfiltered (both angles)
- `data/moonboard2024_40.json` — 40° problems, after the config's filters
- `data/moonboard2024_40_benchmarks.json` — 40° benchmarks only

## Step D — convert for moonlink-pwa

Our `moves` are stored as a packed string (`"s~D5~|l~G11~|e~J18~"`); moonlink-pwa
expects an array of `{Description, IsStart, IsEnd}` objects. Reshape it:

```bash
python3 to_moonlink.py
```

It converts whatever boards/angles `config.json` selected. With the default
config it produces:
- `data/moonboard2024_40_moonlink.json` — all 35,773 40° problems
- `data/moonboard2024_40_benchmarks_moonlink.json` — the 411 benchmarks

If `moonlink_pwa_dir` is set, it additionally writes a combined compact
`problems.json` (all configured boards/angles in one file, ~5 MB instead of
~25 MB for the full 2024/40° catalog) straight into the PWA directory.

## Step E — use it in moonlink-pwa

The integrated way (recommended): set `"moonlink_pwa_dir"` in `config.json` to
your moonlink-pwa checkout, run `python3 to_moonlink.py`, then serve the PWA
from that directory (`python3 -m http.server` works — `localhost` counts as a
secure context for Web Bluetooth). The app finds `problems.json` next to it,
loads the whole library automatically, and keeps a copy in IndexedDB so it's
still there offline. Re-running Step D refreshes it on the next page load.

Optional eye candy: `python3 fetch_hold_layouts.py` (needs the same
headed-Chrome moonboard.com login as the legacy scraper) downloads each
configured board's **hold photos and layout** from the website's hold-setup
viewer into `<moonlink_pwa_dir>/holds/`. The PWA then draws the actual holds
under the LED grid — problems light up as rings around real holds — switching
layouts automatically per problem's board.

The standalone way: open moonlink-pwa anywhere (HTTPS or local file — Web
Bluetooth needs **Chrome/Edge** on desktop/Android; on **iPhone use the Bluefy
browser**) and drag any of the `*_moonlink.json` files onto its drop zone. The
PWA also understands the raw `data/*_40.json` scraper files in a pinch. A
dropped library is persisted on the device too.

Either way: filter by grade range / board / angle / benchmark / search, sort by
repeats, grade, rating, date or name, pick a problem (or hit **Random**),
connect to your board, and it lights up over Bluetooth.

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
| `config.json` | which boards/angles/subsets to download — see [section 4](#4-choosing-what-to-download--configjson) |
| `config.py` | loads + validates `config.json`; shared by the fetch and convert scripts |
| `fetch_problems.py` | replays the app's sync API and pages the full catalog (per `config.json`) |
| `to_moonlink.py` | converts the dataset into moonlink-pwa's import schema (per `config.json`); with `moonlink_pwa_dir` set, also writes the PWA's auto-loaded `problems.json` |
| `fetch_hold_layouts.py` | downloads per-hold photos + board layouts from moonboard.com into the PWA's `holds/` dir (hold-photo rendering) |
| `pull_moonboard.py` | legacy `moonboard.com` website scraper (kept for reference; no longer returns 2024 data) |
| `run.sh` | `nix-shell` wrapper for `pull_moonboard.py` |
| `APP_API_NOTES.md` | the reverse-engineered backend, endpoints, and auth flow |
| `credentials.example.json` | template for the legacy website scraper only |

## Legal

For personal use with your own MoonBoard account. Respect Moon Climbing's Terms
of Service. Don't redistribute the scraped problem database — share the code and
let people pull their own (that's why the `data/` outputs are git-ignored).
