# Phase 4 — Demo Dataset — Best Practices

## 0. The decision summary (read this if you read nothing else)

| Question | Decision | Why |
|---|---|---|
| How to render receipts | **HTML/CSS + Jinja2 → Playwright headless Chromium**, one browser process, `device_scale_factor=3` | Real layout engine, real fonts, CSS you can iterate on in a browser tab; installs cleanly on Windows with `playwright install chromium --only-shell` |
| Branding | **Invent fictional rails** (`SabzPay`, `NoorPay`, `Indus Bank`). Real rail names appear only as *data values* (`rail: "raast"`), never as logos/wordmarks/colour systems in pixels | Zero trademark risk, zero passing-off risk, and judges read it as deliberate |
| How to tamper | **Post-render, in pixel space, with Pillow** — never by editing the HTML and re-rendering | Re-rendering produces a *perfectly consistent* image; your tamper detector would be validated against nothing |
| Randomness at seed time | **None.** Faker runs once, at authoring time; its output is frozen into a committed `manifest.json` | Kills version drift, locale drift, and "it generated different names on Ali's laptop" |
| Images in git | **Commit them.** No LFS. Budget ≤ 250 KB/image, ≤ 8 MB total | LFS is the single most reliable way to give one teammate a broken checkout |
| "Now" | **Fixed anchor** `2026-08-20T14:05:00+05:00`, all fixture times as offsets from it; a `Clock` port so demo mode can move the anchor | Fixtures never go stale overnight, tests never drift |
| Same data for tests + demo | **Yes, mandatory.** One `manifest.json` drives pytest, the seeder, and the accuracy report | Divergence here is how a demo passes CI and fails on stage |

---

## 1. Generating realistic receipt images programmatically

### 1.1 The three candidates, compared honestly

| | **Playwright → Chromium screenshot** | **Pillow `ImageDraw` direct** | **SVG → raster (cairosvg / resvg)** |
|---|---|---|---|
| Layout engine | Full CSS: flexbox, grid, gradients, `border-radius`, `letter-spacing`, ellipsis | None. You compute every `x, y` yourself | Manual `x, y` positioning; no text wrap, no flow |
| Text wrapping / measurement | Free | You must call `draw.textlength()` and break lines by hand | You must pre-wrap into `<tspan>`s |
| Bold/italic | `font-weight: 600` | Load a separate `.ttf` per weight | Separate font files, plus `@font-face` support varies by renderer |
| Iteration speed | Open the HTML in Chrome, edit CSS, refresh. **This is the killer feature under time pressure** | Edit Python, re-run, squint at a PNG | Edit XML, re-run |
| Windows install | `uv add playwright && playwright install chromium --only-shell` — self-contained browser download, no system deps, no PATH surgery | `uv add pillow` — trivial | `cairosvg` needs **libcairo/GTK DLLs on Windows** — the classic `OSError: no library called "cairo-2" was found`. `resvg-py` avoids it but is less known |
| Disk cost | ~100 MB (headless shell) / ~281 MB (full Chromium) | ~5 MB | ~20 MB, plus DLL pain |
| Speed for 30 images | ~8–15 s total with **one** browser reused | ~1 s | ~2 s |
| Post-processing / tampering | Poor — it's a browser | **Excellent** — this is exactly what Pillow is for | Poor |

### 1.2 Recommendation

**Use Playwright for the base render, Pillow for everything after the render.** They are not competitors; they are two stages of the same pipeline.

```
Jinja2 template + case data
        │
        ▼  (Playwright, once, at authoring time)
   base PNG 1080×2340
        │
        ├─► genuine   → delivery step (WhatsApp-grade JPEG re-encode)
        └─► tampered  → Pillow patch → delivery step
```

Reject `cairosvg` outright for this team: a Windows DLL failure on one of four laptops costs more hackathon hours than the entire rendering task is worth. Reject pure-Pillow for the base receipt: you will spend your afternoon hand-computing baseline offsets instead of building the reconciler.

**The cheap version if Playwright download is blocked** (corporate proxy, flaky wifi at the venue): fall back to Pillow with a hard-coded field-position table. Write it as an adapter — `render.py` exposing `render(case) -> bytes` with a `PLAYWRIGHT` and a `PILLOW` backend — so it matches the project's existing "every external dependency behind an adapter with a working local fallback" commitment. The Pillow backend produces uglier receipts; the pipeline still runs.

### 1.3 Concrete render code

`proofpay/demo/render.py`:

```python
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright

TPL_DIR = Path(__file__).parent / "templates"
_env = Environment(loader=FileSystemLoader(TPL_DIR), autoescape=select_autoescape())

# Reduce (not eliminate) cross-machine text rendering variance.
CHROMIUM_ARGS = [
    "--font-render-hinting=none",
    "--disable-font-subpixel-positioning",
    "--disable-lcd-text",
    "--force-color-profile=srgb",
    "--hide-scrollbars",
]

def render_all(cases, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(args=CHROMIUM_ARGS)          # ONE browser
        ctx = browser.new_context(
            viewport={"width": 360, "height": 780},              # CSS px
            device_scale_factor=3,                               # -> 1080×2340
            is_mobile=True, has_touch=True,
            color_scheme="light",
            locale="en-PK",
            timezone_id="Asia/Karachi",
            reduced_motion="reduce",
        )
        page = ctx.new_page()
        for case in cases:
            html = _env.get_template(case.template).render(**case.visible)
            page.set_content(html, wait_until="load")
            page.evaluate("document.fonts.ready")                # don't screenshot mid-font-swap
            page.screenshot(
                path=out_dir / f"{case.id}.base.png",
                type="png", full_page=False, scale="device",
                animations="disabled",
            )
        ctx.close(); browser.close()
```

Two traps this code closes:

- **`document.fonts.ready`** — without it a fast machine screenshots before the webfont swaps in, and you get a fallback-font receipt on CI and a correct one locally.
- **One browser for the whole batch** — launching Chromium per image turns 10 s into 3 minutes.

### 1.4 Fonts

Bundle the font file in the repo (`proofpay/demo/fonts/`) and reference it via `@font-face` with a `file://` or base64 `src`. **Do not** use `local("Roboto")` or a bare `font-family: Roboto, sans-serif` — that resolves differently on each teammate's Windows install and is the number-one cause of "the receipt looks different on my machine".

Inter and the Noto family are both under the **SIL Open Font License**, which explicitly permits bundling and redistributing the font alongside software, provided you ship the copyright notice and licence text. Drop `OFL.txt` next to the `.ttf` and you are done.

```css
@font-face {
  font-family: "PPDemo";
  src: url("fonts/Inter-Regular.ttf") format("truetype");
  font-weight: 400; font-display: block;
}
body { font-family: "PPDemo", sans-serif; }   /* no local() escape hatch */
```

---

## 2. Making receipts look real without infringing branding

### 2.1 What actually makes a screenshot read as a phone screenshot

Judges and your vision model both key on the same handful of cues. Get these and you don't need the logo:

| Cue | Concrete spec |
|---|---|
| Aspect ratio | **1080×2340 (19.5:9)** — the modern Android default. 1080×1920 reads as "2016 phone" |
| Full-bleed, square corners | Real screenshots are rectangular. **Do not round the image corners** — a rounded-corner PNG with a transparent surround is the single most common tell that an image is a mockup |
| Status bar | 24–28 CSS px tall: left = clock (`2:05 PM`) + one or two notification dots; right = signal triangle, wifi arc, battery pill with a `%`. Author these as inline SVG paths yourself — 20 minutes of work, zero asset provenance questions |
| Gesture nav pill | 3–4 px tall, ~110 px wide, centred, bottom, `border-radius: 2px` |
| App chrome | Back chevron + screen title left-aligned in a 56 px app bar; a "success" hero (circle + tick) above the amount; a `Share` / `Download receipt` row at the bottom |
| Typography rhythm | Amount at ~34 px semibold; field labels ~12 px, `#6B7280`; field values ~14 px, `#111827`; 1 px `#E5E7EB` dividers |
| Field set (wallet) | Transaction ID, Date & Time, Sent to (name + masked mobile `0301-****567`), Sent from, Amount, Fee, Total, Status, Balance (sometimes masked) |
| Field set (bank/Raast-style) | Reference / RRN, Beneficiary Name, Beneficiary IBAN (`PK…`, 24 chars), Bank, Amount, Value Date, Status |
| Locale realism | `PKR 5,000` or `Rs. 5,000` — thousands separators, no decimals for round amounts; `20 Aug 2026, 02:05 PM` (12-hour, PKT) |

### 2.2 Branding: the clear recommendation

**Invent fictional brands. Do not reproduce Easypaisa, JazzCash, or any bank's logo, wordmark, brand colour system, or screen-for-screen layout.**

The legal picture, stated plainly:

- **Trademarks** protect names, logos, icons and distinctive UI trade dress — they are precisely the layer that identifies the source of an app. Reproducing them in a demo that circulates publicly (a devpost page, a video, a GitHub repo) is the risky act.
- **Copyright** in a UI is thin — a functional layout of standard components sits much closer to fair use than an original illustration or a branded creative asset. But "thin" is not "zero", and thin-copyright arguments are a bad thing to be relying on the night before judging.
- **Nominative use is fine for facts.** Writing `rail = "easypaisa"` in a database column, or saying "ProofPay handles Easypaisa, JazzCash and Raast receipts" in your README, is factual reference to a real thing and is not infringement. Painting Easypaisa's green over a fake receipt is different in kind.

So draw the line at *pixels*:

| | Allowed | Not allowed |
|---|---|---|
| DB enum / API field | `rail: "easypaisa" \| "jazzcash" \| "raast" \| "bank_transfer"` | — |
| README / pitch | "trained and evaluated on synthetic receipts modelled on Easypaisa, JazzCash and Raast layouts" | "Easypaisa integration" (implies a relationship) |
| Rendered image | `SabzPay`, `NoorPay`, `Indus Bank Pakistan`, generic "Instant Transfer (IBFT)" | Real logos, wordmarks, brand hexes, an exact screen clone |

Pick names that are *evidently* fictional rather than near-misses. `SabzPay` is safe; `EasyPaysa` is worse than useless — a deliberate near-miss is the fact pattern trademark law is most hostile to.

**Provenance marking.** Write a `SYNTHETIC — ProofPay demo fixture` string into a PNG `tEXt` chunk on every base image, and keep `manifest.json` as the authoritative provenance record. Note honestly that the tEXt chunk **does not survive** the JPEG delivery step — that is why the manifest, not the file, is the record. Skip a visible watermark on the receipt body: it corrupts your own OCR ground truth and muddies the tamper signals. Put the "synthetic data" banner in the **UI around** the receipt instead, where judges will actually see it.

---

## 3. Generating tampered variants that leave honest forensic traces

### 3.1 The central rule

> **Tamper in pixel space, after the render. Never by changing the template data and re-rendering.**

If you change `amount: 500` to `amount: 5000` in the Jinja context and re-render, Chromium produces a flawless, internally consistent image: uniform compression history, correct font metrics, correct kerning, correct baseline. Every tamper signal you write will correctly return "no evidence of manipulation" — and you will have built a tamper detector validated against a dataset that contains no tampering. This is the defining trap of Phase 4.

### 3.2 The forensic traces worth reproducing, and how

| Trace | How a real edit produces it | How to reproduce it |
|---|---|---|
| **Local double-compression / ELA hotspot** | Editor pastes a patch, then saves the whole JPEG again — the patch has been through one more encode cycle than its surroundings. ELA keys on exactly this residual-error inconsistency | Encode **only the patch** to JPEG at a different quality/subsampling, decode it, paste it back, then encode the whole image |
| **Quantization-table mismatch** | The forger's tool (Snapseed, MS Paint, an online editor) uses a different quantization table than the phone did | Save the base image with one `qtables` preset, the patched region with another |
| **Font/metric mismatch** | The forger retypes the digits in a font that isn't the app's | Render the replacement text with a *different* bundled font (e.g. DejaVu Sans instead of Inter), or the same font at 97 % size |
| **Background-fill seam** | Rectangular fill doesn't match the app's subtle gradient/divider | Sample one background pixel and flood the patch — deliberately slightly wrong |
| **Alignment / baseline drift** | Pasted text is 1–2 px off the row baseline | Offset the paste box by `+2` px vertically |
| **Resampling blur** | Region copied from a differently-scaled source | Downscale the patch by 0.9 and upscale back with `Image.LANCZOS` before pasting |
| **Digit-count geometry** | `500` → `5,000` is *wider*; a lazy forger overlaps or clips the neighbouring glyph | Let the patch box stay the original width and allow clipping on one case |

### 3.3 Code

`proofpay/demo/tamper.py`:

```python
import io
from PIL import Image, ImageDraw, ImageFont

def _recompress(img: Image.Image, quality: int, subsampling: str) -> Image.Image:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality, subsampling=subsampling, optimize=False)
    buf.seek(0)
    return Image.open(buf).convert("RGB")

def repaint_field(
    img: Image.Image, box: tuple[int, int, int, int], text: str,
    font: ImageFont.FreeTypeFont, *,
    baseline_offset: int = 0, patch_quality: int = 72, resample_wobble: bool = True,
) -> Image.Image:
    """Overwrite a rendered field with `text`, leaving a realistic edit trace."""
    l, t, r, b = box
    src = img.crop(box)
    bg = src.getpixel((1, src.height - 2))            # deliberately naive fill
    patch = Image.new("RGB", src.size, bg)
    ImageDraw.Draw(patch).text((0, baseline_offset), text, font=font, fill=(17, 17, 17))

    if resample_wobble:                                # resampling blur
        small = patch.resize((int(patch.width * 0.9), int(patch.height * 0.9)), Image.LANCZOS)
        patch = small.resize(patch.size, Image.LANCZOS)

    patch = _recompress(patch, patch_quality, "4:2:0")  # <-- the double-compression island
    img = img.copy()
    img.paste(patch, (l, t))
    return img
```

### 3.4 The delivery step — and why it is not optional

Merchants in Pakistan receive these over WhatsApp. WhatsApp **re-encodes to progressive JPEG at low quality and strips EXIF entirely** — a 5 MB phone JPEG comes out at roughly 150–200 KB, and geolocation, device model, and editing-software tags are gone.

This has three consequences you must build into the dataset:

1. **Every image — genuine and tampered — must pass through a WhatsApp-grade re-encode.** Otherwise your tamper detector learns "is a JPEG that has been compressed twice", which is true of 100 % of real inbound receipts and 0 % of your genuine fixtures. That detector would score beautifully on your dataset and fire on everything in the real world.
2. **Never build a signal on EXIF `Software` tags.** It is the first thing people reach for and it is destroyed in transit. If you extract EXIF at all, treat its *absence* as uninformative, not suspicious.
3. Include one `document mode` case (delivered uncompressed) so the pipeline handles both.

```python
def deliver_whatsapp(img: Image.Image, seed_rng) -> bytes:
    # long side clamped like a messenger would, progressive, EXIF-free
    img = img.copy(); img.thumbnail((1600, 1600), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=82, subsampling="4:2:0", progressive=True, optimize=True)
    return buf.getvalue()
```

### 3.5 Ground truth for tamper signals

The manifest records **expected signals as a contract, not a score**:

```json
"expected_signals": { "at_least_one_of": ["ela_local_hotspot", "qtable_mismatch"],
                      "none_of": ["exif_software_tag"] }
```

And — this is the case that protects your architecture — include **at least two tampered fixtures with `expected_signals: {"at_least_one_of": [], "none_of": []}`**: a careful edit that leaves no recoverable trace after WhatsApp compression. Their correct outcome is still `SUSPICIOUS`, decided purely by the ledger contradiction. That fixture is the executable proof of your commitment that *no screenshot-derived signal alone establishes that payment occurred*.

---

## 4. Designing the fixture set to reproduce all five outcomes

### 4.1 Model `outcome` and `reason_code` separately

`AMBIGUOUS` is not a sixth state; it is a **reason** for `NEEDS_REVIEW`. Encode both:

```
outcome:     VERIFIED | UNMATCHED | SUSPICIOUS | DUPLICATE | NEEDS_REVIEW
reason_code: EXACT_REF_MATCH | STRONG_FIELD_CONSENSUS | OVERPAID_WITHIN_TOLERANCE
           | NO_CANDIDATE | PENDING_SETTLEMENT | WRONG_BENEFICIARY | FEED_LAG
           | CLAIM_INFLATION | REF_REWRITE | TIMESTAMP_REWRITE | BENEFICIARY_REWRITE | FABRICATED
           | TXN_ALREADY_ALLOCATED | REPLAY_SAME_ORDER
           | AMBIGUOUS_CANDIDATES | UNDERPAYMENT | LOW_EXTRACTION_CONFIDENCE | FIELD_OCCLUDED
```

Assert on `(outcome, reason_code, rules_version)` in tests. Asserting only on `outcome` lets a rule regression hide: a case can reach `NEEDS_REVIEW` for entirely the wrong reason and the test stays green.

### 4.2 The 30-case matrix

| ID | Family | Variant | Rail | Setup | Expected |
|---|---|---|---|---|---|
| G01 | Verified | genuine | easypaisa | Ref matches ledger exactly | `VERIFIED / EXACT_REF_MATCH` |
| G02 | Verified | genuine | jazzcash | Ref occluded by crop; amount + T±90 s + name agree | `VERIFIED / STRONG_FIELD_CONSENSUS` |
| G03 | Verified | genuine | raast | Sender name is a transliteration variant (`Mohammad Bilal Sheikh` vs ledger `Muhammad Bilal Shaikh`) | `VERIFIED` |
| G04 | Verified | genuine | bank | Name given as `M. B. Shaikh` (initials) | `VERIFIED` |
| G05 | Verified | genuine | easypaisa | Paid PKR 5,200 on a 5,000 order | `VERIFIED / OVERPAID_WITHIN_TOLERANCE` |
| G06 | Verified | genuine | jazzcash | Heavy WhatsApp compression, 1024 px long side | `VERIFIED` |
| G07 | Verified | genuine | raast | Dark-mode receipt | `VERIFIED` |
| G08 | Verified | genuine | bank | IBAN-only beneficiary, no name on screenshot | `VERIFIED` |
| G09 | Verified | genuine | easypaisa | Screenshot taken 3 s after the ledger timestamp | `VERIFIED` |
| G10 | Verified | genuine | jazzcash | Photo-of-screen (perspective + glare), still legible | `VERIFIED` |
| U01 | Unmatched | genuine | raast | **Payment still processing** — real, correct, simply not in the feed yet (anchor − 4 min) | `UNMATCHED / PENDING_SETTLEMENT` |
| U02 | Unmatched | genuine | easypaisa | Paid to a *different* merchant's wallet | `UNMATCHED / WRONG_BENEFICIARY` |
| U03 | Unmatched | genuine | bank | Ledger feed truncated to T−48 h; txn is older | `UNMATCHED / FEED_LAG` |
| U04 | Unmatched | genuine | jazzcash | Valid-looking ref that exists on no rail | `UNMATCHED / NO_CANDIDATE` |
| S01 | Suspicious | edited | easypaisa | Amount `500` → `5,000`, clumsy paste | `SUSPICIOUS / CLAIM_INFLATION` |
| S02 | Suspicious | edited | jazzcash | Ref digit rewritten to hit another order's txn | `SUSPICIOUS / REF_REWRITE` |
| S03 | Suspicious | edited | raast | Timestamp shifted 6 h to land inside the window | `SUSPICIOUS / TIMESTAMP_REWRITE` |
| S04 | Suspicious | edited | bank | Beneficiary name replaced with the merchant's | `SUSPICIOUS / BENEFICIARY_REWRITE` |
| S05 | Suspicious | edited | easypaisa | Wholly fabricated receipt, no ledger row at all | `SUSPICIOUS / FABRICATED` |
| S06 | Suspicious | edited | jazzcash | **Careful edit, no surviving forensic trace**; ledger says 800, claim says 8,000 | `SUSPICIOUS / CLAIM_INFLATION`, `expected_signals` empty |
| D01 | Duplicate | reused | easypaisa | Same txn already allocated to order #1041 | `DUPLICATE / TXN_ALREADY_ALLOCATED` |
| D02 | Duplicate | reused | jazzcash | Byte-identical image re-uploaded to the **same** order | `DUPLICATE / REPLAY_SAME_ORDER` |
| D03 | Duplicate | reused | raast | Same txn, *different* screenshot (re-opened in app, new status bar clock) | `DUPLICATE / TXN_ALREADY_ALLOCATED` |
| D04 | Duplicate | reused | bank | Same txn submitted by a *different* customer | `DUPLICATE / TXN_ALREADY_ALLOCATED` |
| N01 | Needs review | genuine | easypaisa | **Two ledger txns**, same sender, same 5,000, 4 min apart, no ref on screenshot | `NEEDS_REVIEW / AMBIGUOUS_CANDIDATES` |
| N02 | Needs review | genuine | jazzcash | Two candidates differing only in one ref character, that character glare-obscured | `NEEDS_REVIEW / AMBIGUOUS_CANDIDATES` |
| N03 | Needs review | genuine | raast | Paid 4,800 on a 5,000 order | `NEEDS_REVIEW / UNDERPAYMENT` |
| N04 | Needs review | genuine | bank | Motion blur; amount extraction confidence below threshold | `NEEDS_REVIEW / LOW_EXTRACTION_CONFIDENCE` |
| N05 | Needs review | genuine | easypaisa | Crop removes both ref and timestamp | `NEEDS_REVIEW / FIELD_OCCLUDED` |
| N06 | Needs review | genuine | jazzcash | Sender name `Abdur Rehman Qureshi` vs ledger `A R QURESHI TRADERS` — fuzzy score lands in the review band | `NEEDS_REVIEW` |

### 4.3 The two hard cases, in detail

**AMBIGUOUS (N01).** Ambiguity must be *structural*, not accidental. Seed **two** ledger rows that are individually plausible and provide the retrieval layer with no tiebreaker: same sender MSISDN, same amount to the rupee, both inside the timestamp tolerance, neither ref visible on the screenshot. If one row is even slightly better, a scoring tweak silently collapses the case into `VERIFIED` and your hardest test evaporates. Write the assertion as *"≥ 2 candidates survive with score delta < the ambiguity threshold"*, not merely *"outcome == NEEDS_REVIEW"*.

**UNMATCHED that must not read as fraud (U01).** This is the reputational case: a real customer who really paid, 4 minutes ago, whose transaction has not settled. Enforce it in three places:

1. `expected_signals.at_least_one_of == []` — nothing is wrong with the image.
2. A test asserting the response carries **no** tamper-signal entries and **no** suspicion language.
3. A UI copy test: the response's `merchant_guidance` for `PENDING_SETTLEMENT` must read like *"Not in your ledger yet — settlement can take a few minutes. Re-check at 14:15."*, not *"could not verify"*.

Add a golden-file test over the rendered explanation string for U01. It is the cheapest possible guard against a rules refactor turning a patient customer into an accused one.

---

## 5. Determinism and seeding

### 5.1 Layered determinism

| Layer | Mechanism |
|---|---|
| Entity IDs | `uuid.uuid5(NS, f"proofpay:demo:{kind}:{case_id}")` — stable, collision-free, no counters, no DB round-trip |
| Human-readable refs | Derived, not random: `EP{case_index:04d}{checkdigit}` |
| Names / phones / amounts | **Frozen in `manifest.json`.** Faker never runs at seed time |
| Timestamps | Integer minute offsets from a single anchor |
| Image bytes | Committed. Regeneration is a separate, explicit, occasional command |
| Rule outcomes | Pinned `rules_version` recorded in every expectation |

```python
import uuid
NS = uuid.uuid5(uuid.NAMESPACE_URL, "https://proofpay.demo/v1")

def demo_id(kind: str, key: str) -> uuid.UUID:
    return uuid.uuid5(NS, f"proofpay:demo:{kind}:{key}")
```

### 5.2 Handling "now" without the fixtures going stale

Use an **anchor plus offsets**, and treat the anchor as configuration:

```python
# proofpay/demo/clock.py
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os

PKT = ZoneInfo("Asia/Karachi")
PINNED_ANCHOR = datetime(2026, 8, 20, 14, 5, 0, tzinfo=PKT)

def anchor() -> datetime:
    raw = os.getenv("PROOFPAY_DEMO_ANCHOR")          # "today" | ISO-8601 | unset
    if raw == "today":
        n = datetime.now(PKT)
        return n.replace(hour=14, minute=5, second=0, microsecond=0)
    return datetime.fromisoformat(raw) if raw else PINNED_ANCHOR

def at(offset_minutes: int) -> datetime:
    return anchor() + timedelta(minutes=offset_minutes)
```

Then, in the fixture spec, everything is relative: `ledger_offset_min: -12`, `claim_offset_min: -11`.

**The important realisation:** almost none of your rules care about `now`. Timestamp scoring compares *claim vs ledger*, and that delta is invariant under any anchor shift. Only `PENDING_SETTLEMENT` (U01) and feed-lag windows (U03) touch `now`. So:

- **Tests:** always use `PINNED_ANCHOR`. Never `datetime.now()`. Inject a `Clock` port into the decision engine (you already have the adapter pattern — reuse it). Prefer dependency injection over `freezegun`/`time-machine`: an injected clock is faster, works in async paths, and needs no library. Keep **`time-machine`** in the toolbox for the two places you cannot inject — it is ~100× faster than `freezegun` (≈16 µs vs ≈6.4 ms per call) because it patches at the C layer.
- **Demo day:** `PROOFPAY_DEMO_ANCHOR=today uv run proofpay-demo seed --reset`. The ledger and orders move to today; U01 becomes "4 minutes ago" again.
- **The pixel problem:** the receipt image has `20 Aug 2026` burned into it. Two honest options:
  - **(a) Accept it** and make the UI display *absolute* timestamps everywhere (`20 Aug 2026, 02:05 PM`), never relative ones (`2 hours ago`). Absolute stale dates look like historical data; relative ones look broken. **This is the recommendation.**
  - **(b) Rebuild:** `uv run proofpay-demo build --anchor today` re-renders all 30 images with today's dates in ~15 s and rewrites the manifest. Fine to run the morning of the demo; then commit the result so everyone is on the same bytes.

**Never** re-render inside `seed`. Seeding must not depend on a browser.

### 5.3 The honest limit on byte-reproducibility

Chromium's PNG encoder is deterministic given identical pixels, but the pixels are **not** identical across operating systems: text rendering technologies differ (DirectWrite vs CoreText vs FreeType), sub-pixel anti-aliasing differs, and this is a known, unfixed reality of headless-browser screenshot comparison — Playwright's own guidance is to keep separate baselines per browser/platform combination.

Therefore:

- Images are **artifacts committed once**, not outputs regenerated per machine.
- `proofpay-demo verify` checks committed images against a `sha256` list in the manifest — a fast integrity check, not a rendering check.
- If you add a `--check-render` mode, compare with a **perceptual tolerance** (mean absolute pixel difference below ~1 %), and make it a warning, never a CI failure.

---

## 6. Fake data that looks Pakistani and plausible

### 6.1 Faker's actual coverage — and its limits

Verify before you build on it. As of **Faker 40.37.x**, the `en_PK` locale ships **only a `person` provider**. There is no `ur_PK` locale, and `en_PK` has **no address provider** and no locale-specific phone provider you should rely on. The `en_PK` person names skew Arabic-classical (`Najam Ghazzal`, `Kamal Majd Udeen`) rather than everyday Pakistani-urban (`Ayesha Siddiqui`, `Bilal Ahmed Khan`).

**Recommendation: use Faker as a starter, not as the source.** Write a ~120-line curated `pk.py` module of first names, family names, and Karachi/Lahore business names, run it once, and freeze the output into `manifest.json`. Curated lists of 60 given names × 40 family names give you 2,400 combinations — vastly more than 30 fixtures need, and they will look right to a Pakistani judge in a way Faker's output will not.

Also: **Faker's seeded output is not stable across Faker versions.** The docs seed via the class method `Faker.seed(0)` (instance `.seed()` is deprecated and raises `TypeError`), but nothing guarantees the same seed yields the same string after a minor upgrade. Freezing to JSON removes the dependency entirely — a `uv lock` bump can never change your dataset.

### 6.2 Phone numbers and identifiers

Use real PTA prefix ranges so numbers pass a plausibility glance, with fictional subscriber digits:

| Operator | Prefixes |
|---|---|
| Jazz (incl. ex-Warid) | 0300–0309, 0320–0329 |
| Zong | 0310–0319, 0370 |
| Ufone | 0330–0338 |
| Telenor | 0340–0349 |

Format on-screen as `0301-4567890`, and **mask like the real apps do** — `0301-****890`. That masking is itself a matching challenge worth having in the dataset.

**IBANs:** Pakistani IBAN is 24 characters — `PK` + 2 mod-97 check digits + 4-char bank code + 16-char account. Write the mod-97 yourself rather than adding `schwifty`; PK bank-code registry coverage in third-party libraries is uneven, and the algorithm is ten lines:

```python
def pk_iban(bank_code: str, account: str) -> str:
    body = f"{bank_code}{account:0>16}PK00"
    n = int("".join(str(int(c, 36)) for c in body))
    return f"PK{98 - n % 97:02d}{bank_code}{account:0>16}"
```

Use **fictional 4-letter bank codes** (`INDU`, `SBZP`) so no real institution's code appears.

### 6.3 Transliteration variation — the point of the fuzzy matcher

Urdu/Arabic-origin names have no single canonical Latin spelling; the same person's name mutates across documents, and bank records add their own conventions (uppercase, truncation, honorific-stripping, "AND SONS"). Build this variation deliberately, one axis at a time, so each fixture isolates one failure mode:

| Axis | Screenshot form | Ledger form |
|---|---|---|
| Vowel transliteration | `Muhammad` | `Mohammad` / `Mohammed` / `Mohd` |
| Consonant cluster | `Shaikh`, `Qureshi`, `Siddiqui` | `Sheikh`, `Qureishi`, `Siddiqi` |
| `Rehman/Rahman` | `Abdur Rehman` | `Abdul Rahman` |
| Compound splitting | `Noorulhaq` | `Noor Ul Haq` |
| Word order | `Bilal Ahmed Khan` | `Khan, Bilal Ahmed` |
| Initials | `Muhammad Bilal Shaikh` | `M B SHAIKH` |
| Case + noise | `Ayesha Siddiqui` | `AYESHA SIDDIQUI          ` |
| Business suffix | `Ali Traders` | `ALI TRADERS PVT LTD` |
| Honorific | `Mr. Usman Ghani` | `USMAN GHANI` |

```python
TRANSLIT = {"muhammad": ["mohammad", "mohammed", "mohd", "md"],
            "shaikh":   ["sheikh", "shaykh"],
            "rehman":   ["rahman", "rehmaan"],
            "siddiqui": ["siddiqi", "sadiqui"],
            "qureshi":  ["qureishi", "quraishi"]}
```

Keep the variant **axis label** in the manifest (`"name_variation": "consonant_cluster"`). When the fuzzy matcher regresses, the failing test names the exact linguistic phenomenon it broke on — worth far more than a bare score assertion. And include one **negative** control: two genuinely different people whose names are within fuzzy distance (`Bilal Ahmed` vs `Bilal Ahmad`), where the correct behaviour is *not* to merge them.

---

## 7. Seed script design

### 7.1 The contract

```
uv run proofpay-demo build     [--anchor today]   # render images + rewrite manifest  (rare, needs Playwright)
uv run proofpay-demo seed      [--anchor ...]     # idempotent upsert into the DB      (fast, no browser)
uv run proofpay-demo seed --reset                 # drop + alembic upgrade head + seed
uv run proofpay-demo verify                       # manifest integrity + image hashes
uv run proofpay-demo report                       # per-field extraction accuracy
```

`seed` must run in **under 3 seconds** and require nothing but Python and the DB. If seeding needs a browser, an API key, or the network, someone's laptop will fail at the worst moment.

### 7.2 Idempotency

Because every primary key is a `uuid5` of the case ID, idempotency is nearly free. For a hackathon, `session.merge()` is the right call — one line, identical behaviour on SQLite and PostgreSQL, no dialect-specific `on_conflict_do_update` to port later:

```python
def seed(session, manifest, anchor_dt):
    for case in manifest["cases"]:
        session.merge(Merchant(id=demo_id("merchant", case["merchant"]), ...))
        session.merge(Order(id=demo_id("order", case["id"]), ...))
        for i, row in enumerate(case["ledger"]):
            session.merge(LedgerTxn(
                id=demo_id("txn", f'{case["id"]}:{i}'),
                occurred_at=anchor_dt + timedelta(minutes=row["offset_min"]),
                ...))
    session.commit()
```

**Do not pre-seed the second allocation for the DUPLICATE cases.** Seed only the *first* allocation and let the demo's second submission collide with the database uniqueness constraint. That is the whole point of putting the constraint in the schema — the seed data must exercise it, not simulate its outcome.

### 7.3 `--reset`, safely

```python
def reset(engine, url: str, force: bool):
    if engine.dialect.name == "sqlite":
        Path(url.database).unlink(missing_ok=True)
    else:
        if url.host not in {"localhost", "127.0.0.1", "db"} and not force:
            raise SystemExit(f"refusing to reset non-local database {url.host!r}; pass --force")
        with engine.begin() as c:
            c.exec_driver_sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    from alembic import command
    from alembic.config import Config
    command.upgrade(Config("alembic.ini"), "head")     # migrations, never create_all()
```

Two rules: **always go through Alembic**, never `Base.metadata.create_all()` — otherwise the demo DB and the migration history diverge and your first Postgres deploy fails on a column that only ever existed in `create_all`. And **refuse non-local hosts** by default.

### 7.4 Why hand-inserted rows are the classic one-laptop demo

A row typed into DB Browser for SQLite, or a `psql` INSERT pasted from Slack, exists in exactly one place: that machine's disk. It is not in git, not in review, not in CI, and not in anyone else's database. Concretely, it produces:

- **The Thursday-night bug** — the demo works for whoever typed the rows and 404s for everyone else, and the two hours before judging go to reconstructing state instead of rehearsing.
- **Green CI, red stage** — tests run against seeded data; the demo runs against hand-typed data; they diverge without a single failing test.
- **Migration rot** — hand-typed rows survive `alembic upgrade` in a state no migration ever produced. Nulls appear in `NOT NULL` columns added later.
- **No reset** — after a bad demo run there is no way back to a clean state, so the team stops experimenting.

Enforce it culturally *and* mechanically:

- README states: **"There is exactly one way to get data: `uv run proofpay-demo seed --reset`."**
- `.gitignore` the dev SQLite file. Never commit a `.db`/`.sqlite`.
- CI job: `seed --reset` on an empty DB, then `verify`, then the full pytest suite. A hand-typed row cannot pass that job because it does not exist in the repo.
- A `demo_seed_meta` table holding `manifest_sha256` and `rules_version`; the API's `/healthz` reports it. If a teammate's screen shows a different hash, you know in five seconds.

---

## 8. Committing binary fixtures

### 8.1 The arithmetic first

A flat receipt UI at 1080×2340 with large areas of solid colour compresses to roughly **60–150 KB** as PNG and **80–200 KB** as a WhatsApp-grade JPEG. Thirty base images plus thirty delivered variants ≈ **5–8 MB total**. That is a rounding error in clone time.

### 8.2 Commit or generate at seed time?

| | Commit images | Generate at seed time |
|---|---|---|
| Everyone sees identical bytes | ✅ | ❌ — cross-OS font rendering differs |
| Seed needs Playwright + 100 MB browser | ❌ | ✅ (a real cost on a venue wifi) |
| CI can run without browsers | ✅ | ❌ |
| Tamper traces stable | ✅ | ❌ — re-rendering changes what forensics find |
| Repo size | +6 MB | 0 |
| Reviewing a change to a receipt | Opaque binary diff | Readable template diff |

**Commit the images.** The determinism argument is decisive: a dataset whose forensic properties change per machine cannot support tamper-signal tests. You keep the reviewability benefit anyway because the *templates and the manifest* are committed text — the PNG is a build artifact of reviewable sources, like a lockfile.

### 8.3 Size discipline

```gitattributes
* text=auto eol=lf
*.png binary
*.jpg binary
fixtures/demo/manifest.json text eol=lf
```

The `eol=lf` line matters more than it looks: on Windows, `core.autocrlf=true` silently rewrites line endings, which changes `manifest.json`'s bytes and therefore its hash — and your `verify` command fails on exactly the teammate who is new to git. Set this on day one.

Add a cheap guard (pre-commit hook or a CI step):

```bash
find fixtures/demo -type f -size +250k -print | grep . && \
  { echo "fixture over 250KB — re-export smaller"; exit 1; }
du -sm fixtures/demo | awk '$1 > 10 { print "fixtures dir over 10MB"; exit 1 }'
```

Regenerate images with `build` in a **single commit** touching all 30 — never dribble them in, or the repo accumulates every intermediate version of every binary forever (git keeps them all; deleting the file does not reclaim the history).

### 8.4 Git LFS: no

**Do not use LFS for this project.** Reasons, in order of importance for a 4-person hackathon team:

1. **It is the exact failure mode this phase exists to prevent.** A teammate who clones without `git lfs install` gets 130-byte pointer files where images should be. The app "works" — it just cannot read any receipt. This is a confusing, hard-to-diagnose, whole-evening bug, and it lands on the member new to git.
2. **CI needs opt-in.** `actions/checkout` does not fetch LFS objects unless you pass `lfs: true`; forget it and you get intermittent fixture-not-found failures.
3. **The thresholds don't apply.** LFS earns its keep when binaries exceed ~10 MB and churn regularly, or when clone times pass a minute. You are at 6 MB, static.
4. **Free-tier quotas.** GitHub's included LFS storage and bandwidth are small and are consumed by every CI run and every clone.

LFS *would* be right if you later grow to hundreds of megabytes of video or a large real-image evaluation corpus. Note that in the README as a future step and move on.

---

## 9. One dataset, two consumers: tests and demo

### 9.1 Manifest schema

`fixtures/demo/manifest.json` — one file, four layers per case:

```json
{
  "schema_version": 1,
  "rules_version": "2026.08.1",
  "anchor": "2026-08-20T14:05:00+05:00",
  "cases": [{
    "id": "S01",
    "family": "suspicious", "variant": "edited", "rail": "easypaisa",
    "images": { "delivered": "images/S01.delivered.jpg",
                "sha256": "9c1f…", "bytes": 141233 },

    "visible": {                       
      "amount": "5,000", "currency": "PKR",
      "sender_name": "Mohammad Bilal Sheikh", "sender_msisdn": "0301-****890",
      "receiver_name": "SabzPay Merchant 44012",
      "txn_ref": "EP0031746", "timestamp": "20 Aug 2026, 01:53 PM", "status": "Successful"
    },

    "ledger": [{ "offset_min": -12, "amount_minor": 50000, "ref": "EP0031746",
                 "sender_name": "MUHAMMAD BILAL SHAIKH", "sender_msisdn": "03014567890" }],

    "order": { "ref": "ORD-1043", "amount_minor": 500000, "customer": "Bilal Shaikh" },

    "expected": {
      "outcome": "SUSPICIOUS", "reason_code": "CLAIM_INFLATION",
      "amount_semantics": "CLAIM_INFLATION",
      "field_verdicts": { "sender_name": "MATCH", "amount": "CONTRADICTED",
                          "txn_ref": "MATCH", "timestamp": "MATCH" },
      "expected_signals": { "at_least_one_of": ["ela_local_hotspot", "qtable_mismatch"],
                            "none_of": ["exif_software_tag"] }
    }
  }]
}
```

### 9.2 The subtlety that will bite you

> **Extraction ground truth is what the image *shows*, not what the ledger *says*.**

For S01 the correct extraction is `amount = 5000`. The transaction really was 500. If you score extraction against the ledger, every tampered fixture counts as an extraction failure and your accuracy report becomes meaningless. This is why the manifest has a separate `visible` block: `visible` grades the **extractor**, `ledger` + `order` grade the **reconciler**, and `expected` grades the **rules**. Three consumers, three ground truths, one file.

### 9.3 pytest wiring

```python
# tests/conftest.py
import json, pytest
from pathlib import Path

MANIFEST = json.loads((Path("fixtures/demo/manifest.json")).read_text(encoding="utf-8"))

def pytest_generate_tests(metafunc):
    if "case" in metafunc.fixturenames:
        cases = MANIFEST["cases"]
        metafunc.parametrize("case", cases, ids=[c["id"] for c in cases])
```

```python
# tests/test_decision_matrix.py
def test_outcome_and_reason(case, engine, seeded_db):
    r = engine.decide(case["id"])
    assert (r.outcome, r.reason_code) == (
        case["expected"]["outcome"], case["expected"]["reason_code"]), case["id"]
    assert r.rules_version == MANIFEST["rules_version"]

def test_no_screenshot_signal_is_load_bearing(case, engine, seeded_db):
    """Removing all tamper signals must never turn a non-VERIFIED into VERIFIED."""
    r = engine.decide(case["id"], suppress_tamper_signals=True)
    if case["expected"]["outcome"] != "VERIFIED":
        assert r.outcome != "VERIFIED", case["id"]
```

That second test is a one-line executable statement of the project's headline architectural commitment. Judges love a test that encodes a principle.

### 9.4 The per-field accuracy report

Report **per field**, never as one blended number. The reason is concrete: an invoice number `INV-20260412` read as `INV-2O260412` is 92 % character-accurate and 0 % field-accurate — and for a reference ID, field accuracy is the only figure that matters.

| Field | Metric | Rationale |
|---|---|---|
| `amount` | exact match on minor units after normalisation | 4,999 ≠ 5,000. No partial credit |
| `currency` | exact | — |
| `txn_ref` | exact after `strip/upper`, **plus** normalised Levenshtein as a secondary | Near-misses tell you whether to widen candidate retrieval |
| `timestamp` | within ±60 s of `visible` | Guards format parsing, not clock skew |
| `sender_name` | normalised Levenshtein similarity, report mean + % ≥ 0.85 | Names legitimately vary; exact match is the wrong bar |
| `sender_msisdn` | exact on unmasked digits; masked → excluded, counted separately | Don't punish the model for `****` |
| `rail`, `status` | exact (classification) | — |

```
uv run proofpay-demo report --out reports/extraction_accuracy.md
```

```markdown
### Extraction accuracy — 30 cases — model qwen-vl (fallback: stub) — rules 2026.08.1
| field         | n  | exact | mean sim | p50 lat |
|---------------|----|-------|----------|---------|
| amount        | 30 | 29/30 |    —     |  1.9 s  |
| txn_ref       | 27 | 25/27 |   0.98   |    —    |
| sender_name   | 30 |  8/30 |   0.91   |    —    |
| timestamp     | 28 | 27/28 |    —     |    —    |
| **not extracted (occluded, expected)**: txn_ref ×3, timestamp ×2
```

Also emit `reports/extraction_accuracy.json` and commit both. Two extra rows earn their place: a **stub-adapter** run (proving the no-API-key fallback path still produces a report) and a **per-family breakdown** (accuracy on `edited` cases is the interesting number). Now "our extraction is measured, not asserted" is a claim backed by a regenerable artifact — and the delta between two commits' reports is the most persuasive slide you can put in front of a judge.

---

## 10. The data-ethics note (draft text to paste into the README and the pitch)

> **Every payment receipt in this repository is synthetic.**
>
> ProofPay reasons about payment screenshots: images that, in the real world, carry a named person's phone number, bank account, transaction history and running balance. Collecting real examples — from the web, from WhatsApp groups, from our own phones — would mean putting identifiable financial records of people who never consented into a public repository and in front of hackathon judges. We are not willing to do that, and no accuracy figure would justify it.
>
> So we built the dataset instead. Thirty receipts across four payment rails, rendered from HTML templates we wrote, populated with invented names and invented account numbers, on fictional brands (`SabzPay`, `NoorPay`, `Indus Bank`) that belong to no real company. Real system names appear only as internal data values, never as reproduced logos or interfaces. Ground truth is authored, not annotated, so we know the correct answer for every field of every image by construction — including for the images we deliberately tampered with.
>
> This is not a shortcut around a dataset we could not obtain. It is what let us do things a scraped corpus could not:
>
> - **Labelled forgeries.** We know exactly which pixels were altered and how, because we altered them. Real-world forgery datasets have no such ground truth.
> - **Reproducible evaluation.** Fixed seed, fixed anchor timestamp, committed images. `uv run proofpay-demo report` produces the same numbers on any machine, so accuracy is *measured* and regressions are *caught*.
> - **Adversarial coverage on demand.** We can generate the ambiguous case — two indistinguishable candidate transactions — that occurs rarely in the wild and is precisely where a naive system fails silently.
> - **A repository we can publish.** Nothing here needs redaction, retention limits, or a deletion request process.
>
> The same reasoning is standard in production fintech, where synthetic data is used to develop fraud and reconciliation systems without exposing customer records — with the caveat, which we accept, that synthetic data supports privacy compliance rather than replacing it. Our dataset is authored from scratch and trained on nothing, so no real person's data is in it, upstream of it, or recoverable from it.
>
> Everything under `fixtures/demo/` is synthetic. Nothing in it refers to a real person, account, or transaction.

Keep this to one slide. The point lands in ten seconds: on a fintech project, *how you got your data* is part of the engineering, and choosing to author it is a design decision with technical payoffs, not an apology.

---

## 11. Anti-patterns, collected

| Anti-pattern | Consequence | Fix |
|---|---|---|
| Tampering by editing template data and re-rendering | Tamper detector validated against zero tampering | Patch in pixel space with Pillow, post-render |
| Only tampered images get JPEG re-encoded | Detector learns "double-compressed = fake"; fires on every real WhatsApp receipt | Run the delivery step on **all** images |
| Building a tamper signal on EXIF `Software` | Destroyed by WhatsApp on every real inbound image | Treat missing metadata as uninformative |
| Real logos/brand colours in rendered receipts | Trademark exposure on a public repo and a public demo | Fictional brands; real names only as data values |
| Near-miss brand names (`EasyPaysa`) | Worse than the real logo — reads as deliberate passing off | Clearly distinct invented names |
| Blurring a real screenshot instead of generating one | Still real financial data; blurring is weak and partly reversible | Generate |
| Faker at seed time | Names change on a lockfile bump; different data per machine | Faker once at authoring time → freeze to `manifest.json` |
| `datetime.now()` in fixtures or rules | Tests drift; U01 flips outcome overnight | Anchor + offsets, injected `Clock` port |
| UI shows "2 hours ago" | Dataset visibly stale the day after you build it | Absolute timestamps everywhere |
| Committing `dev.sqlite` as "the dataset" | Opaque, merge-hostile, drifts from migrations | Commit JSON + images; DB is always rebuilt |
| `Base.metadata.create_all()` in the seeder | Demo schema diverges from Alembic history | `command.upgrade(cfg, "head")` |
| Hand-inserted rows | The one-laptop demo | Seed script is the only door; CI proves it |
| Pre-seeding both allocations for DUPLICATE cases | The DB uniqueness constraint is never exercised | Seed the first allocation only |
| Asserting only on `outcome` | Cases pass for the wrong reason | Assert `(outcome, reason_code, rules_version)` |
| Ambiguous case has a slight best candidate | Collapses to VERIFIED after any scoring tweak | Make candidates numerically indistinguishable; assert on candidate-set size and score delta |
| Grading extraction against the ledger | Every tampered fixture scores as an extraction failure | Grade against `visible` |
| One blended "94 % accurate" number | Hides that `txn_ref` is at 70 % | Per-field table |
| Rendering images inside `seed` or inside tests | Slow, needs Chromium in CI, non-deterministic across OS | `build` is a separate, rare command |
| Launching a browser per image | 10 s becomes 3 minutes | One browser, one context, loop pages |
| Rounded corners / transparent surround on receipts | Instantly reads as a mockup | Full-bleed rectangle |
| Git LFS for 6 MB of PNGs | Broken checkout for whoever forgets `git lfs install` | Commit directly |
| `core.autocrlf` rewriting `manifest.json` | Hash verification fails on Windows only | `.gitattributes` with `text eol=lf` |
| 4000×9000 px "high quality" fixtures | Blows the repo and the vision-model token budget | 1080×2340; keep the long side ≤ ~1600 px after delivery |

**One more, specific to your model adapter:** keep delivered images modest in pixel count. Qwen-VL models bill by visual tokens at roughly a 28–32 px block per token, and default budgets land near ~1.3 M pixels — a 1080×2340 image (~2.5 M px) will be downscaled or will cost double. Deliver at ~1600 px long side and verify the current per-image limits against Model Studio's "Image limits" section before demo day rather than trusting any number in this document.

---

## Sources

- [Playwright Python — Installation](https://playwright.dev/python/docs/intro) · [Browsers & install sizes](https://playwright.dev/python/docs/browsers) · [Browser contexts](https://playwright.dev/python/docs/api/class-browser) · [Visual comparisons](https://playwright.dev/docs/test-snapshots)
- [Playwright issue #23654 — Rendering determinism](https://github.com/microsoft/playwright/issues/23654) · [issue #20097 — font render differences across machines](https://github.com/microsoft/playwright/issues/20097)
- [playwright on PyPI (1.62.0)](https://pypi.org/project/playwright/)
- [Pillow — Image file formats: JPEG/PNG save options](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html) · [ImageDraw module](https://pillow.readthedocs.io/en/stable/reference/ImageDraw.html)
- [Faker — Localized providers (en_PK)](https://faker.readthedocs.io/en/master/locales.html) · [Faker class: seeding](https://faker.readthedocs.io/en/master/fakerclass.html) · [phone_number provider](https://faker.readthedocs.io/en/master/providers/faker.providers.phone_number.html)
- [Alembic — Tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html) · [Cookbook](https://alembic.sqlalchemy.org/en/latest/cookbook.html) · [Flask-DB: migrate, seed and reset](https://nickjanetakis.com/blog/flask-db-helps-you-migrate-seed-and-reset-your-sql-database) · [Patterns for making seeds idempotent](https://elixirforum.com/t/patterns-for-making-seeds-idempotent/58299)
- [time-machine vs freezegun benchmark (Adam Johnson)](https://adamj.eu/tech/2021/02/19/freezegun-versus-time-machine/) · [time-machine comparison docs](https://time-machine.readthedocs.io/en/stable/comparison.html)
- [Git LFS — practical guide](https://kuldeep-modh.medium.com/git-lfs-the-practical-guide-to-versioning-large-files-without-breaking-your-repository-5795b327a78e) · [Handling large files with LFS (Tower)](https://www.git-tower.com/learn/git/faq/handling-large-files-with-lfs) · [GitLab: Git LFS](https://docs.gitlab.com/topics/git/lfs)
- [Photo metadata in WhatsApp/Telegram/Signal (2026)](https://fast.io/resources/whatsapp-telegram-signal-photo-metadata-preservation/) · [Forensic value of EXIF across transfer methods](https://www.sciepublish.com/article/pii/567) · [File structure analysis of media sent over WhatsApp (thesis)](https://www.ucdenver.edu/docs/librariesprovider27/ncmf-docs/theses/risemberg_thesis_spring2020.pdf)
- [DocQT — forgery localization via diverse JPEG quantization tables](https://arxiv.org/pdf/2605.19688) · [Detecting JPEG double compression with a quantization-table database](https://www.mecs-press.org/ijem/ijem-v15-n3/v15n3-3.html) · [Image forensics explained](https://scanly.co/blog/image-forensics-explained)
- [Trademarks for mobile apps](https://arapackelaw.com/trademarks/trademarks-for-mobile-apps/) · [Screen capture: fair use vs copyright](https://www.mangoapps.com/articles/screen-capture-copyright-violation-or-fair-use)
- [SIL Open Font License (SIL)](https://software.sil.org/oflt/) · [Noto fonts licensing](https://en.wikipedia.org/wiki/Noto_fonts) · [Inter typeface](https://en.wikipedia.org/wiki/Inter_(typeface))
- [Fuzzy name matching techniques (Babel Street)](https://www.babelstreet.com/blog/fuzzy-name-matching-techniques) · [Muhammad (name) — spelling variants](https://en.wikipedia.org/wiki/Muhammad_(name)) · [Muslim personal names in Urdu](https://www.degruyterbrill.com/document/doi/10.1515/ijsl-2023-0004/html)
- [Pakistan SIM code / prefix list 2026](https://evo.com.pk/all-sim-codes-list/) · [Pakistan IBAN structure](https://bank.codes/iban/structure/pakistan/) · [Pakistan IBAN format & validation](https://www.xflowpay.com/tools/iban/countries/pakistan)
- [OCR accuracy benchmarking (Docsumo)](https://www.docsumo.com/blogs/ocr/accuracy) · [AI document extraction accuracy benchmarks](https://airparser.com/blog/ai-document-extraction-accuracy-benchmarks/) · [CM1 — few-shot information extraction dataset](https://arxiv.org/pdf/2505.04214)
- [Synthetic data in financial services (bobsguide)](https://www.bobsguide.com/synthetic-data-in-financial-services/) · [Synthetic data & GDPR compliance (YData)](https://ydata.ai/resources/synthetic-data-gdpr-compliance.html) · [Is synthetic data truly GDPR compliant? (Decentriq)](https://www.decentriq.com/article/synthetic-data-privacy)
- [Alibaba Cloud Model Studio — image & video understanding](https://www.alibabacloud.com/help/en/model-studio/vision) · [Qwen3-VL pixel control](https://mintlify.wiki/QwenLM/Qwen3-VL/inference/pixel-control)

---

## Definition of done

**Dataset content**

- [ ] `fixtures/demo/manifest.json` exists, is the single source of truth, and contains **30 cases**, each with `visible`, `ledger`, `order`, and `expected` blocks.
- [ ] All five outcomes are represented, with the case counts from §4.2: **VERIFIED ×10, UNMATCHED ×4, SUSPICIOUS ×6, DUPLICATE ×4, NEEDS_REVIEW ×6**.
- [ ] At least **two** cases carry `reason_code: AMBIGUOUS_CANDIDATES`, and for each a test asserts ≥ 2 surviving candidates with score delta below the ambiguity threshold.
- [ ] Case **U01** (payment still processing) exists, has empty `expected_signals`, and has a golden-file test on its merchant-facing explanation text asserting no suspicion language.
- [ ] All three amount semantics appear as distinct cases: **underpayment (N03)**, **overpayment (G05)**, **claim inflation (S01)**.
- [ ] At least one tampered case (**S06**) has *no* detectable forensic trace and still resolves to `SUSPICIOUS` from ledger evidence alone.
- [ ] At least four rails and at least six distinct name-variation axes are covered, each labelled in the manifest.

**Images**

- [ ] All 30 delivered images are committed under `fixtures/demo/images/`, each ≤ 250 KB, directory total ≤ 10 MB, no Git LFS.
- [ ] Every image has a `sha256` in the manifest, and `proofpay-demo verify` passes on a fresh clone on all four team laptops.
- [ ] Every image — genuine and tampered — has passed through the WhatsApp-grade delivery re-encode.
- [ ] All tampering is done post-render in pixel space; no tampered image was produced by re-rendering the template.
- [ ] No real logo, wordmark, brand colour system, or cloned screen appears in any image. Rail brands are fictional.
- [ ] `.gitattributes` declares `*.png binary`, `*.jpg binary`, and `* text=auto eol=lf`.
- [ ] Bundled font file ships with its `OFL.txt`.

**Determinism**

- [ ] Every entity ID is a `uuid5` derived from a case ID. No autoincrement dependence, no `random` at seed time.
- [ ] No `Faker` call happens at seed time or test time; Faker output is frozen in the manifest.
- [ ] No `datetime.now()` anywhere in the fixture, seed, or rules code paths — all times derive from `demo.clock.anchor()`, injected as a `Clock` port.
- [ ] `PROOFPAY_DEMO_ANCHOR=today seed --reset` produces a working, fresh-looking demo; the UI displays absolute timestamps only.
- [ ] Running `seed --reset` twice in a row produces byte-identical database content (verified by a row-hash check).

**Seed script**

- [ ] `uv run proofpay-demo {build,seed,verify,report}` all exist and are documented in the README.
- [ ] `seed` completes in **< 3 s** and requires no browser, no network, and no API key.
- [ ] `seed` (without `--reset`) is idempotent — running it on a populated DB changes nothing and raises nothing.
- [ ] `--reset` runs `alembic upgrade head`, never `create_all()`, and refuses non-local database hosts without `--force`.
- [ ] DUPLICATE cases seed only the first allocation, so the database uniqueness constraint is genuinely exercised at demo time.
- [ ] `demo_seed_meta` records `manifest_sha256` + `rules_version`, and `/healthz` reports them.
- [ ] The dev SQLite file is `.gitignore`d; no `.db`/`.sqlite` is committed.

**Tests and reporting**

- [ ] pytest parametrises over `manifest.json` by case ID; a failure names the case (e.g. `test_outcome_and_reason[S02]`).
- [ ] Every case asserts on `(outcome, reason_code, rules_version)`, not `outcome` alone.
- [ ] `test_no_screenshot_signal_is_load_bearing` passes for all 30 cases.
- [ ] Extraction is graded against `visible`, reconciliation against `ledger`/`order` — verified by a test that would fail if S01 were graded against the ledger.
- [ ] `report` emits both `reports/extraction_accuracy.md` and `.json`, with **per-field** metrics, a per-family breakdown, and a stub-adapter run; both are committed.
- [ ] CI runs, on an empty database: `seed --reset` → `verify` → full pytest → `report`. It is green.
- [ ] A fresh clone on a machine that has never run the project reaches a working demo with exactly two commands, and this has been executed end-to-end by the team member new to git — by them, not watched over their shoulder.

**Ethics**

- [ ] The data-ethics note from §10 is in the README and condensed onto one pitch slide.
- [ ] A repo-wide grep confirms no real person's name, phone number, IBAN, or transaction reference appears in any file, image, or commit message.