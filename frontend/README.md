# ProofPay — merchant web app

Payment verification for small merchants in Pakistan. A shopkeeper shares the
screenshot a customer sent them on WhatsApp; ProofPay compares it against the
payments that actually arrived, checks whether that payment already paid for an
earlier order, and answers in about two seconds.

React 19 · Vite · TypeScript (strict) · Tailwind v4.

## Run it

```bash
npm install
npm run dev        # http://localhost:5173
npm run build      # tsc -b && vite build
npm run lint       # oxlint
```

It runs with **no backend**. `VITE_USE_MOCKS` defaults to on, and the fixtures in
`src/mocks/` were generated from the real verification engine, so all five
verdicts are real engine output rather than hand-written JSON.

The picker at the top of the upload screen means the same thing in both modes.
`src/mocks/orders.json` is dumped from the backend's own order list, and every
fixture in `src/mocks/verifications.json` is one of those same orders checked
against its own committed receipt by the real engine. Choosing an order replays
that order's own answer — the edited-amount order comes back SUSPICIOUS, about
its own Rs 5,000, and no verdict on screen ever discusses a sum the picker did
not offer. Regenerate all three mock files together with
`cd ../backend && uv run python ../scripts/generate_api_mocks.py`; it refuses to
write a set in which an order in the picker has no check behind it.

## Against the live API

```bash
# Linux / macOS
VITE_USE_MOCKS=false npm run dev
```

```powershell
# Windows PowerShell
$env:VITE_USE_MOCKS='false'; npm run dev
```

with the backend up:

```bash
cd ../backend && uv run uvicorn proofpay.main:app --reload
```

Sign-in is automatic and silent — the first call that needs a token posts to
`/api/v1/auth/token` (form-encoded, user `owner`, any password) and holds the
Bearer token from there. There is no login screen to fail on stage.

The two dialects of the API — the generated mocks and the live server — are
folded into one set of shapes by `src/api/adapt.ts`. Every response goes through
it, mocks included, so a screen that renders one renders the other.

## Demonstrating it

| | |
|---|---|
| `?present=1` | Raises the type for a projector. Use this, **not** browser zoom: zoom shrinks the CSS viewport and can trip the phone breakpoint live on stage. |
| **Start over** / `Esc` | Always reachable, in the top strip. Cancels whatever is in flight, clears the used-payment memory, returns a clean upload screen. |
| The order picker | Top of the upload screen, above the drop target: choose the order first, then hand over the proof. The chosen one is filled white; the rest are outlines. Arrow keys move between them. "Check this payment" stays unavailable until both an order and a screenshot are in hand. |
| The demo rail | Three buttons at the bottom of the upload screen go straight to a real verdict without an order or a file, so a demo never depends on a file picker or on venue wifi. |

## Where things live

| | |
|---|---|
| `src/theme.css` | Every colour, type step and the nine-step spacing scale. The dynamic spacing scale is **off**: `p-5` generates nothing. |
| `src/lib/status.ts` | The one lookup binding a status to its word, colour, polarity and glyph. |
| `src/lib/copy.ts` | The merchant-facing words. |
| `src/screens/` | The five verdicts, the upload screen and the checking screen. |
| `src/api/` | The client and the wire adapter. |

Two rules worth knowing before editing anything here: a fraud score is never
rendered in any form, and NOT FOUND is not an accusation. The reasoning is in the
header comment of each file.
