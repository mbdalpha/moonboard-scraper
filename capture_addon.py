"""mitmproxy addon: capture the Moon app's backend traffic.

Logs every request to the Bubble backend (grn-climbing.ems-x.com) with full
headers + bodies to data/captured_requests.jsonl, and prints a one-line summary
to the console so we can see the climb endpoint fire in real time.
"""
import json
import pathlib

OUT = pathlib.Path(__file__).resolve().parent / "data" / "captured_requests.jsonl"
HOST_MATCH = "ems-x.com"


def _body(msg):
    try:
        return msg.get_text(strict=False)
    except Exception:
        return f"<{len(msg.raw_content or b'')} bytes binary>"


def response(flow):
    host = flow.request.pretty_host
    if HOST_MATCH not in host:
        return
    rec = {
        "method": flow.request.method,
        "url": flow.request.pretty_url,
        "req_headers": dict(flow.request.headers),
        "req_body": _body(flow.request),
        "status": flow.response.status_code,
        "resp_headers": dict(flow.response.headers),
        "resp_body": _body(flow.response),
    }
    with OUT.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    path = flow.request.path.split("?")[0]
    rlen = len(flow.response.raw_content or b"")
    print(f"[CAPTURED] {flow.request.method} {path} -> {flow.response.status_code} "
          f"({rlen} bytes resp)", flush=True)
