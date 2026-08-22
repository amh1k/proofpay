# Phase 5 — Merchant Client — Best Practices

**Scope:** the React app a merchant uses to log in, submit a payment screenshot, read the verification result, and browse history. The single most important artefact in this phase is **the result view**. Everything else is plumbing that must not break during a five-minute demo.

**Governing constraint from the architecture:** the screenshot is an *untrusted claim*; the merchant's transaction feed is the *source of truth*. This is not just a backend rule — it must be **visible in the UI's structure**. See §5.

---

## 1. Project setup — Vite + React + Tailwind in August 2026

### 1.1 What "current" actually means right now (verified against the registry today)

| Package | Current | Use |
|---|---|---|
| `vite` | **8.2.2** (Vite 8 released 2026‑03‑12; Rolldown is the default bundler, no opt‑in) | yes |
| `react` / `react-dom` | **19.2.8** | yes |
| `typescript` | latest is **7.0.2** (2026‑07‑08, Go‑native `tsgo`) | **no — pin `~6.0.3`** |
| `tailwindcss` + `@tailwindcss/vite` | **4.3.3** | yes |
| `@tanstack/react-query` | **5.101.4** | yes |
| `@tanstack/react-table` | latest is **9.1.2** | **pin `^8.21.3`** (see §7) |
| `@tanstack/react-router` | **1.170.31** | yes |
| `@vitejs/plugin-react` | **6.1.0** | yes |
| `react-dropzone` | **20.1.1**, peer `react: ">= 18"` | yes — React 19 is fine |
| `lucide-react` | **1.33.0** | yes |

Node requirement for Vite 8: `^20.19.0 || >=22.12.0`. Vite 8 is **ESM‑only**. If anyone on the team is on Node 18, they cannot run the frontend — check this on day one, not on demo day.

### 1.2 TypeScript: use 6, not 7 (contested — here's the call)

TypeScript 7.0 shipped 8 July 2026 and is 8–12× faster. **Do not use it for this project.** TS 7.0 has *no stable programmatic API*, so `typescript-eslint`, `ts-morph`, `ts-jest` and template type‑checkers cannot run on it; that API is targeted for 7.1, "several months out". A hackathon is exactly the wrong place to discover your linter won't start. Pin `typescript: "~6.0.3"`. (For reference, `satnaing/shadcn-admin` — your named reference repo — pins `typescript: "~6.0.3"` today.)

**TS 6 changed defaults you must know:**

- `strict` is **on by default** (this is why the current `create-vite` template no longer lists it).
- `types` defaults to **`[]`** — no auto‑discovery of `@types`. If you drop `"types": ["vite/client"]`, `import.meta.env` stops type‑checking. Keep it.
- ESM is the default `module`; `target` defaults to the current year's ES version.
- `--baseUrl` is deprecated as a resolution root, `--outFile` is removed, `moduleResolution: "node"` is deprecated (use `"bundler"`).

### 1.3 Scaffold

```bash
npm create vite@latest proofpay-web -- --template react-ts
cd proofpay-web
npm i @tailwindcss/vite tailwindcss \
      @tanstack/react-query @tanstack/react-router @tanstack/react-table@^8 \
      lucide-react sonner zod react-hook-form @hookform/resolvers \
      clsx tailwind-merge class-variance-authority react-dropzone
npm i -D @tanstack/router-plugin @tanstack/react-query-devtools @types/node
npx shadcn@latest init
```

Note the current template lints with **oxlint**, not ESLint (`_oxlintrc.json`, `"lint": "oxlint"`). Keep oxlint — it is instant and needs zero config. Do not spend hackathon hours porting to `typescript-eslint`.

Tailwind v4 is **CSS‑first**. There is no `tailwind.config.js` and you should not create one. All theme config lives in `src/styles/index.css`:

```css
@import "tailwindcss";

@theme {
  /* ProofPay verification-state tokens — see §6 for the palette rationale */
  --color-state-verified:  oklch(0.45 0.13 155);
  --color-state-suspicious: oklch(0.55 0.15 70);
  --color-state-duplicate: oklch(0.48 0.16 300);
  --color-state-review:    oklch(0.50 0.15 250);
  --color-state-unmatched: oklch(0.45 0.02 260);
}
```

In `components.json`, for Tailwind v4 leave `tailwind.config` **blank** and point `tailwind.css` at your stylesheet.

### 1.4 `vite.config.ts` — including the IPv6 trap

```ts
import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { tanstackRouter } from '@tanstack/router-plugin/vite'

export default defineConfig({
  plugins: [
    tanstackRouter({ target: 'react', autoCodeSplitting: true }),
    react(),
    tailwindcss(),
  ],
  resolve: { alias: { '@': path.resolve(__dirname, './src') } },
  server: {
    port: 5173,
    strictPort: true,          // fail loudly instead of silently moving to 5174
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',   // <-- NOT localhost. See below.
        changeOrigin: true,
      },
    },
  },
})
```

**The IPv6 trap, explained properly.** Since Node 17, Node's DNS resolution no longer reorders results to prefer IPv4 — `localhost` resolves to whatever the OS returns first, and on Windows and modern macOS that is usually **`::1`** (IPv6 loopback). Uvicorn started as `uvicorn app:api --host 127.0.0.1` binds **only** the IPv4 loopback. So Vite's proxy dials `::1:8000`, nothing is listening there, and you get:

```
[vite] http proxy error: /api/verifications
Error: connect ECONNREFUSED ::1:8000
```

The failure mode that wastes an afternoon: `curl http://localhost:8000/health` works from a shell (curl falls back to IPv4), so everyone concludes "the backend is fine, the frontend is broken."

Three fixes, in order of preference:

1. **Write `http://127.0.0.1:8000` in the proxy target.** Deterministic, one line, no environment dependence. Do this.
2. **Bind Uvicorn to both stacks:** `uvicorn app:api --host 0.0.0.0 --port 8000 --reload`. You need this anyway for the phone demo (§4/§10). Note `--host ::` binds IPv6 and, on Linux with dual‑stack sockets, IPv4 too — but this is OS‑dependent, so prefer `0.0.0.0` plus fix 1.
3. `dns.setDefaultResultOrder('ipv4first')` at the top of `vite.config.ts`. Works, but it is invisible magic that the next person will delete. Don't rely on it.

The same trap bites in reverse on `server.host`: Vite's default is `'localhost'`, and Vite will print the *resolved* address when it differs from what you typed. Read that line in the terminal — it is telling you which stack you're on.

**Why proxy at all rather than calling `http://127.0.0.1:8000` directly from the browser?** Because the proxy makes dev **same‑origin**: no CORS middleware to configure, `Set-Cookie` from FastAPI actually sticks (critical for the refresh‑cookie auth in §9), and every call in your code is a bare relative path:

```ts
// src/lib/api.ts
const BASE = import.meta.env.VITE_API_BASE_URL ?? '/api'
```

In dev `VITE_API_BASE_URL` is unset → `/api` → proxied. In a deployed build you set it once.

### 1.5 Environment variables

Only `VITE_`‑prefixed vars reach the client bundle. **This is a security boundary, not a naming convention.**

> **ANTI‑PATTERN, and someone on your team will try it:** putting the DashScope / Qwen‑VL API key in the frontend as `VITE_DASHSCOPE_API_KEY` to "call the model directly and skip the backend". Every `VITE_*` value is inlined into the JS bundle in plaintext and shipped to every visitor. The vision adapter lives in the backend (Phase 4) and only the backend holds that key. Add a grep to your pre‑commit or CI: `grep -rn "VITE_.*\(KEY\|SECRET\|TOKEN\)" src/ .env*` → fail.

Useful client vars: `VITE_API_BASE_URL`, `VITE_DEMO_MODE=1`, `VITE_USE_FIXTURES=0` (§10).

### 1.6 File layout (feature‑first — mirror the reference repo so you can paste code)

```
src/
  main.tsx                    # QueryClient + Router providers, global 401 handler (§9)
  routeTree.gen.ts            # generated — gitignore-adjacent, do not hand-edit
  routes/
    __root.tsx
    (auth)/sign-in.tsx
    _authenticated/route.tsx          # layout + guard
    _authenticated/index.tsx          # dashboard
    _authenticated/verify.tsx         # upload + camera
    _authenticated/verifications/index.tsx      # history table
    _authenticated/verifications/$id.tsx        # THE result view
    dev/states.tsx                    # renders all 5 verdicts from fixtures (§10)
  features/
    verify/      { components/, hooks/use-file-intake.ts, api.ts }
    result/      { components/evidence-table.tsx, verdict-banner.tsx, reason-codes.tsx }
    verifications/ { components/columns.tsx, components/verifications-table.tsx }
    dashboard/
  components/
    ui/                       # shadcn primitives — do not hand-edit
    data-table/               # lifted from shadcn-admin (§7)
    layout/
  lib/
    verification-states.tsx   # SINGLE SOURCE OF TRUTH for the 5 states (§6)
    api.ts, upload.ts, image.ts, auth.ts
  fixtures/                   # one JSON per verdict, shared with tests and /dev/states
```

---

## 2. Server state — TanStack Query, and why `useEffect` fetching is the wrong default

### 2.1 The argument in one paragraph

TanStack Query is not a fetching library; it is an **async state manager**. Hand‑rolled `useEffect` + `useState` fetching forces you to re‑implement, per call site: loading state, error state, cancellation, **race‑condition protection**, caching, dedup, refetch‑on‑focus, and retry. The race condition is the one that actually bites in this app: the merchant filters history by `SUSPICIOUS`, then quickly by `DUPLICATE`; if the first request resolves last, the table shows SUSPICIOUS rows under a DUPLICATE filter. With Query there is no race, because **state is keyed by its input** — a response can only ever land in the cache entry for the key that requested it. You also get a discriminated union at the type level, so `data` is non‑nullable inside the success branch.

For a team whose stated priority is planning and testing over code volume, this is the highest‑leverage dependency in the phase: it deletes roughly a third of the frontend code you'd otherwise write and test.

### 2.2 Client setup

```ts
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      refetchOnWindowFocus: import.meta.env.PROD,   // off in dev: alt-tabbing while coding is not intent
      retry: (failureCount, error) => {
        if (isHttpError(error) && [401, 403, 422].includes(error.status)) return false
        return failureCount < 2
      },
    },
  },
})
```

Do **not** retry 401/403/422. Retrying a 401 three times during a demo turns a one‑second redirect into a five‑second hang.

### 2.3 The slow verification request — do not freeze the UI

Verification is OCR + retrieval + scoring. Realistically 3–12 seconds with Qwen‑VL, longer on venue wifi. Two shapes:

**Shape A — synchronous mutation (simplest, use this if p95 < ~10s).**

```ts
const verify = useMutation({
  mutationFn: (file: File) => postVerification(file, { onProgress: setPct }),
  onSuccess: (result) => {
    queryClient.invalidateQueries({ queryKey: ['verifications'] })
    router.navigate({ to: '/verifications/$id', params: { id: result.id } })
  },
})
```

`verify.isPending` drives the staged progress UI in §8. The UI is *never* frozen — `mutate()` is fire‑and‑forget and React keeps rendering. Prefer `mutate` over `mutateAsync` unless you genuinely need `try/catch`; `mutateAsync` with an unhandled rejection is a silent unhandled promise.

**Shape B — 202 + poll (use this if the backend can take >15s, or if you want the staged narrative to be *honest*).** Backend returns `{ id, status: 'PENDING', stage: 'OCR' }` immediately; client polls. This is strictly better UX because the stepper reflects reality instead of a guess.

```ts
useQuery({
  queryKey: ['verification', id],
  queryFn: () => getVerification(id),
  enabled: !!id,
  refetchInterval: (query) => {
    const s = query.state.data?.status
    return s === 'PENDING' || s === 'RUNNING' ? 1_500 : false   // false clears the timer
  },
})
```

`refetchInterval` accepts a function receiving the query; returning `false` stops polling, and polling resumes automatically if the function later returns a positive number. Leave `refetchIntervalInBackground` **off** (default) — polling pauses when the tab is hidden, which is what you want.

**Recommendation:** build Shape A first (it is one afternoon), and design the backend response so Shape B is a drop‑in (`status` + `stage` fields present from day one, just always terminal in Shape A). Agree this contract with the Phase 3/4 owners *before* anyone writes code.

### 2.4 Query key conventions

```ts
export const qk = {
  verifications: (f: Filters) => ['verifications', f] as const,
  verification:  (id: string) => ['verification', id] as const,
  dashboard:     () => ['dashboard'] as const,
}
```

Put filters **inside** the key. That is what makes filtering race‑proof and gives you free caching when the merchant toggles a facet back.

> **ANTI‑PATTERNS:** calling `refetch()` on an interval you manage with `setInterval`; storing server data in Zustand/Context ("global state") — server data is a cache, not state; `useEffect(() => { fetch(...).then(setData) }, [])`; a `loading` boolean you set yourself.

---

## 3. File upload UX

### 3.1 One intake, three doors

Drop, paste, and picker/camera must all funnel into a single `File`. Build one hook and never branch again.

```ts
// src/features/verify/hooks/use-file-intake.ts
export function useFileIntake(onFile: (f: File) => void) {
  // 1. paste
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const item = [...(e.clipboardData?.items ?? [])]
        .find(i => i.kind === 'file' && i.type.startsWith('image/'))
      if (!item) return                     // let normal text paste through
      e.preventDefault()
      const f = item.getAsFile()
      if (f) onFile(renameIfAnonymous(f))   // clipboard images arrive as "image.png"
    }
    window.addEventListener('paste', onPaste)
    return () => window.removeEventListener('paste', onPaste)
  }, [onFile])
  // 2. drop -> react-dropzone  3. picker/camera -> <input type="file">
}
```

**Paste matters more than drag‑and‑drop for this product.** A Pakistani merchant on a desktop receives the screenshot in WhatsApp Web or Telegram Web, right‑clicks → Copy image, and hits Ctrl+V. That is the primary desktop path. Make it work *anywhere on the page*, not only when a specific element is focused, and put a visible hint on the dropzone: **"Drop, paste (Ctrl+V), or choose a file."** Judges notice paste working; almost no hackathon project implements it.

Key facts: reading image data from a `paste` event needs **no `clipboard-read` permission** — the Ctrl+V gesture is implicit consent, so it works in every modern browser with no prompt. Only call `preventDefault()` when you actually found an image item, otherwise you break pasting into the reference‑ID text field. Caveat: iOS Safari does not expose `clipboardData.items` for images from the photo library in all contexts — do not make paste the only mobile path (you have camera anyway).

### 3.2 Drag and drop

Use **`react-dropzone` v20** (`peer react: ">= 18"`, so React 19 is fine — older "react-dropzone doesn't support React 19" advice is stale). It handles the thing everyone gets wrong by hand: `dragleave` fires when the pointer crosses a *child* element, so a naive implementation flickers the highlight. Dropzone keeps the enter/leave counter for you, plus `accept`, `maxSize`, and keyboard/ARIA on the root.

```tsx
const { getRootProps, getInputProps, isDragActive } = useDropzone({
  accept: { 'image/*': ['.png', '.jpg', '.jpeg', '.webp', '.heic'] },
  maxFiles: 1,
  maxSize: 12 * 1024 * 1024,
  onDrop: ([f]) => f && onFile(f),
})
```

Cheap alternative if you want zero deps: the shadcn registry now ships a `file-upload` / dropzone block (`npx shadcn add file-upload`) with dashed drop area, file list and remove buttons. Either is fine; do not hand‑roll.

### 3.3 Preview

```ts
const url = useMemo(() => URL.createObjectURL(file), [file])
useEffect(() => () => URL.revokeObjectURL(url), [url])
```

> **ANTI‑PATTERN:** `FileReader.readAsDataURL` for preview. A 12 MP phone photo becomes a ~10 MB base64 string held in memory and pushed through React state and the DOM. Object URLs are a pointer. Always revoke on unmount or you leak per upload.

### 3.4 Client‑side downscaling — and the domain trap nobody warns you about

The mechanics (modern, EXIF‑correct, no library):

```ts
export async function downscale(file: File, maxEdge = 1600): Promise<Blob> {
  const bmp = await createImageBitmap(file, {
    imageOrientation: 'from-image',   // phone photos are rotated via EXIF — without this they land sideways
    resizeWidth: maxEdge,             // browser-native, higher quality than a manual drawImage squeeze
    resizeQuality: 'high',
  })
  const c = new OffscreenCanvas(bmp.width, bmp.height)
  c.getContext('2d')!.drawImage(bmp, 0, 0)
  bmp.close()
  return c.convertToBlob({ type: 'image/jpeg', quality: 0.85 })
}
```

Notes: `OffscreenCanvas` uses `convertToBlob()` (Promise) where `HTMLCanvasElement` uses `toBlob()` (callback). Canvases cap around 16384×16384 in most browsers. Resizing to a sane size and exporting at q≈0.85 beats exporting a full‑resolution image at low quality.

**Now the trap. Do not downscale by default in ProofPay.**

Client‑side re‑encoding does three things that actively damage this specific pipeline:

1. **It strips EXIF and all container metadata** — which is part of what your tamper‑evidence module reads.
2. **It normalises JPEG quantisation tables and removes double‑compression artefacts** — the exact signals that distinguish "screenshot straight from Easypaisa" from "screenshot opened in an editor and re‑saved". Every uploaded image would arrive looking identically re‑encoded, so the tamper‑evidence signals become uniformly uninformative.
3. **It degrades OCR of the smallest, most decision‑relevant glyphs** — the transaction reference ID (typically the smallest text on an Easypaisa/JazzCash receipt).

**Recommended policy:**

| File size | Action |
|---|---|
| ≤ 4 MB | Upload **untouched**. This is >95% of real screenshots. |
| > 4 MB | Downscale to 2000px long edge, JPEG q=0.9, **and send header `X-Client-Resized: 1`** plus the original dimensions and byte size in the form data. |

The header matters: the backend's tamper‑evidence module must know the client re‑encoded, so it can suppress compression‑based signals rather than reporting a false "re‑saved" observation. Write this into the API contract now — it is a genuine cross‑phase interface, and it's the kind of detail that reads as engineering maturity to a judge.

### 3.5 Upload progress

**`fetch()` cannot report upload progress.** It still has no upload progress event; `ReadableStream` request bodies with `duplex: 'half'` are Chromium‑only, require HTTP/2 + HTTPS, and give you stream pulls rather than real progress. Use `XMLHttpRequest`, wrapped so `useMutation` can consume it:

```ts
export function postVerification(file: File, opts: { onProgress?: (p: number) => void } = {}) {
  return new Promise<VerificationResult>((resolve, reject) => {
    const fd = new FormData()
    fd.append('screenshot', file, file.name)          // multipart — do NOT set Content-Type yourself
    fd.append('order_id', currentOrderId)
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${BASE}/verifications`)
    xhr.setRequestHeader('Authorization', `Bearer ${getAccessToken()}`)
    xhr.upload.onprogress = e => e.lengthComputable && opts.onProgress?.(e.loaded / e.total)
    xhr.onload  = () => xhr.status < 400 ? resolve(JSON.parse(xhr.responseText))
                                         : reject(new HttpError(xhr.status, xhr.responseText))
    xhr.onerror = () => reject(new HttpError(0, 'network'))
    xhr.timeout = 60_000
    xhr.ontimeout = () => reject(new HttpError(0, 'timeout'))
    xhr.send(fd)
  })
}
```

Never set `Content-Type` manually on a `FormData` body — the browser must add the multipart boundary.

**The 100%‑bar trap:** upload progress reaches 100% in ~1 second on a 300 KB screenshot, and then the merchant stares at a full bar for eight seconds while OCR runs. A completed bar that does not advance reads as *frozen*. Fix: the upload bar is only **stage 1 of 5** (§8). At 100% the bar hands off to the staged stepper.

> **ANTI‑PATTERN:** base64‑encoding the image into a JSON body. It inflates payload by 33%, blocks the main thread, and throws away the multipart streaming the server already handles.

---

## 4. Camera capture in the browser

### 4.1 The decision

| | `<input type="file" accept="image/*" capture="environment">` | `getUserMedia()` + `<video>` + canvas |
|---|---|---|
| Code | ~1 line | ~80 lines + permission states + track cleanup |
| Reliability on a phone | **Very high** — hands off to the native camera app | Medium — varies by browser/OS/permission history |
| Image quality | Full native camera pipeline (HDR, stabilisation, autofocus) | Whatever the `<video>` track resolution is; often worse |
| Preview/retake | Native, familiar | You build it |
| Desktop | Falls back to a normal file picker (correct) | Opens the webcam (usually wrong for this product) |
| Secure context needed | **No** | **Yes** |

**Recommendation: ship `<input capture>`. Do not build `getUserMedia` for this hackathon.** A merchant photographing a customer's phone screen wants the native camera with autofocus and tap‑to‑focus. `getUserMedia` buys you an in‑page viewfinder and costs you a class of demo‑day failures.

```tsx
<input
  type="file"
  accept="image/*"
  capture="environment"           /* rear camera; "user" = selfie camera */
  className="sr-only"
  ref={cameraInputRef}
  onChange={e => e.target.files?.[0] && onFile(e.target.files[0])}
/>
<Button onClick={() => cameraInputRef.current?.click()}>
  <Camera aria-hidden /> Take photo
</Button>
```

`capture` is no longer a boolean — it takes `user` or `environment`, and if the requested facing mode is unavailable the UA falls back to its preferred default. Where `capture` is unsupported the input degrades to a plain picker, which is a correct fallback, not a failure. Remember `accept` is only a picker hint — **the server must revalidate the content type**.

### 4.2 Secure context — the actual demo killer

`getUserMedia()` only works in secure contexts; in an insecure context `navigator.mediaDevices` is **`undefined`** and you get a `TypeError`, not a permission prompt. Potentially‑trustworthy origins include `https://`, `http://localhost`, `http://127.0.0.1`, `http://*.localhost`, and `file://`.

**`http://192.168.1.x:5173` is NOT a secure context.** This is the exact URL you will type into your phone to demo, and it is the reason "the camera worked on my laptop and died on stage".

Even with `<input capture>` (which needs no secure context), you likely want HTTPS on the phone anyway — for clipboard APIs, service workers, and because iOS Safari is increasingly hostile to insecure origins. Options, cheapest first:

1. **Demo on the laptop, not the phone.** Screenshots are pre‑loaded fixtures (§10). Zero risk. Genuinely the right answer if camera capture is not a scored feature.
2. **`vite-plugin-mkcert`** — generates a locally trusted cert; add `server: { host: true }`. Works instantly on the laptop. On a phone you must install `rootCA.pem` (find the folder with `mkcert -CAROOT`) — AirDrop/email it to iOS and enable full trust under Settings → General → About → Certificate Trust Settings; Android needs user roots enabled. Budget 20 minutes and **do it the day before**, not on stage.
3. **A tunnel** (`cloudflared tunnel --url http://127.0.0.1:5173`) — real public HTTPS cert, no device setup, works on any phone. But it depends on venue wifi and adds latency, and you must add the tunnel hostname to `server.allowedHosts`.

On `allowedHosts`: add the specific hostname. Setting it to `true` allows any website to reach your dev server via DNS rebinding.

### 4.3 If you do build `getUserMedia` (stretch goal only)

Handle the named errors explicitly and map each to merchant‑readable copy plus a fallback button:

| Error | Meaning | UI |
|---|---|---|
| `NotAllowedError` | denied, or insecure context, or Permissions‑Policy | "Camera blocked. Use **Choose file** instead." + how to re‑enable |
| `NotFoundError` | no device matches constraints | fall back to file picker silently |
| `NotReadableError` | OS/hardware busy (another app has the camera) | "Close other camera apps and retry" |
| `OverconstrainedError` | your constraints are impossible | retry without `exact` |

Use `{ video: { facingMode: 'environment' } }` (soft) rather than `{ facingMode: { exact: 'environment' } }` (hard) — the exact form throws `OverconstrainedError` on laptops. **Always `track.stop()` every track** on unmount, on route change, and before switching cameras; a live camera light during the rest of the demo is embarrassing and drains a laptop battery fast.

---

## 5. The explainable result view — the most important screen

### 5.1 Why "87% likely fraud" is the wrong design

This is a design commitment, not a preference. Five reasons:

1. **It's uncalibrated and users read it as a frequency.** Nothing in your pipeline guarantees that "87" means "87 out of 100 such payments are fraudulent". It is a scoring artefact. Displaying it makes a claim you cannot support.
2. **It relocates the decision from your versioned rules to the merchant's gut.** You have already committed to *deterministic, versioned, reproducible* decision rules. A percentage invites the merchant to run a private, unversioned threshold ("72? eh, ship it"). That destroys the reproducibility guarantee that is the point of the architecture.
3. **It is not actionable.** The merchant's next step is completely different for "the sender name doesn't match" (ask the customer who paid) versus "this transaction is already allocated to order #4471" (do not ship — this is a reuse attempt). A single number collapses distinct actions into one blob.
4. **It is not defensible in a dispute.** Regulators and investigators accept *specific, auditable, documented reasons tied to data points a human can verify* — not scores. FICO's long‑standing Reason Reporter exists precisely because a neural‑network score alone is unusable in an adverse‑action conversation. Your merchant has to say something to a customer whose payment was refused. "0.87" is not a sentence.
5. **A precise‑looking number suppresses inspection.** Two decimal places create false authority and users stop reading the evidence beneath it — the exact overtrust failure XAI research warns about. The guidance is blunt: say "estimated risk based on your last 5 transactions", not "anomaly score: 0.78".

**What replaces it:** one of five discrete states + a plain‑language sentence + machine‑readable reason codes + a per‑field evidence table + exactly one recommended action. Internal scores may exist in the JSON and may be shown to a developer under a collapsed "Technical detail" section — they must never be the headline.

### 5.2 The screen, top to bottom

Think of it as **GOV.UK "check your answers" crossed with a diff view**. The GOV.UK summary list exists to let a person verify key/value pairs quickly, and it is the closest established pattern to "claimed vs actual".

```
┌───────────────────────────────────────────────────────────────────────┐
│ ① VERDICT BANNER                                                      │
│   [✔] VERIFIED                                     Order #4471        │
│   Payment confirmed against transaction TXN-8842.                     │
│   ▸ Recommended action:  [ Release the order ]                        │
├───────────────────────────────────────────────────────────────────────┤
│ ② AMOUNT LINE (its own band — amount is the field merchants read 1st) │
│   Expected  Rs 4,500      Screenshot claims  Rs 4,500                 │
│   Your record  Rs 4,500                              ✔ Exact match    │
├───────────────────────────────────────────────────────────────────────┤
│ ③ EVIDENCE TABLE                                                      │
│   Field          │ Screenshot (claim) │ Your records (truth) │ Result │
│   Sender name    │ MUHAMMAD A.        │ Muhammad Ahmed        │ ~ close│
│   Amount         │ Rs 4,500           │ Rs 4,500              │ ✔ match│
│   Time           │ 14:03, 22 Aug      │ 14:02, 22 Aug         │ ✔ 1m   │
│   Reference ID   │ 8842119            │ 8842119               │ ✔ match│
│   Rail           │ Easypaisa          │ Easypaisa             │ ✔ match│
├───────────────────────────────────────────────────────────────────────┤
│ ④ WHY  (reason codes, plain language first, code second)              │
│   • Sender name is a close but not exact match       NAME_FUZZY       │
├───────────────────────────────────────────────────────────────────────┤
│ ⑤ ▸ Screenshot observations (3)          [collapsed by default]       │
│      Not proof of anything on their own.                              │
├───────────────────────────────────────────────────────────────────────┤
│ ⑥ Decision d-01J… · rules v1.4.0 · 22 Aug 2026 14:03 PKT · [Copy JSON]│
└───────────────────────────────────────────────────────────────────────┘
```

**① Verdict banner.** State chip (icon + text + colour), one sentence in merchant language, and **exactly one primary action**. A merchant should be able to act correctly after reading only this band; everything below is justification. Do not put three equal‑weight buttons here. Map: VERIFIED → *Release the order*; UNMATCHED → *Ask customer for the transaction ID*; SUSPICIOUS → *Hold — do not release*; DUPLICATE → *Hold — already used for order #4471* (make the order number a link); NEEDS_REVIEW → *Send to review*.

**② Amount band.** Amount is the first thing a merchant looks at, and your architecture already distinguishes underpayment / claim inflation / overpayment. Give each its own sentence, not a generic "mismatch":

- underpayment → "Rs 500 **less** than the order total."
- claim inflation → "The screenshot claims Rs 5,000 but your records show Rs 4,500 was received." ← the tell for a doctored screenshot; word it as a *discrepancy between claim and record*, never as an accusation.
- overpayment → "Rs 200 **more** than the order total. You may owe a refund."

**③ Evidence table — the structural rule that encodes your architecture.**

Three columns, always in this order: **Field | Screenshot (claim) | Your records | Result**. The middle column is styled as *unverified*: lighter text, a dashed left border, and the column header literally reads "Screenshot (claim)". The third column is styled as *authoritative*: normal weight, solid border, header "Your records". Never render a green tick in the claim column — only the Result column carries a verdict. **This makes "no screenshot‑derived signal may alone establish that payment occurred" a visible property of the layout**, not a paragraph in a README. It is also the single best thing to point at when a judge asks "how do you stop someone photoshopping a receipt?"

When there is no matching transaction (UNMATCHED), the third column shows an em dash and a muted "no candidate found" — not an empty cell. An empty cell reads as a rendering bug.

Mark up as a real `<table>` with `<th scope="row">` for the field name, or as a `<dl>` for the mobile stacked layout. Do not use `<div>` soup — screen readers need the row association to say "Sender name, screenshot MUHAMMAD A., your records Muhammad Ahmed, close match".

**④ Reason codes.** Plain English sentence first, stable code second in a monospace muted chip. The code is what your team greps in logs and what the evidence JSON contains; the sentence is what the merchant reads. Suggested: `AMT_EXACT`, `AMT_UNDER`, `AMT_CLAIM_INFLATED`, `AMT_OVER`, `NAME_EXACT`, `NAME_FUZZY`, `NAME_MISMATCH`, `TS_IN_WINDOW`, `TS_OUT_OF_WINDOW`, `REF_EXACT`, `REF_ABSENT`, `TXN_ALREADY_ALLOCATED`, `NO_CANDIDATE`, `OCR_LOW_CONFIDENCE`. Keep the list **short, closed, and versioned alongside the rules engine** — the frontend imports the label map, the backend owns the codes.

**⑤ Tamper observations behind progressive disclosure.** Collapsed by default, with a count in the summary and a standing subtitle: *"Observations about the image file. These are not proof of tampering and do not, by themselves, change the decision."* Use a native `<details>`/shadcn `Collapsible` with `aria-expanded`. **This is the most dangerous section in the product** — an "ELA anomaly detected" line rendered in red next to a VERIFIED banner will be misread by a merchant, and by a judge, as an accusation. Keep it grey, keep it neutral, keep it collapsed, and never colour it with a verdict colour.

**⑥ Provenance footer.** Decision ID, rules version, engine version, timestamp with an explicit timezone (`PKT`), and a **Copy evidence JSON** button. This is a small amount of work that pays off twice: it demonstrates the reproducibility claim, and during Q&A you can copy the JSON and show it. Free credibility.

### 5.3 Visual hierarchy

Weight the screen so an unfamiliar reader parses it in under three seconds:

1. State chip — largest text on the page (`text-2xl`/`text-3xl`), icon at `size-7`+.
2. The one‑sentence explanation — `text-lg`, dark neutral, never coloured.
3. Recommended action button — the only filled button above the fold.
4. Amount band — `text-xl` numerals, **tabular figures** (`font-variant-numeric: tabular-nums`) so Rs amounts align.
5. Evidence table — body size, generous row height (48px+), the Result column right‑aligned so ticks/crosses form a scannable vertical line.
6. Reason codes, observations, provenance — progressively quieter.

Format currency with `Intl.NumberFormat('en-PK', { style: 'currency', currency: 'PKR' })` and times with `Intl.DateTimeFormat` and an explicit `timeZone: 'Asia/Karachi'`. Do not hand‑roll `Rs ` + `toFixed(2)`; and never render a raw ISO timestamp on the merchant screen.

> **ANTI‑PATTERNS for this screen:** a big score/gauge/speedometer; a red "FRAUD" stamp; showing the model's raw OCR JSON as the primary content; "AI Confidence: High" with nothing behind it; a verdict with no matched transaction ID shown; the word "fraud" anywhere in merchant‑facing copy (it is an accusation about a *person*; you are reporting a *mismatch between a claim and a record*). Prefer "could not be confirmed", "does not match", "already used".

---

## 6. Accessibility and colour — including the projector

### 6.1 One state registry, imported everywhere

Every state's label, icon, colour and action lives in **one file**. The badge, the faceted filter, the result banner, the dashboard tile and the empty state all import it. This is exactly how `shadcn-admin` does it (`src/features/tasks/data/data.tsx` exports a `statuses` array of `{label, value, icon}` consumed by both the table column and the faceted filter). Copy the pattern, change the data.

```tsx
// src/lib/verification-states.tsx
import { CheckCircle2, AlertTriangle, Copy, SearchX, UserSearch } from 'lucide-react'

export const VERIFICATION_STATES = [
  { value: 'VERIFIED',     label: 'Verified',     icon: CheckCircle2,
    sentence: 'Payment confirmed against your records.',
    action: 'Release the order',
    cls: 'text-emerald-800 bg-emerald-50 border-emerald-700 dark:text-emerald-200 dark:bg-emerald-950' },
  { value: 'UNMATCHED',    label: 'Not found',    icon: SearchX,
    sentence: 'No transaction in your records matches this screenshot.',
    action: 'Ask for the transaction ID',
    cls: 'text-slate-800 bg-slate-100 border-slate-600 dark:text-slate-200 dark:bg-slate-800' },
  { value: 'SUSPICIOUS',   label: 'Suspicious',   icon: AlertTriangle,
    sentence: 'The screenshot disagrees with your records.',
    action: 'Hold — do not release',
    cls: 'text-amber-900 bg-amber-50 border-amber-700 dark:text-amber-200 dark:bg-amber-950' },
  { value: 'DUPLICATE',    label: 'Already used', icon: Copy,
    sentence: 'This transaction is already allocated to another order.',
    action: 'Hold — already used',
    cls: 'text-violet-900 bg-violet-50 border-violet-700 dark:text-violet-200 dark:bg-violet-950' },
  { value: 'NEEDS_REVIEW', label: 'Needs review', icon: UserSearch,
    sentence: 'A person should check this one.',
    action: 'Send to review',
    cls: 'text-sky-900 bg-sky-50 border-sky-700 dark:text-sky-200 dark:bg-sky-950' },
] as const
```

### 6.2 Colour semantics — the opinionated bit

- **Green is reserved for `VERIFIED` and nothing else.** Not for "OCR succeeded", not for a completed progress bar, not for a matched field in the *claim* column.
- **Red is reserved for system failure** (network down, 500, upload rejected). If red also means SUSPICIOUS, then a failed API call looks like a fraud verdict on a projector at 10 metres. Give SUSPICIOUS **amber** — the semantics you want are *stop and check*, not *error*.
- **DUPLICATE gets violet**, deliberately outside the red/amber/green axis. Duplicate is not a severity judgement; it is a *factual* state ("this transaction is already spoken for"). Distinct hue = instantly distinguishable in the history table.
- **UNMATCHED gets neutral grey.** Absence of evidence is not evidence. Grey is the honest colour.
- **NEEDS_REVIEW gets blue** — the universal "queued for a human" colour.

Amber vs green are the two most commonly confused hues for deuteranopia (~8% of men). They are also the two that a cheap projector's colour profile mangles most. Hence the next rule.

### 6.3 Never colour alone — WCAG 1.4.1

Every state carries **three** cues: colour + a **distinct icon silhouette** + a **text label**. WCAG 1.4.1 requires that colour is not the only visual means of conveying information. Pick icons with different *outlines*, not different glyphs inside the same circle: circle‑with‑tick, triangle, two overlapping squares, magnifier‑with‑cross, person‑with‑magnifier. If you squint until the icons are 8px blobs and two states look the same, change one.

Add a fourth cue for the result view specifically: a **4px left border** on the verdict banner in the state colour, so peripheral vision picks up the verdict from across the room.

GOV.UK's tag guidance is the right instinct here: keep the number of statuses to the minimum, keep a tag's colour consistent everywhere it appears, use sentence case, use adjectives not verbs ("Verified", not "Verify"), and **never make a status tag a link or button** — it will be clicked and nothing will happen.

### 6.4 Contrast, and surviving a projector

- Text: **4.5:1** minimum (WCAG 1.4.3). Icons, chip borders and the Result column glyphs are non‑text and need **3:1** (1.4.11).
- **Projectors crush contrast and shift hue.** In practice: never use Tailwind `*-400` or `*-500` text on white; use `*-800`/`*-900` text on `*-50`/`*-100` fills with a `*-700` border. That combination is ~7:1+ and survives a washed‑out beam.
- **Avoid pure yellow on white and light green on white** — the two that vanish first under projector gamma.
- Test the real thing: turn your laptop brightness to 40%, sit 3 metres back, and read the result view. If you cannot name the verdict in one second, the design is wrong.
- Reflow (WCAG 1.4.10): no horizontal scrolling at 320px‑equivalent width. Wide things — the evidence table, the history table — go inside `overflow-x-auto` containers; the page body never scrolls sideways.

### 6.5 The rest of the a11y baseline (cheap, do it)

- Reuse `skip-to-main.tsx` from `shadcn-admin` verbatim.
- Every icon‑only button gets `aria-label`; every decorative icon gets `aria-hidden="true"`.
- Verdict arrival must be announced: wrap the verdict sentence in `role="status"` (polite live region) so a screen‑reader user hears the result when the mutation resolves.
- Visible focus: keep shadcn's `focus-visible:ring-2 focus-visible:ring-offset-2`. Do not `outline: none` anything.
- The dropzone must be operable by keyboard — `react-dropzone`'s root handles this; if you hand‑roll, the drop area must contain a real focusable control, not a `<div onClick>`.
- Respect `prefers-reduced-motion` for the scanning animation in §8 — one media query.

---

## 7. Status and history UI — what to reuse from `satnaing/shadcn-admin`

The repo today runs Vite 8, React 19.2, Tailwind 4.2, TanStack Router 1.168, TanStack Query 5.99, **TanStack Table 8.21**, TypeScript ~6.0.3, Vitest 4 with browser mode. That is essentially the stack above, which is why it is worth copying rather than admiring.

### 7.1 Copy verbatim

| Path | Why |
|---|---|
| `src/components/data-table/column-header.tsx` | sortable header w/ dropdown |
| `src/components/data-table/faceted-filter.tsx` | **the faceted filter** — popover + `Command` + checkbox list + selected‑count badges, driven by `column.getFacetedUniqueValues()` |
| `src/components/data-table/toolbar.tsx` | search input + `filters[]` array of `{columnId, title, options}` + Reset |
| `src/components/data-table/pagination.tsx`, `view-options.tsx` | done, working |
| `src/hooks/use-table-url-state.ts` | syncs filters/pagination/global filter into URL search params |
| `src/components/layout/*`, `skip-to-main.tsx`, `long-text.tsx`, `confirm-dialog.tsx` | sidebar shell, a11y, truncation |
| `src/main.tsx` QueryClient + `QueryCache.onError` 401 handling | see §9 |

The toolbar's filter API is already exactly what you need:

```tsx
<DataTableToolbar
  table={table}
  searchPlaceholder="Search by order, sender or reference…"
  filters={[
    { columnId: 'status', title: 'Result', options: VERIFICATION_STATES.map(s => ({ label: s.label, value: s.value, icon: s.icon })) },
    { columnId: 'rail',   title: 'Rail',   options: RAILS },
  ]}
/>
```

One `VERIFICATION_STATES` array feeds the badge, the filter and the result banner. That is the payoff of §6.1.

### 7.2 Rebuild

- `src/features/tasks/**` → `src/features/verifications/**`. Keep the file *shape* (`columns.tsx`, `*-table.tsx`, `data/schema.ts` with a zod schema); replace the content. Your zod schema should be generated from or checked against the FastAPI OpenAPI schema so a backend field rename breaks the build, not the demo.
- Columns: `created_at` (relative + absolute on hover), `order_id`, `sender (claimed)`, `amount` (tabular‑nums, right‑aligned, with the under/over delta as a small suffix), `rail`, `status` badge, expander.
- The dashboard: reuse the `recharts` card layout from `features/dashboard`, but make the tiles *state counts* (5 tiles matching the 5 states), each clickable → navigates to `/verifications?status=DUPLICATE`. Deep‑linkable filters are a demo superpower: you can jump straight to the interesting rows instead of scrolling.

### 7.3 Delete

Clerk (`@clerk/react`), `features/chats`, `features/users`, `features/apps`, the RTL `DirectionProvider` and `FontProvider`, `input-otp`, `react-day-picker` if you have no date filter. Run `npx knip` (already configured in the repo) to find the rest. **Dead code in a hackathon repo is a liability** — a judge who opens `features/chats` learns you copied a template and didn't read it.

### 7.4 TanStack Table 8 vs 9 (contested)

`@tanstack/react-table` latest is **9.1.2**, but every shadcn data‑table example, and `shadcn-admin` itself, targets v8. **Pin `^8.21.3`.** A major‑version migration mid‑hackathon to gain nothing user‑visible is the definition of a bad trade. Note it in the README as a known deferred upgrade — that is a better look than a half‑migrated table.

### 7.5 Expandable evidence row

The point of the history table is that a merchant can expand a row and see the same evidence table from §5 without leaving the list.

```tsx
const table = useReactTable({
  data, columns,
  getRowCanExpand: () => true,
  getExpandedRowModel: getExpandedRowModel(),
  getFacetedRowModel: getFacetedRowModel(),
  getFacetedUniqueValues: getFacetedUniqueValues(),   // free facet counts
  // ...
})

{table.getRowModel().rows.map(row => (
  <Fragment key={row.id}>
    <TableRow data-state={row.getIsSelected() && 'selected'}>…</TableRow>
    {row.getIsExpanded() && (
      <TableRow>
        <TableCell colSpan={row.getVisibleCells().length} className="bg-muted/40 p-0">
          <EvidenceTable evidence={row.original.evidence} compact />
        </TableCell>
      </TableRow>
    )}
  </Fragment>
))}
```

The expander cell must be a real `<button>` with `aria-expanded={row.getIsExpanded()}` and an `aria-label` like `"Show evidence for order 4471"`. Anti‑pattern: a clickable chevron `<div>`.

### 7.6 Client‑side vs server‑side filtering

**Recommendation: client‑side.** Fetch up to ~500 verifications and let TanStack Table do filtering, sorting and faceting in the browser. You get `getFacetedUniqueValues()` counts for free (the "3" next to DUPLICATE in the filter popover), instant interaction with no spinner, and no pagination contract to negotiate with the backend. Server‑side filtering means either giving up facet counts or adding a `/verifications/facets` endpoint — real work for a dataset that will have 40 rows on demo day. Document the ceiling in the README ("client‑side filtering up to 500 rows; server‑side pagination is the next step") so the limitation is a stated design decision rather than an oversight.

---

## 8. Loading, empty, error, optimistic

### 8.1 Time budget (Nielsen's limits, which are 30 years old and still correct)

| Elapsed | Perception | What you show |
|---|---|---|
| < 0.1s | instantaneous | nothing |
| < 1s | flow of thought preserved | nothing, or a subtle inline spinner |
| 1–10s | attention holds if you show something | **staged progress** |
| > 10s | attention breaks; user switches tasks | percent‑done or an ETA, plus a way out |

Percent‑done indicators are recommended for operations over ~10 seconds; users are demonstrably more satisfied and wait longer when a wait animation explains a >1s delay. Verification lands squarely in the 1–10s band and can spill past 10s on venue wifi, so it needs the full treatment.

### 8.2 The verification wait — make it feel intentional

**A bare spinner for eight seconds reads as "broken".** Replace it with a **narrated stepper** that shows the merchant that a *pipeline* is running — which is also the best possible advertisement for your architecture during a demo. Judges watching a five‑step stepper labelled "Reading screenshot → Matching your transactions → Checking for reuse → Applying rules v1.4.0" learn what the product does without you saying a word.

```
[✓] Uploading screenshot            0.4s
[✓] Reading the screenshot           2.1s
[●] Matching against your records    …          ← current, animated
[ ] Checking for reuse
[ ] Applying decision rules v1.4.0
```

Rules for the stepper:

1. **Prefer real stages.** If the backend returns `stage` (Shape B in §2.3), drive the stepper from it. This is worth asking the Phase 3 owner for — it's one enum field.
2. If you must simulate, **never let the fake stepper complete before the real response arrives.** Cap the simulated progress at the last step and hold there. A stepper that shows "Done" while the screen hasn't changed is worse than a spinner.
3. Keep a live region: `<div role="status" aria-live="polite">` announcing the current stage.
4. At **10s**, swap the copy to "Still working — the AI model is taking longer than usual." At **25s**, offer **Keep waiting** / **Cancel**. At **60s** (the XHR timeout), fail cleanly into the error state with a **Try again** button that actually retries.
5. Keep the screenshot preview visible the whole time, ideally with a slow scanning shimmer over it (gated behind `prefers-reduced-motion: no-preference`). It anchors the wait to *this specific image*.
6. The upload bar (§3.5) occupies step 1 only.

### 8.3 Skeletons vs spinners (contested — here's the rule)

Skeleton screens are contested in the research (they can *increase* perceived wait when overused). Use this decision rule:

- **< 1s** → nothing.
- **Known‑shape content that's arriving** (history table, dashboard tiles) → **skeleton**, shaped like the real thing, same row height, so nothing shifts when data lands. Layout shift on arrival is the thing skeletons are actually for.
- **Multi‑second pipeline with distinct phases** (verification) → **narrated stepper**, not a skeleton.
- **Indeterminate short action** (login submit) → spinner *inside the button*, button disabled, label changes to "Signing in…". Never a full‑page overlay for a form submit.

### 8.4 Empty states

Every empty state gets: an icon, a one‑line explanation, and **one action**.

- History, no rows ever → "No verifications yet. Upload a payment screenshot to get started." + **Verify a payment** + **Try a sample screenshot**. That second button is your demo reset hatch (§10) hiding in plain sight.
- History, filters exclude everything → "No verifications match these filters." + **Clear filters** (`table.resetColumnFilters()`). Distinguish these two states — showing "no verifications yet" when the user has a DUPLICATE filter on is a classic bug and looks like data loss on stage.

### 8.5 Errors — four classes, four treatments

| Class | Detection | Treatment |
|---|---|---|
| Offline / network | `navigator.onLine === false`, or `HttpError(0)` | Persistent banner "You're offline." Retry when back online. Do **not** navigate away. |
| 401 expired | status 401 | Global handler → toast + redirect (§9). `retry: false`. |
| 422 bad input | status 422 | **Inline, on the dropzone**: "That file isn't a readable image" / "The screenshot is too blurry to read (OCR confidence 0.21). Try a clearer photo." Never a toast — the user must see it next to the control they need to fix. |
| 5xx / model failure | status ≥ 500 | Error card in the result slot: what failed, what it doesn't mean, one **Try again**. |

The 5xx copy matters for this domain: **"We couldn't complete the check" must never look like "the payment is fake."** Render it in *neutral grey with a red icon*, structurally distinct from the five verdict cards. Explicit copy: *"This is a system error, not a verdict on the payment."*

Wrap each route in an error boundary (TanStack Router `errorComponent`) so a render crash in the evidence table degrades to one card, not a white screen.

### 8.6 Optimistic updates — mostly, don't

**Never optimistic:** the verification result. You cannot guess a verdict, and an optimistically‑rendered "VERIFIED" that flips to "DUPLICATE" is the single worst thing this UI could do. It also violates the architecture: the client would be establishing that payment occurred.

**Optimistic is fine** for cheap, reversible, non‑verdict actions: marking a verification as resolved/acknowledged, adding a note, dismissing from a queue. Standard `onMutate` → snapshot → `setQueryData` → roll back in `onError` → `invalidateQueries` in `onSettled`.

Cheaper alternative that costs nothing and covers 90% of the value: use `mutation.variables` while `isPending` to render the pending item in a muted style. No cache surgery, no rollback bug.

---

## 9. Auth on the client

### 9.1 Storage (contested — with a clear recommendation and a clear hackathon fallback)

OWASP's position is that session identifiers should not sit in `localStorage`, because JavaScript can always read it; `httpOnly` cookies mitigate that. Both are XSS‑exposed to some degree, but `httpOnly` raises the bar meaningfully; cookies then need `SameSite` and/or CSRF tokens.

**Correct design (do this if you have half a day):**

- **Access token: in memory only** — a module‑scoped variable plus a Zustand store. Never persisted. Short TTL (15 min).
- **Refresh token: `httpOnly; Secure; SameSite=Lax` cookie set by FastAPI**, path‑scoped to `/api/auth/refresh`.
- On app boot, call `POST /api/auth/refresh` once; if it succeeds you're logged in, if it 401s you show the login page. This survives page reload without any token touching JS.
- The Vite proxy (§1.4) makes this work in dev, because dev is same‑origin. This is a concrete reason the proxy is not optional.

**Hackathon fallback (be explicit about it):** one JWT with a 12‑hour expiry in **`sessionStorage`**, plus the global 401 handler below. `sessionStorage` over `localStorage` because it dies with the tab, so a shared demo laptop doesn't stay logged in. Write the tradeoff in the README: *"The access token is held in sessionStorage. This is XSS‑exposed; the production design is an in‑memory access token with an httpOnly refresh cookie. Deferred for time."* Judges reward a named, understood limitation far more than they punish it.

> **ANTI‑PATTERN:** storing the JWT in a **non‑`httpOnly` cookie via `document.cookie`** and calling it "cookie‑based, therefore secure". It is exactly as readable by JavaScript as `localStorage`, plus it now rides along on every request. `shadcn-admin`'s `auth-store.ts` does precisely this (`setCookie(ACCESS_TOKEN, ...)` from a `js-cookie`‑style helper) — it's a template convenience, not a security design. If you copy that file, understand what you copied.

### 9.2 Route protection

Use TanStack Router's `beforeLoad` guard on a pathless layout route:

```tsx
// src/routes/_authenticated/route.tsx
export const Route = createFileRoute('/_authenticated')({
  beforeLoad: ({ context, location }) => {
    if (!context.auth.isAuthenticated) {
      throw redirect({ to: '/sign-in', search: { redirect: location.href } })
    }
  },
  component: AuthenticatedLayout,
})
```

with the router context typed via `createRootRouteWithContext<{ auth: AuthState; queryClient: QueryClient }>()`. Every protected page then just lives under `routes/_authenticated/`. One guard, zero per‑page checks, and the `redirect` search param means a mid‑demo expiry bounces the merchant back to exactly where they were.

### 9.3 Expiry mid‑demo — the concrete defences

**Defence 1 — a global 401 handler on the QueryCache.** This is the single best thing in the reference repo; lift it:

```ts
queryCache: new QueryCache({
  onError: (error) => {
    if (isHttpError(error) && error.status === 401) {
      toast.error('Session expired — signing you back in')
      useAuthStore.getState().auth.reset()
      router.navigate({ to: '/sign-in', search: { redirect: router.history.location.href } })
    }
  },
})
```

Do the same in `defaultOptions.mutations.onError` — a 401 on the *upload* mutation is the one that will actually happen, and it will not go through `QueryCache`.

**Defence 2 — pre‑emptive refresh.** Decode `exp` from the JWT (`jwt-decode`, or just `JSON.parse(atob(t.split('.')[1]))` — you are reading, not verifying) and refresh at `exp - 60s`. Costs ten lines.

**Defence 3 — demo‑day token TTL.** Set the backend access token to 12 hours for the demo build. Zero risk, removes the entire failure mode. Do it in config, not in code, so it isn't shipped as a "feature".

**Defence 4 — never destroy a rendered result on a 401.** If the merchant is looking at a verdict and a background refetch 401s, redirecting mid‑sentence is a disaster on stage. Guard the redirect: if the current route is `/verifications/$id` and we already have data, show a non‑blocking "Session expired — sign in to continue" banner instead of navigating.

**Defence 5 — the demo account is seeded and idempotent.** `merchant@proofpay.dev` / a password nobody has to type carefully, pre‑filled in dev via `VITE_DEMO_MODE`. Do not type a password on stage.

---

## 10. Demo‑proofing the frontend

Judges will watch on a projector or a large TV, at a resolution you have never tested, possibly mirrored (which forces the laptop to the *lower* of the two resolutions — often 1366×768), possibly at 16:10 or 4:3, possibly with overscan cropping the outer 3% of the screen. Plan for it.

### 10.1 Layout that cannot break

- **Design at 1280×720; verify at 1024×768 and 1366×768.** Every important control must be above the fold at 1024×768 — that includes the verdict banner *and* its action button.
- **Overscan margin:** never place anything critical within 24px of the viewport edge. Sticky headers/footers get `pb-6` more than looks necessary.
- **A constrained content column:** `mx-auto w-full max-w-5xl px-4 md:px-6`. Never a full‑bleed layout that stretches an evidence table to 2400px on a wide TV — the eye cannot track a row across that width.
- **`min-h-dvh`, not `min-h-screen`/`100vh`.** `vh` is wrong on mobile with a dynamic URL bar and can be wrong on some presentation modes.
- **No fixed pixel heights** on anything containing text. `min-h-*` + `flex` only.
- **Wide content scrolls inside itself:** the evidence table and history table go in `overflow-x-auto` wrappers. The page body must never scroll horizontally.
- **Test browser zoom at 67%, 100%, 150% and 200%** before demo day. Presenters routinely zoom to 150% so the back row can read, and that is when three‑column layouts collapse.

### 10.2 A "Present mode" toggle (30 minutes, huge payoff)

```css
:root { --pp-scale: 1; font-size: calc(16px * var(--pp-scale)); }
html[data-density="present"] { --pp-scale: 1.25; }
```

Bind it to a header button and to a keyboard shortcut. Because Tailwind v4 sizes in `rem`, everything scales coherently — unlike browser zoom, which also scales your carefully chosen max‑widths. Under present mode, also bump the verdict chip to `text-3xl` and icons to `size-8`.

### 10.3 Keyboard‑only operation

Assume the touchpad misbehaves or the presenter is using a clicker.

- **Tab order must be sane on every screen.** Walk each flow with Tab only, once, the day before. This takes ten minutes and always finds something.
- Shortcuts, registered globally and listed in a `?` dialog: `u` = upload/focus dropzone, `Ctrl+V` = paste (already global), `Enter` = primary action on the result screen, `g h` = go to history, `/` = focus search, `Esc` = close dialogs, `r` = demo reset (guarded).
- **Guard shortcut handlers**: ignore key events when `event.target` is an `input`/`textarea`/`[contenteditable]`, or `/` will be unusable in the search box.
- Reuse `shadcn-admin`'s `command-menu.tsx` (`cmdk`) for `Cmd/Ctrl+K` navigation. It is copy‑paste, it works, and driving a demo entirely from a command palette looks extremely deliberate.

### 10.4 Reset control

Bind a **Reset demo** button (visible only when `import.meta.env.VITE_DEMO_MODE === '1'`) to:

```ts
await api.post('/demo/reset')      // backend re-seeds merchant txns, clears allocations
queryClient.clear()                 // drop all cached server state
router.navigate({ to: '/' })
```

Two failure modes it fixes: (a) the duplicate‑detection demo only works *once* per transaction, because your DB constraint has now allocated it — without a reset you get one shot at the best part of the demo; (b) a botched practice run leaves the history table full of junk rows.

Also seed **fixture screenshots into `public/demo/`** and give each a button: *"Use sample: clean Easypaisa"*, *"Use sample: altered amount"*, *"Use sample: reused transaction"*. Fetch → `new File([blob], name, {type})` → straight into the same intake hook. **Never open a native file picker on stage.** Finding a file in a picker while people watch is thirty seconds of dead air and a real chance of picking the wrong one.

### 10.5 Venue wifi will fail

This is the frontend twin of your "every dependency has a local fallback" commitment.

- `VITE_USE_FIXTURES=1` swaps the API client module for one that returns fixture JSON with a realistic 3‑second delay through the same stepper. Ten lines, one `if`, and it means you can demo the entire client with no backend and no network. Build it on day one and keep it working — it is also how you develop the result view before Phase 3 lands.
- **Self‑host fonts or use the system stack** (`font-family: ui-sans-serif, system-ui, …`). A Google Fonts request on dead wifi means invisible text for three seconds during the opening shot.
- No CDN scripts. Everything bundled.

### 10.6 Demo‑day mechanics

- **Present from `npm run build && npm run preview`, not `npm run dev`.** HMR mid‑demo can white‑screen on a stale module, dev builds are slower, and dev‑only warnings clutter the console if you open it. Rehearse against the preview build. (Keep `dev` for development, obviously.)
- Top‑level error boundary with a **Reload** button, so a crash costs three seconds instead of ending the demo.
- Fresh browser profile: no extensions, no password‑manager popups, no "restore tabs", no OS notifications, Do Not Disturb on.
- Pre‑warm the app before you present: log in, run one verification, then reset. Cold caches and a cold Uvicorn worker make the first request the slowest one of the day.
- Have `/dev/states` open in a second tab — a route that renders all five verdict cards from fixtures, stacked. If the live pipeline fails, you can still show every outcome and talk through the evidence model. It doubles as your visual regression surface during development.

### 10.7 Testing (matching the team's stated priority)

Cheap and high‑value, in priority order:

1. **Fixture‑driven render tests for the result view — one per state.** `render(<VerificationResult result={fixtures.duplicate} />)` and assert the visible verdict text, the recommended action, and that the evidence table has a row per field. Five tests, catches the majority of what can go wrong on the screen that matters.
2. **A test that fails if a fraud percentage appears**: assert no rendered text matches `/\d+\s*%/` in the verdict banner. It sounds silly; it enforces a design commitment across four contributors under time pressure.
3. A test that the claim column never renders a success indicator.
4. Vitest 4 browser mode with `@vitest/browser-playwright` (already configured in `shadcn-admin`) if you want real DOM; jsdom is fine and faster to start.

Skip full E2E. Not worth the setup cost in the time available.

---

## 11. Anti‑pattern index (the ones specific to this product)

1. **A fraud probability percentage anywhere in the merchant UI.** §5.1.
2. **A green tick in the "Screenshot (claim)" column.** It contradicts the core architectural commitment, visually.
3. **Tamper observations styled as a verdict** — red text, expanded by default, or contributing to the headline. They are observations, collapsed, grey, with a disclaimer.
4. **Downscaling every upload by default** — silently destroys the tamper‑evidence and OCR signals Phase 4 depends on. §3.4.
5. **`localhost` in the Vite proxy target.** §1.4.
6. **`VITE_DASHSCOPE_API_KEY`.** §1.5.
7. **A bare spinner for an 8‑second AI call.** §8.2.
8. **A fake progress stepper that finishes before the real response.** §8.2.
9. **Optimistically rendering a verdict.** §8.6.
10. **Retrying 401s.** Turns a redirect into a hang. §2.2.
11. **`useEffect` + `fetch` + `setState` for the history list.** Race conditions under fast filter toggling. §2.1.
12. **`FileReader.readAsDataURL` for the preview**, or base64 JSON upload bodies. §3.3/§3.5.
13. **The word "fraud" in merchant‑facing copy.** You report a mismatch between a claim and a record; you do not accuse a person.
14. **Red doing double duty** for both SUSPICIOUS and system errors. §6.2.
15. **Opening a native file picker during the live demo.** §10.4.
16. **Upgrading to TypeScript 7 / TanStack Table 9 during the hackathon.** §1.2/§7.4.
17. **Shipping `features/chats` and Clerk from the template** because deleting felt risky. §7.3.

---

## Sources

- [Vite — server options (`proxy`, `host`, `allowedHosts`)](https://vite.dev/config/server-options) · [Vite 8.0 announcement](https://vite.dev/blog/announcing-vite8) · [Vite 8 / Rolldown coverage, InfoQ](https://www.infoq.com/news/2026/05/vite-v8-rust/)
- [FastAPI localhost vs 127.0.0.1 IPv6 conflict](https://www.technetexperts.com/fastapi-localhost-ipv6-conflict/) · [vitejs/vite discussion #7620 — proxy ECONNREFUSED](https://github.com/vitejs/vite/discussions/7620)
- [Tailwind CSS — installation with Vite (v4 plugin)](https://tailwindcss.com/docs/installation/using-vite) · [shadcn/ui — Tailwind v4](https://ui.shadcn.com/docs/tailwind-v4) · [shadcn/ui — components.json](https://ui.shadcn.com/docs/components-json) · [shadcn/ui — CLI](https://ui.shadcn.com/docs/cli)
- [Announcing TypeScript 6.0 (new defaults, strict by default)](https://devblogs.microsoft.com/typescript/announcing-typescript-6-0/) · [TypeScript 7.0 released — InfoQ](https://www.infoq.com/news/2026/08/typescript-7-released/) · [TypeScript 7.0 migration readiness / tooling blockers](https://ecorpit.com/typescript-7-migration-readiness-eslint-astro-blockers-2026/)
- [TanStack Query — Mutations](https://tanstack.com/query/latest/docs/framework/react/guides/mutations) · [TanStack Query — Polling](https://tanstack.com/query/latest/docs/framework/react/guides/polling) · [TkDodo — Why You Want React Query](https://tkdodo.eu/blog/why-you-want-react-query) · [Fixing race conditions in React with useEffect](https://maxrozen.com/race-conditions-fetching-data-react-with-useeffect)
- [TanStack Router — Authenticated Routes](https://tanstack.com/router/latest/docs/framework/react/guide/authenticated-routes)
- [satnaing/shadcn-admin](https://github.com/satnaing/shadcn-admin) (stack, `src/components/data-table/*`, `use-table-url-state.ts`, `main.tsx` QueryCache 401 handler, `auth-store.ts`)
- [web.dev — How to paste files](https://web.dev/patterns/clipboard/paste-files) · [MDN — `paste` event](https://developer.mozilla.org/en-US/docs/Web/API/Element/paste_event) · [MDN — `ClipboardEvent.clipboardData`](https://developer.mozilla.org/en-US/docs/Web/API/ClipboardEvent/clipboardData) · [W3C Clipboard API](https://www.w3.org/TR/clipboard-apis/)
- [react-dropzone](https://github.com/react-dropzone/react-dropzone) · [IMG.LY — resize & compress images in JavaScript](https://img.ly/blog/how-to-compress-an-image-before-uploading-it-in-javascript/) · [Client-side image compression with JavaScript](https://minipx.com/blog/client-side-image-compression-javascript/)
- [Jake Archibald — Fetch streams are great, but not for measuring upload/download progress](https://jakearchibald.com/2025/fetch-streams-not-for-progress/) · [Has fetch() caught up with XMLHttpRequest?](https://waspdev.com/articles/2025-10-10/has-fetch-caught-up-with-xhr)
- [MDN — `MediaDevices.getUserMedia()`](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia) · [MDN — Secure Contexts](https://developer.mozilla.org/en-US/docs/Web/Security/Secure_Contexts) · [MDN — `<input type="file">` (`capture`)](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/input/file) · [vite-plugin-mkcert](https://github.com/liuweiGL/vite-plugin-mkcert)
- [GOV.UK Design System — Summary list / check answers](https://design-system.service.gov.uk/components/summary-list/) · [GOV.UK Design System — Tag](https://design-system.service.gov.uk/components/tag/)
- [FICO — Explainable AI in fraud detection (Reason Reporter)](https://fico.com/blogs/analytics-optimization/explainable-ai-fraud-detection) · [SEON — Explainable AI in fraud & compliance](https://seon.io/resources/explainable-ai-in-fraud-and-compliance/) · [Kumo — Explainable fraud detection & compliance](https://kumo.ai/resources/learn/explainable-fraud-detection-compliance/) · [Eleken — Explainable AI UI design](https://www.eleken.co/blog-posts/explainable-ai-ui-design-xai)
- [NN/g — Response Time Limits (0.1s / 1s / 10s)](https://www.nngroup.com/articles/response-times-3-important-limits/) · [NN/g — Progress Indicators](https://www.nngroup.com/articles/progress-indicators/)
- [WCAG 2.2 SC 1.4.1 Use of Color](https://www.thewcag.com/criteria/1.4.1) · [Status indicators need more than colour](https://www.accessibility.chat/articles/when-color-coding-fails-why-status-indicators-need-more-than-pretty-colors)
- [OWASP-aligned guidance on JWT storage in the front end](https://www.cyberchief.ai/2023/05/secure-jwt-token-storage.html) · [localStorage vs cookies for JWTs](https://medium.com/cotterapp/localstorage-vs-cookies-all-you-need-to-know-about-storing-jwt-tokens-securely-in-the-front-end-277332bf9a5c)

---

## Definition of done

**Setup**
- [ ] `npm create vite` react-ts scaffold on Vite 8.2+, React 19.2, `typescript@~6.0.3` (**not** 7.x); every team member on Node ≥20.19 or ≥22.12, verified.
- [ ] Tailwind v4 via `@tailwindcss/vite`; no `tailwind.config.js`; state colour tokens defined in `@theme`.
- [ ] `shadcn init` complete; `@` path alias set in **both** `vite.config.ts` and `tsconfig.app.json`.
- [ ] Vite proxy `/api → http://127.0.0.1:8000` with `changeOrigin: true`; **no `localhost` string anywhere in the proxy config**; a teammate on a fresh clone can `npm run dev` and hit the API without touching CORS.
- [ ] `grep -rn "VITE_.*\(KEY\|SECRET\|TOKEN\)" src/ .env*` returns nothing. No model API key in the client.
- [ ] `npm run build` passes with `tsc -b` clean and `oxlint` clean.

**Server state**
- [ ] TanStack Query is the only data-fetching mechanism; zero `useEffect(() => { fetch… })` in `src/`.
- [ ] `QueryClient` configured with `retry` that excludes 401/403/422 and a shared `qk` key factory.
- [ ] Verification submission is a `useMutation`; the UI stays interactive for its full duration.
- [ ] The response contract includes `status` and `stage` so 202+poll (`refetchInterval` returning `false` on terminal status) is a drop-in.

**Upload & camera**
- [ ] All three intake paths — drop, **paste (Ctrl+V anywhere)**, file picker — funnel through one `useFileIntake` hook.
- [ ] Paste does not break normal text paste in inputs.
- [ ] Preview uses `URL.createObjectURL` with a `revokeObjectURL` cleanup; no base64 preview, no base64 upload body.
- [ ] Upload is `multipart/form-data` via XHR with real `upload.onprogress`; `Content-Type` is not set manually.
- [ ] Downscaling is **off below 4 MB**; above it, EXIF-correct resize via `createImageBitmap({ imageOrientation: 'from-image' })` **and** an `X-Client-Resized: 1` header that the backend honours. The header is documented in the API contract.
- [ ] `<input type="file" accept="image/*" capture="environment">` works on a real phone; if HTTPS is needed, certs are installed and tested **the day before**.

**The result view**
- [ ] No percentage, gauge, or score is rendered in merchant-facing UI. A test asserts this.
- [ ] Verdict banner: state chip (icon + label + colour + left border), one plain-language sentence, exactly one primary action.
- [ ] Amount band distinguishes underpayment / claim inflation / overpayment with distinct copy.
- [ ] Evidence table has columns **Field | Screenshot (claim) | Your records | Result**, in that order; the claim column is visually marked unverified and never carries a success indicator.
- [ ] Reason codes shown as plain sentence + stable code chip; the code list is shared with the backend.
- [ ] Tamper observations are collapsed by default, neutrally coloured, and carry the "not proof" disclaimer.
- [ ] Provenance footer shows decision ID, rules version, timestamp with `PKT`, and a **Copy evidence JSON** button.
- [ ] `role="status"` announces the verdict when it arrives.

**Accessibility & colour**
- [ ] One `verification-states.tsx` registry feeds the badge, faceted filter, result banner, dashboard tiles and empty states.
- [ ] Each state carries colour **+ distinct icon silhouette + text label**; green only for VERIFIED, red only for system errors.
- [ ] All text ≥ 4.5:1; icons and chip borders ≥ 3:1; verified at 40% laptop brightness from 3 m.
- [ ] No horizontal page scroll at 320px width; wide tables scroll inside `overflow-x-auto`.
- [ ] Skip-to-main link present; every icon-only button has `aria-label`; focus rings visible everywhere.

**History & dashboard**
- [ ] Data table built on `@tanstack/react-table@^8` with the `data-table/` components lifted from `shadcn-admin`.
- [ ] Faceted filter over all five states with live counts from `getFacetedUniqueValues()`.
- [ ] Filters live in URL search params — `/verifications?status=DUPLICATE` is deep-linkable and used in the demo script.
- [ ] Expandable row renders the same evidence table, toggled by a real `<button>` with `aria-expanded`.
- [ ] Dashboard tiles are the five state counts and each links into the filtered table.
- [ ] `npx knip` reports no unused template code; Clerk, chats, users, RTL/font providers deleted.

**States**
- [ ] Verification wait shows a named-stage stepper, never a bare spinner; the simulated stepper cannot complete before the real response.
- [ ] "Still working" copy at 10s; Keep waiting / Cancel at 25s; clean failure at 60s.
- [ ] Skeletons (not spinners) for the history table and dashboard, shaped to prevent layout shift.
- [ ] "No verifications yet" and "no rows match filters" are distinct empty states with distinct actions.
- [ ] Four error classes handled distinctly; 5xx copy explicitly says it is a system error, not a verdict.
- [ ] No optimistic rendering of any verdict.

**Auth**
- [ ] Route protection via a single `_authenticated` `beforeLoad` guard with `redirect({ search: { redirect } })`.
- [ ] Global 401 handler on both `QueryCache.onError` and `mutations.onError`; 401s are not retried.
- [ ] Token storage decision made, implemented, and its tradeoff written in the README.
- [ ] Demo-build token TTL ≥ 12 h; a 401 during a rendered result shows a banner rather than navigating away.

**Demo-proofing**
- [ ] Verified at 1024×768, 1366×768 and 1920×1080, and at 67% / 150% / 200% browser zoom.
- [ ] Present mode (`data-density="present"`) toggle works and is bound to a shortcut.
- [ ] Every flow completable with keyboard only; walked end-to-end once, the day before.
- [ ] **Reset demo** control clears backend seed + `queryClient.clear()` + returns home, and the duplicate-detection scenario is repeatable.
- [ ] Three sample screenshots in `public/demo/` with one-click buttons; the demo never opens a native file picker.
- [ ] `VITE_USE_FIXTURES=1` runs the full client with no backend and no network.
- [ ] Fonts self-hosted or system stack; zero CDN requests at runtime.
- [ ] Top-level error boundary with a Reload action; demo runs from `vite preview`, rehearsed at least twice.
- [ ] `/dev/states` renders all five verdicts from fixtures and is open in a second tab on demo day.
- [ ] Five fixture render tests pass, including the "no percentage in the verdict banner" assertion.