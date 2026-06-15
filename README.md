# moonboard-2024-fetcher

Pull the full MoonBoard 2024 problem catalog into local JSON and convert it for
[moonlink-pwa](https://github.com/mbdalpha/moonlink-pwa), which lights problems
on a physical LED board.

## How it works

The 2024 data only lives in the Moon Climbing app, behind device attestation
that can't be faked from a script. So instead this borrows your phone's session:
you run a proxy, the app makes one authenticated request through it, and the tool
replays that request's sync endpoint to page the whole catalog. Backend details:
[`APP_API_NOTES.md`](APP_API_NOTES.md).

```
 Moon app on phone ──(WireGuard VPN)──▶ proxy on computer ──▶ catalog JSON ──▶ moonlink-pwa
```

## What you need

- A MoonBoard account and the Moon Climbing app on a real phone (emulators fail
  attestation), on the same Wi-Fi as your computer.
- `nix` (runs the proxy tools) and `python3`.
- The WireGuard app on the phone, plus Bluefy on iPhone for the LED step (Safari
  has no Web Bluetooth).

## The CLI

```bash
chmod +x *.sh moonboard
```

| Command | Does |
|---|---|
| `./moonboard fetch` | start the proxy if needed, wait for a phone request, download, convert |
| `./moonboard proxy` | start the proxy and print the WireGuard QR |
| `./moonboard convert` | re-run only the conversion on downloaded data |
| `./moonboard holds` | download hold photos for the PWA (needs Chrome) |
| `./moonboard stop` | stop the proxy |
| `./moonboard status` | proxy / capture / dataset state |
| `./moonboard config` | print the active config |

## First run

1. `./moonboard proxy` and scan the QR with the WireGuard app, then toggle the
   tunnel ON.
2. Install the proxy's cert: on the phone open `http://mitm.it`, install the iOS
   profile, then enable full trust under Settings → General → About →
   Certificate Trust Settings.
3. `./moonboard fetch`, then open the Moon app and load the 2024 / 40° problem
   list when it says it's waiting. Tokens expire fast, so if it 401s just run it
   again.

That's it — after the one-time tunnel + cert, every refresh is just
`./moonboard fetch`. The scripts it wraps (`fetch_problems.py`, `to_moonlink.py`,
etc.) also run standalone if you'd rather.

## config.json

Picks what to download. Default is MoonBoard 2024 at 40°:

```json
{ "boards": [{ "id": 21, "name": "MoonBoard 2024", "angles": ["40°"] }] }
```

Known board ids: 15 = 2017, 17 = 2019, 19 = Mini 2020, 21 = 2024, 22 = Mini
2024. Other keys filter the output (`benchmarks_only`, `min_grade`/`max_grade`,
`setter`) or wire it to the app (`moonlink_pwa_dir`); see `config.py` for the
full list.

## Using it in moonlink-pwa

Set `moonlink_pwa_dir` in `config.json` to your moonlink-pwa checkout and the
conversion drops a `problems.json` next to it that the served PWA auto-loads.
Otherwise just drag a `data/*_moonlink.json` file onto the PWA's drop zone.
`./moonboard holds` adds real hold photos under the grid.

## Legal

For personal use with your own MoonBoard account. Respect Moon Climbing's Terms
of Service, and don't redistribute the scraped database — share the code and let
people pull their own.
