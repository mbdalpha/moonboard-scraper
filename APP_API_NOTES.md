# Moon Climbing app backend — decompilation findings (2026-06-10)

Decompiled `com.trainingboard.moon` (Flutter app). The 2024-board data lives in
this backend, **not** moonboard.com (which is being retired).

## Backend
- Host: `https://grn-climbing.ems-x.com`
- API base: `/_bs_api/v1/`  ("bs_api" = **Bubble.io** service API; ems-x.com is a Bubble host)
- Attestation entry point: `POST /_bs_api/v1/_ap/validate`
  - Live: returns `{"message":"Invalid token","status":10,...}` (HTTP 400) without a valid token.

## Auth flow (from libapp.so strings)
1. App gets a **Play Integrity** token (Android) / **App Attest + DeviceCheck** (iOS).
2. `POST /_ap/validate` with that token -> backend session.
3. `/auth/authorize` issues a `Bearer` token; later calls send `appId` + `apiKey` + `Bearer`.

## Endpoint names found (under /_bs_api/v1/)
- `/_ap/validate`        device attestation
- `/auth/authorize`      get bearer token
- `/problems/problemfilter`   <-- the climb list (what we want)
- `/problems/holdfilter`
- `/profileProblems`, `/profileDetails`, `/profileLogbookSummary`, `/profile/update`
- `/logbook`, `/logbookDetail`
- `/board`, `/boards/`, `/boardbuilder`, `/map/marker`, `/permissions/methods`, `/climbharder`

All of the above 404 when hit directly without attestation/auth; only `/_ap/validate`
responds. So the data endpoints are gated behind the attestation + bearer flow.

## Feasibility
The wall is **Play Integrity / App Attest** at `/_ap/validate`. Those tokens are
Google/Apple-signed, tied to a genuine device + the app's exact signing cert; a
plain script cannot mint one. Realistic paths:
  1. Run the real app (real device, or proxy like mitmproxy/HTTP Toolkit) and
     capture the `Bearer` token after it authenticates, then replay it against
     `/problems/problemfilter` from a script until it expires.
  2. Frida hook on a rooted device to dump the live token / call the app's own
     authenticated client.
Pure-software Play Integrity bypass on a non-certified environment is generally
not reliable (that's the point of attestation).
