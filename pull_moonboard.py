#!/usr/bin/env python3
"""Pull MoonBoard climbs from moonboard.com into a local JSON dataset.

Ported from OpenMoonBoard's MoonBoardClient.cs
(https://github.com/ConnorDKeehan/OpenMoonBoard):
  1. Log in to www.moonboard.com with a real account.
  2. Crawl the logbooks of a few prolific users to discover setter IDs.
  3. Call Account/GetProblems/{setterId} for each setter -- the only endpoint
     that returns full problems including moves.

moonboard.com sits behind a Cloudflare managed challenge that blocks plain
HTTP clients and headless browsers, so this drives a *headed* Chrome via
Playwright and issues all API calls with fetch() from inside the page.

Run via:  ./run.sh <command>
Commands:
  discover    log in, dump hold-setup / angle ids found on the site
  benchmarks  pull the benchmark list for the target setup (fast)
  crawl       full setter crawl -> data/raw_problems.jsonl (resumable)
  dataset     build all_climbs.json + moonboard2024_40_climbs.json from raw data

Credentials: env MOONBOARD_USERNAME / MOONBOARD_PASSWORD, or credentials.json
next to this script: {"username": "...", "password": "..."}
"""

import json
import os
import pathlib
import re
import sys
import time
import urllib.parse

from playwright.sync_api import sync_playwright

BASE = "https://www.moonboard.com"
HERE = pathlib.Path(__file__).resolve().parent
DATA = HERE / "data"
PROFILE = HERE / "browser-profile"
RAW_PROBLEMS = DATA / "raw_problems.jsonl"
SETTERS_STATE = DATA / "setters.json"
CHROME = "/run/current-system/sw/bin/google-chrome"

# Seed users from OpenMoonBoard's SyncRBicepsAndHLeesLogBookSettersCommandHandler
SEED_USERS = {
    "Ben Moon": "3069743d-2452-4b75-a074-dea06979a4e7",
    "Ravioli Biceps": "E786F934-B0FF-4422-98A5-716DBAFDC7FB",
    "Hoseok Lee": "F3484E0C-4620-41C8-BCC3-0114563AB1AA",
}

TARGET_SETUP_RE = re.compile(r"2024", re.I)
TARGET_ANGLE_RE = re.compile(r"40", re.I)

REQUEST_DELAY_S = 1.0
PAGE_SIZE = 100

FETCH_JS = """async ({url, body}) => {
  const resp = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
      'X-Requested-With': 'XMLHttpRequest',
    },
    body,
    credentials: 'same-origin',
  });
  return {status: resp.status, text: await resp.text()};
}"""


def load_credentials():
    user = os.environ.get("MOONBOARD_USERNAME")
    pw = os.environ.get("MOONBOARD_PASSWORD")
    if user and pw:
        return user, pw
    cred_file = HERE / "credentials.json"
    if cred_file.exists():
        creds = json.loads(cred_file.read_text())
        return creds["username"], creds["password"]
    sys.exit(
        "No credentials. Set MOONBOARD_USERNAME/MOONBOARD_PASSWORD or create "
        f"{cred_file} with {{\"username\": ..., \"password\": ...}}"
    )


class MoonBoardClient:
    def __init__(self, pw):
        self.ctx = pw.chromium.launch_persistent_context(
            str(PROFILE),
            executable_path=CHROME,
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()

    def close(self):
        self.ctx.close()

    def goto(self, url, challenge_wait_s=90):
        self.page.goto(url, timeout=60000)
        waited = 0
        while "Just a moment" in self.page.title() and waited < challenge_wait_s:
            self.page.wait_for_timeout(3000)
            waited += 3
        if "Just a moment" in self.page.title():
            raise RuntimeError(
                "Stuck on the Cloudflare challenge -- click the checkbox in the "
                "Chrome window if one is shown, then re-run."
            )

    def is_logged_in(self):
        return bool(re.search(r"logoutForm|Sign out", self.page.content(), re.I))

    def login(self):
        self.goto(f"{BASE}/account/login")
        if self.is_logged_in():
            print("Already logged in (session restored from browser profile)")
            return
        username, password = load_credentials()
        self.page.fill('#frmLogin input[name="Login.Username"]', username)
        self.page.fill('#frmLogin input[name="Login.Password"]', password)
        with self.page.expect_navigation(timeout=60000):
            self.page.click('#frmLogin [type="submit"]')
        self.page.wait_for_timeout(2000)
        if not self.is_logged_in():
            html = self.page.content()
            (DATA / "login_debug.html").write_text(html)
            err = re.search(
                r'validation-summary-errors.*?<li>([^<]+)</li>', html, re.S
            )
            raise RuntimeError(
                f"Login failed at {self.page.url} (title: {self.page.title()!r}): "
                + (err.group(1).strip() if err else "unknown reason")
                + " -- page saved to data/login_debug.html"
            )
        print("Logged in to moonboard.com")

    def api_post(self, url, form, retries=3):
        body = urllib.parse.urlencode(form)
        for attempt in range(retries):
            res = self.page.evaluate(FETCH_JS, {"url": url, "body": body})
            if res["status"] == 200:
                try:
                    return json.loads(res["text"])
                except json.JSONDecodeError:
                    pass  # challenge page or html error -> fall through to retry
            if attempt < retries - 1:
                print(
                    f"  status {res['status']} from {url}, re-checking session...",
                    file=sys.stderr,
                )
                self.goto(BASE + "/Dashboard/Index")
                if not self.is_logged_in():
                    self.login()
                time.sleep(3 * (attempt + 1))
        snippet = res["text"][:200].replace("\n", " ")
        raise RuntimeError(f"API call failed ({res['status']}) {url}: {snippet}")

    def paged_post(self, url, filter_str="", page_size=PAGE_SIZE):
        """Kendo-grid style paged POST, as in genericMoonBoardRequest()."""
        results = []
        page_num = 1
        while True:
            doc = self.api_post(
                url,
                {
                    "sort": "",
                    "page": str(page_num),
                    "pageSize": str(page_size),
                    "group": "",
                    "filter": filter_str,
                },
            )
            batch = doc.get("Data") or []
            results.extend(batch)
            total = doc.get("Total")
            print(f"  {url.split('.com/')[-1]} page {page_num}: +{len(batch)} (total={total})")
            if len(batch) < page_size or (total is not None and len(results) >= total):
                break
            page_num += 1
            time.sleep(REQUEST_DELAY_S)
        return results

    # --- endpoints from MoonBoardClient.cs ---

    def get_benchmarks(self, filter_str):
        return self.paged_post(f"{BASE}/Dashboard/GetBenchmarks", filter_str)

    def get_logbook_days(self, user_id, filter_str=""):
        return self.paged_post(f"{BASE}/Account/GetLogbook/{user_id}", filter_str)

    def get_logbook_entries(self, user_id, day_id, filter_str=""):
        return self.paged_post(
            f"{BASE}/Account/GetLogbookEntries/{user_id}/{day_id}", filter_str
        )

    def get_problems_by_setter(self, setter_id, filter_str=""):
        return self.paged_post(f"{BASE}/Account/GetProblems/{setter_id}", filter_str)


def discover(client):
    """Dump hold setup / configuration ids visible on the site after login."""
    found = []
    for path in ("/Dashboard/Index", "/Problems/Index"):
        try:
            client.goto(BASE + path)
        except Exception as e:
            print(f"  {path}: {e}")
            continue
        html = client.page.content()
        (DATA / f"page_{path.strip('/').replace('/', '_')}.html").write_text(html)
        for m in re.finditer(
            r'<option[^>]*value="(\d+)"[^>]*>\s*([^<]*)</option>', html
        ):
            desc = m.group(2).strip()
            if re.search(r"(moonboard|masters|mini|\d{4}|°|degree)", desc, re.I):
                found.append((path, m.group(1), desc))
        for m in re.finditer(
            r'"Id"\s*:\s*(\d+)\s*,\s*"Description"\s*:\s*"([^"]+)"', html
        ):
            found.append((path, m.group(1), m.group(2)))
        time.sleep(REQUEST_DELAY_S)
    (DATA / "discovery.json").write_text(json.dumps(found, indent=2))
    print(f"\nDiscovered {len(found)} id/description pairs -> data/discovery.json")
    for path, id_, desc in found:
        print(f"  [{path}] {id_} = {desc}")
    return found


def resolve_target_ids(client):
    """Figure out setupId + Configuration id for MoonBoard 2024 @ 40 degrees."""
    setup_id = os.environ.get("MB_SETUP_ID")
    config_id = os.environ.get("MB_CONFIG_ID")
    if setup_id and config_id:
        return setup_id, config_id
    disc_file = DATA / "discovery.json"
    found = (
        json.loads(disc_file.read_text()) if disc_file.exists() else discover(client)
    )
    for _, id_, desc in found:
        if not setup_id and TARGET_SETUP_RE.search(desc) and re.search(
            r"moonboard", desc, re.I
        ):
            setup_id = id_
            print(f"Using setupId {id_} ({desc})")
        if not config_id and TARGET_ANGLE_RE.search(desc) and re.search(
            r"°|degree", desc, re.I
        ):
            config_id = id_
            print(f"Using Configuration {id_} ({desc})")
    if not (setup_id and config_id):
        sys.exit(
            "Could not auto-detect 2024/40deg ids -- inspect data/discovery.json "
            "and set MB_SETUP_ID / MB_CONFIG_ID env vars."
        )
    return setup_id, config_id


def target_filter(setup_id, config_id):
    return f"setupId~eq~'{setup_id}'~and~Configuration~eq~{config_id}"


def is_target_problem(p):
    setup = ((p.get("Holdsetup") or {}).get("Description")) or ""
    config = ((p.get("MoonBoardConfiguration") or {}).get("Description")) or ""
    return bool(TARGET_SETUP_RE.search(setup) and TARGET_ANGLE_RE.search(config))


def load_setters():
    return json.loads(SETTERS_STATE.read_text()) if SETTERS_STATE.exists() else {}


def save_setters(setters):
    SETTERS_STATE.write_text(json.dumps(setters, indent=2))


def cmd_benchmarks(client):
    setup_id, config_id = resolve_target_ids(client)
    benchmarks = client.get_benchmarks(target_filter(setup_id, config_id))
    out = DATA / f"benchmarks_setup{setup_id}_config{config_id}.json"
    out.write_text(json.dumps(benchmarks, indent=2))
    print(f"Saved {len(benchmarks)} benchmarks -> {out}")


def cmd_crawl(client):
    """Seed logbooks -> setters -> all problems per setter (resumable)."""
    setup_id, config_id = resolve_target_ids(client)
    filter_str = target_filter(setup_id, config_id)
    setters = load_setters()

    if not setters:
        print("Collecting setters from seed users' logbooks...")
        for name, uid in SEED_USERS.items():
            print(f"Seed user: {name}")
            try:
                days = client.get_logbook_days(uid, filter_str)
            except Exception as e:
                print(f"  logbook failed: {e}")
                continue
            for day in days:
                try:
                    entries = client.get_logbook_entries(uid, day["Id"], filter_str)
                except Exception as e:
                    print(f"  day {day['Id']} failed: {e}")
                    continue
                for entry in entries:
                    setter = (entry.get("Problem") or {}).get("Setter") or {}
                    sid, nick = setter.get("Id"), setter.get("Nickname")
                    if sid and sid not in setters:
                        setters[sid] = {"name": nick, "synced": False}
                time.sleep(REQUEST_DELAY_S)
            save_setters(setters)
        print(f"Found {len(setters)} setters -> {SETTERS_STATE}")

    pending = {sid: s for sid, s in setters.items() if s["synced"] is not True}
    print(f"{len(pending)} of {len(setters)} setters left to sync")
    seen_ids = set()
    if RAW_PROBLEMS.exists():
        with RAW_PROBLEMS.open() as f:
            for line in f:
                try:
                    seen_ids.add(json.loads(line)["Id"])
                except (json.JSONDecodeError, KeyError):
                    pass

    with RAW_PROBLEMS.open("a") as out:
        for i, (sid, setter) in enumerate(pending.items(), 1):
            print(f"[{i}/{len(pending)}] setter {setter['name']} ({sid})")
            try:
                # Unfiltered: grab everything the setter made, filter locally later.
                problems = client.get_problems_by_setter(sid)
            except Exception as e:
                print(f"  failed: {e}")
                setters[sid]["synced"] = "failed"
                save_setters(setters)
                continue
            new = 0
            for p in problems:
                if p.get("Id") in seen_ids:
                    continue
                seen_ids.add(p.get("Id"))
                out.write(json.dumps(p) + "\n")
                new += 1
            out.flush()
            setters[sid]["synced"] = True
            setters[sid]["problems"] = len(problems)
            save_setters(setters)
            print(f"  {len(problems)} problems ({new} new, {len(seen_ids)} total)")
            time.sleep(REQUEST_DELAY_S)
    print(f"Crawl complete. Raw problems in {RAW_PROBLEMS}")


def cmd_dataset():
    if not RAW_PROBLEMS.exists():
        sys.exit(f"No raw data yet -- run crawl first ({RAW_PROBLEMS} missing)")
    all_problems, target = [], []
    with RAW_PROBLEMS.open() as f:
        for line in f:
            p = json.loads(line)
            all_problems.append(p)
            if is_target_problem(p):
                target.append(p)
    out_all = DATA / "all_climbs.json"
    out_2024 = DATA / "moonboard2024_40_climbs.json"
    out_all.write_text(json.dumps(all_problems, indent=2))
    out_2024.write_text(json.dumps(target, indent=2))
    print(f"{len(all_problems)} climbs total -> {out_all}")
    print(f"{len(target)} MoonBoard 2024 40\N{DEGREE SIGN} climbs -> {out_2024}")


def main():
    DATA.mkdir(exist_ok=True)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "dataset":
        cmd_dataset()
        return
    if cmd not in ("discover", "benchmarks", "crawl"):
        print(__doc__)
        return

    with sync_playwright() as pw:
        client = MoonBoardClient(pw)
        try:
            client.login()
            if cmd == "discover":
                discover(client)
            elif cmd == "benchmarks":
                cmd_benchmarks(client)
            elif cmd == "crawl":
                cmd_crawl(client)
        finally:
            client.close()


if __name__ == "__main__":
    main()
