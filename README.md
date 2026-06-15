# moonboard-fetcher

Pull the full MoonBoard problem catalog into local JSON and convert it for
[moonlink-pwa](https://github.com/mbdalpha/moonlink-pwa), which lights problems
on a physical LED board.

## How it works

The data only lives in the Moon Climbing app, behind device attestation
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
- Only for `./moonboard holds` (optional): a moonboard.com website login and
  headed Chrome — see [Hold photos](#hold-photos) below. The everyday
  `fetch` path doesn't need either.

## The CLI

```bash
chmod +x *.sh moonboard
```

| Command | Does |
|---|---|
| `./moonboard fetch` | start the proxy if needed, wait for a phone request, download, convert |
| `./moonboard proxy` | start the proxy and print the WireGuard QR |
| `./moonboard convert` | re-run only the conversion on downloaded data |
| `./moonboard holds` | download hold photos from moonboard.com and bundle them for the PWA (separate website login) |
| `./moonboard boards` | list the boards/angles you can scrape |
| `./moonboard select` | choose which board + angle to scrape (writes config.json) |
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

That's it - after the one-time tunnel + cert, every refresh is just
`./moonboard fetch`. The scripts it wraps (`fetch_problems.py`, `to_moonlink.py`,
etc.) also run standalone if you'd rather.

## Choosing what to scrape

Easiest is the CLI, which writes `config.json` for you:

```bash
./moonboard boards                      # list the boards
./moonboard select                      # pick a board + angle, interactively
./moonboard select --board 21 --angle 40
./moonboard select --all                # every board, every angle
```

Or edit `config.json` directly. Default is MoonBoard 2024 at 40°:

```json
{ "boards": [{ "id": 21, "name": "MoonBoard 2024", "angles": ["40°"] }] }
```

`angles` can be a list like `["25°","40°"]` or `"all"`. The remaining keys
filter the output (`benchmarks_only`, `min_grade`/`max_grade`, `setter`) or wire
it to the app (`moonlink_pwa_dir`); see `config.py` for the full list.

## Using it in moonlink-pwa

Set `moonlink_pwa_dir` in `config.json` to your moonlink-pwa checkout and the
conversion drops a `problems.json` next to it that the served PWA auto-loads.
Otherwise just drag a `data/*_moonlink.json` file onto the PWA's drop zone.

### Hold photos

`./moonboard holds` adds the real hold photos under the LED grid. This is a
*separate* path from `fetch`: the photos live on moonboard.com, which sits
behind Cloudflare, so it drives a headed Chrome (via Playwright) and logs into
the website. Give it credentials one of two ways:

```bash
export MOONBOARD_USERNAME=... MOONBOARD_PASSWORD=...   # env, or
cp credentials.example.json credentials.json          # then fill it in
```

It writes both `data/moonlink_holds.zip` and `data/moonlink_holds.json` — drop
either onto the PWA's library zone (the `.json` survives transfer to a phone;
the `.zip` is smaller for desktop). If `moonlink_pwa_dir` is set, it also copies
the holds straight into that checkout so a served PWA auto-loads them.

## Legal

For personal use with your own MoonBoard account. Respect Moon Climbing's Terms
of Service.