# moonboard-2024-fetcher

Pull the full MoonBoard 2024 problem catalog into local JSON and convert it for
[moonlink-pwa](https://github.com/mbdalpha/moonlink-pwa), which lights problems
on a physical LED board.

## Why this isn't a normal scraper

Most MoonBoard scrapers hit `moonboard.com`, but that site is being retired and
no longer serves 2024-board data. The data now lives only in the Moon Climbing
app, which talks to a Bubble.io backend (`grn-climbing.ems-x.com`) behind Apple
App Attest / Firebase App Check. Those attestation tokens are bound to a real
device and can't be minted from a script.

So this doesn't fake attestation — it borrows a real phone's session. You
intercept one authenticated request from the app, then replay its sync endpoint
to page through the whole catalog. Backend details are in
[`APP_API_NOTES.md`](APP_API_NOTES.md).

```
 Moon app on phone ──(all traffic, WireGuard VPN)──▶ mitmproxy on computer ──▶ internet
                                                          │ (MITM ems-x.com only)
                                                          ▼
                          captured_requests.jsonl ──▶ auth_headers.json
                                                          │ replayed by
                                                          ▼
                              fetch_problems.py ──▶ to_moonlink.py ──▶ moonlink-pwa
```

Two things that aren't obvious:

- **WireGuard mode, not an HTTP proxy.** The app is Flutter, and Flutter ignores
  the phone's system HTTP-proxy setting, so a normal proxy captures nothing.
  mitmproxy's WireGuard mode captures at the network layer instead.
- **Don't intercept attestation.** MITM'ing the Apple/Firebase handshakes breaks
  their pinning and the app hangs on "please wait". `--allow-hosts 'ems-x\.com'`
  decrypts only the Moon backend and tunnels everything else through untouched.

## What you need

- A MoonBoard account and the Moon Climbing app on a real phone (iPhone or
  Android — emulators fail attestation). The steps below are for iPhone; Android
  is the same with a different cert UI.
- A computer on the same Wi-Fi as the phone.
- `nix` (to run `mitmproxy`, `wireguard-tools`, `qrencode` without installing
  them) and `python3` (stdlib only). On non-NixOS, install those three yourself
  and adjust the `nix-shell` calls in `start_proxy.sh` / `run.sh`.
- The WireGuard app on the phone. For the LED-board step on iPhone you'll also
  need the Bluefy browser, since Safari has no Web Bluetooth.

## Setup

```bash
git clone <your-repo-url> moonboard-2024-fetcher
cd moonboard-2024-fetcher
chmod +x *.sh moonboard
```

## The `moonboard` CLI

One command drives the pipeline. The usual refresh is just `./moonboard fetch`.

| Command | Does |
|---|---|
| `./moonboard fetch` | start the proxy if needed, wait for a phone request, download, convert. `--no-convert` to skip convert, `--timeout SECS` to wait longer |
| `./moonboard proxy` | start the proxy and print the WireGuard QR |
| `./moonboard convert` | re-run only the conversion on already-downloaded data |
| `./moonboard holds` | download hold photos/layouts for the PWA (needs Chrome) |
| `./moonboard stop` | stop the proxy |
| `./moonboard status` | proxy / capture / dataset / PWA-link state |
| `./moonboard config` | print the active `config.json` |

The phone setup below is a one-time thing. After that, `./moonboard fetch` is the
whole loop. Every underlying script (`start_proxy.sh`, `fetch_problems.py`,
`to_moonlink.py`, `fetch_hold_layouts.py`) also runs on its own if you prefer.

## First run

### 1. Start the proxy

```bash
./moonboard proxy
```

This warns if your firewall is up (NixOS blocks inbound UDP 51820, which
WireGuard needs — `sudo systemctl stop firewall` to open it), starts mitmproxy
in WireGuard mode, and prints a QR for the phone config (also saved to
`data/moon-wg.conf` / `moon-wg-qr.png`).

### 2. Point the phone at it

Both parts are required:

**Tunnel.** In the WireGuard app: **+ → Create from QR code**, scan the QR (or
copy `data/moon-wg.conf` and use Create from file). Toggle it ON and approve the
VPN prompt.

**Certificate.** In Safari open `http://mitm.it`, download the iOS profile, then
Settings → General → VPN & Device Management → install the mitmproxy profile.
Then turn on full trust: Settings → General → About → bottom →
Certificate Trust Settings → toggle mitmproxy ON. Without full trust iOS keeps
rejecting the cert.

Apple services like `gateway.icloud.com` are pinned and will keep failing in
`data/wg.log`. That's fine; only `ems-x.com` matters.

### 3. Capture and fetch

The auth tokens expire within minutes, so capture and fetch run back-to-back:

```bash
./moonboard fetch
```

When it says it's waiting, open the Moon app and load the MoonBoard 2024 / 40°
problem list (pull to refresh; log out/in if nothing happens). It grabs the auth
headers from the captured request and replays the sync endpoint:

```
GET /_bs_api/v1/problems/get/{board}/0/{dateInserted}/{dateUpdated}/{dateDeleted}?api-version=3.0
```

It's a 3-watermark delta sync capped at 25,000 rows per call, so it pages from
2000 onward until a response is under the cap with no new ids — about 3 calls for
the full catalog:

```
Total MoonBoard 2024 problems: 35777  -> data/moonboard2024_all.json
  at 40°:                 35773  -> data/moonboard2024_40.json
  at 40° benchmarks:      411  -> data/moonboard2024_40_benchmarks.json
```

Then it converts to moonlink-pwa's schema (`data/*_moonlink.json`). Output names
follow the board name and angle from your config; all of `data/` is git-ignored.

## config.json

Controls which boards/angles get downloaded and which subsets get written. The
checked-in default is MoonBoard 2024 at 40° plus a benchmarks file:

```json
{
  "boards": [{ "id": 21, "name": "MoonBoard 2024", "angles": ["40°"] }],
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
| `boards` | `id` is the `{board}` in the sync URL. Known ids: 15 = 2017, 17 = 2019, 19 = Mini 2020, 21 = 2024, 22 = Mini 2024 (16/18/20/23–25 are empty; the 2016 board isn't in the app). `angles` is a list like `["40°","25°"]` (bare `"40"` works) or `"all"`. |
| `benchmarks_only` | only write benchmark problems |
| `min_grade` / `max_grade` | inclusive Font-grade range, e.g. `"6B+"`…`"7C"` |
| `setter` | only problems whose setter name contains this (case-insensitive) |
| `output_dir` | where dataset files go |
| `write_benchmark_files` | also write a `*_benchmarks` file per angle |
| `moonlink_pwa_dir` | a moonlink-pwa checkout. Set it and `to_moonlink.py` also writes one combined `problems.json` there, which the served PWA auto-loads |

The sync API always returns a board's whole catalog, so `boards` drives the
download and the rest just filter what's written. A missing `config.json` uses
the defaults. Two more examples:

```json
{ "boards": [{ "id": 21, "name": "MoonBoard 2024", "angles": "all" }],
  "write_benchmark_files": false }

{ "boards": [{ "id": 21, "name": "MoonBoard 2024", "angles": ["40°"] }],
  "benchmarks_only": true, "min_grade": "7A" }
```

## Using it in moonlink-pwa

**Integrated (recommended).** Set `moonlink_pwa_dir` to your moonlink-pwa
checkout, run `./moonboard fetch` (or `convert`), then serve the PWA from that
directory — `python3 -m http.server`, since `localhost` is a secure context for
Web Bluetooth. The app finds `problems.json` next to it, loads the library, and
caches it in IndexedDB for offline use. Re-converting refreshes it on next load.

**Standalone.** Open moonlink-pwa anywhere (HTTPS or local file; Web Bluetooth
needs Chrome/Edge on desktop/Android, or Bluefy on iPhone) and drag any
`*_moonlink.json` onto its drop zone. It also reads the raw `data/*_40.json`
files, and persists a dropped library on the device.

Either way you can filter by grade range / board / angle / benchmark / search,
sort by repeats, grade, rating, date or name, pick a problem (or Random),
connect, and light the board.

**Hold photos (optional).** `./moonboard holds` (needs the headed-Chrome
moonboard.com login the legacy scraper uses) downloads each board's hold photos
and layout into `data/holds/` and bundles them:

- `data/moonlink_holds.json` — base64 images in one file; survives transfer to a
  phone, so use this for phone imports.
- `data/moonlink_holds.zip` — smaller, for desktop or serving.

Drop either on the PWA's library zone and it draws the real holds under the grid,
dimmed behind the lit climb, switching layout per board. If `moonlink_pwa_dir` is
set the holds are also copied to `<pwa>/holds/` for a served PWA to auto-load —
include that folder in your deploy.

## Refreshing later

```bash
# phone: tunnel ON, cert still trusted
./moonboard fetch
```

When done, toggle the WireGuard tunnel OFF on the phone (leave the tunnel + cert
for next time, or remove them under VPN & Device Management), run
`./moonboard stop`, and re-enable the firewall if you stopped it.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Phone says "no internet" once the VPN is on | Firewall blocking UDP 51820 — `sudo systemctl stop firewall` |
| `http://mitm.it` won't load | Tunnel not ON, or a Wi-Fi HTTP proxy is interfering. Use the WireGuard tunnel. |
| "certificate unknown" in `data/wg.log` | Cert not fully trusted yet — finish the Certificate Trust Settings step |
| App hangs on "please wait" | Proxy is intercepting attestation. Start via `./moonboard proxy`, which sets `--allow-hosts`. |
| `captured_requests.jsonl` stays empty | You're on a Wi-Fi HTTP proxy, which Flutter ignores. Use WireGuard mode and turn the Wi-Fi proxy off. |
| fetch exits 401/403 | Tokens expired — re-run `./moonboard fetch` and reload the app within a minute or two |
| `gateway.icloud.com` errors spamming the log | Normal, Apple pins those; ignore |

## Files

| File | Purpose |
|---|---|
| `moonboard` | the CLI (`fetch` / `proxy` / `convert` / `holds` / `stop` / `status` / `config`) |
| `start_proxy.sh` | starts mitmproxy in WireGuard mode; prints the config + QR |
| `capture_addon.py` | mitmproxy addon logging `ems-x.com` traffic to `data/captured_requests.jsonl` |
| `capture_and_fetch.sh` | shim that forwards to `./moonboard fetch` |
| `config.py` / `config.json` | config loader + the config itself |
| `fetch_problems.py` | replays the sync API and pages the catalog |
| `to_moonlink.py` | converts to moonlink-pwa's schema; writes `problems.json` when `moonlink_pwa_dir` is set |
| `fetch_hold_layouts.py` | downloads hold photos/layouts and bundles them for the PWA |
| `pull_moonboard.py` / `run.sh` | legacy `moonboard.com` scraper (no longer returns 2024 data) |
| `APP_API_NOTES.md` | the reverse-engineered backend and auth flow |
| `credentials.example.json` | template for the legacy scraper only |

## Legal

For personal use with your own MoonBoard account. Respect Moon Climbing's Terms
of Service. Don't redistribute the scraped database — share the code and let
people pull their own (which is why `data/` is git-ignored).
