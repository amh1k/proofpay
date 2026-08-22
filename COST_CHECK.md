# ProofPay — Cost and Licensing Check

**BOTTOM LINE: Yes. ProofPay can be built, run, and demoed for US$0, with no credit card entered anywhere.** The entire code stack — Python, FastAPI, SQLAlchemy, SQLite, Pillow, RapidFuzz, React, Vite, Tailwind, shadcn/ui — is MIT/BSD/Apache/public-domain and free forever, with no copyleft and no paid tier. The repo already defaults to SQLite + local-filesystem storage + the deterministic extractor, so it runs on a laptop with zero accounts. Every cloud piece is an *optional upgrade* for judging points: Model Studio's Qwen-VL free quota is genuinely free (1M tokens per model, 90 days, no card, and it hard-stops instead of billing), OSS costs effectively nothing at a few hundred receipt images, and hosting can be Render Free + Cloudflare Pages with no card. The only real spending risks are (a) Alibaba Function Compute, which auto-converts to pay-as-you-go with no hard stop, and (b) any Alibaba free trial, which requires a verified card on file. Avoid both and the financial blast radius is zero.

## Cost summary

| Component | What we use | Cost | Notes |
|---|---|---|---|
| **Open-source tooling** | | | |
| Language / runtime | Python 3.10+ (CPython) | Free (open source) | Python-2.0.1, permissive, explicitly not GPL |
| API framework | FastAPI, Starlette, Uvicorn | Free (open source) | MIT / BSD-3-Clause |
| Validation / config | Pydantic, pydantic-settings | Free (open source) | MIT |
| ORM / migrations | SQLAlchemy, Alembic | Free (open source) | MIT |
| Local database | SQLite | Free (open source) | Public domain — not even attribution required |
| Image handling | Pillow | Free (open source) | MIT-CMU. Never was copyleft; older scanners may label it HPND |
| Fuzzy matching | RapidFuzz | Free (open source) | MIT. **Do not** swap in `fuzzywuzzy`/`python-Levenshtein` — GPL |
| Auth | bcrypt, PyJWT | Free (open source) | Apache-2.0 / MIT. bcrypt needs the NOTICE file kept |
| Tests | pytest, httpx, ruff | Free (open source) | MIT |
| Frontend | React, Vite, TailwindCSS, shadcn/ui | Free (open source) | MIT throughout. Radix = MIT, lucide = ISC |
| Offline OCR fallback | Tesseract / pytesseract / PaddleOCR | Free (open source) | Apache-2.0. Self-hosted, unmetered |
| **Cloud services (optional)** | | | |
| Vision OCR | Qwen-VL via Model Studio (Singapore) | Free tier — expires 90 days from activation | 1M tokens **per model** (~5M total). No card. Hard-stops with "Free Quota Only" on |
| Image storage | Alibaba OSS | Free tier | 5 GB/mo + 100 GB egress bands; new-user trial on top. Card required, no hard stop |
| Hosted Postgres (demo) | Neon Free | Free tier | Permanent, no card, suspends instead of billing |
| Hosted Postgres (Alibaba) | ApsaraDB RDS for PostgreSQL | Free trial — expires 30 days | Card + real-name verification required; resources deleted at expiry |
| Backend hosting | Render Free web service | Free tier | No card; 750 hrs/mo; spins down after 15 min idle |
| Frontend hosting | Cloudflare Pages | Free tier | No card, egress not billed, 500 builds/mo |
| Live-demo tunnel | Cloudflare Quick Tunnel | Free (no account) | New random URL each restart; no SSE support |
| Serverless backend | Alibaba Function Compute | **Risk — may cost money** | 150k CU/mo for 3 months, then **auto-bills**, no hard stop. Avoid |
| Netlify (frontend alt) | Netlify Free | **Risk — too tight** | 300 credits/mo ≈ 20 production deploys. Hard cap, no charge, but you *will* hit it |
| Render / Railway Postgres | — | **Risk — data loss / paid** | Render free DB self-deletes at 30 days; Railway has no free tier |

## Cloud services in detail

### Qwen-VL vision models (Alibaba Cloud Model Studio, Singapore)
**Allowance:** 1,000,000 free tokens *per model*, not a shared pool — confirmed on `qwen-vl-max`, `qwen-vl-plus`, `qwen3-vl-plus`, `qwen3-vl-flash`, and `qwen-vl-ocr`, so ~5M vision tokens in aggregate. 500 receipts downscaled to ~1024px cost roughly 560K tokens, i.e. ~56% of *one* model's quota.
**Card:** No — registration needs only email, password, and a non-mainland-China mobile number.
**Expiry:** 90 days from activation (hard; unused quota is voided). The clock starts at activation, so don't activate months early.
**Biggest gotcha:** By default a new, unverified account **cannot** call the API after the free quota runs out — it hard-stops rather than billing. That safety disappears the moment anyone adds payment info, so turn on the **"Free Quota Only"** toggle as the first console action and catch `AllocationQuota.FreeTierOnly` in the OCR path. Also: Singapore region only, and the base URL embeds your WorkspaceId (`https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1`).
Source: https://www.alibabacloud.com/help/en/model-studio/new-free-quota · https://www.alibabacloud.com/help/en/model-studio/model-pricing

### Alibaba OSS (object storage)
**Allowance:** Pricing-page tier tables list the lowest band of every billable item as "Free" for Singapore: 0–5 GB Standard LRS storage, 0–100 GB outbound traffic, 0–500M read requests, 0–100M write requests. A new-user trial stacks on top (the international doc says 500 GB for 1 month; the China-site mirror says 20 GB for 3 months — **these conflict and we could not reconcile them**; plan against the smaller). Whether the recurring 5 GB band is *permanent* is **unconfirmed** — no footnote says.
**Card:** Yes — the free-quota doc requires "a valid payment method (credit card, debit card, or PayTM) attached to your account during the free trial." Prepaid, gift, virtual, and UnionPay-only cards are rejected, which may block students outright.
**Expiry:** Trial 1 month (or 3, per the conflicting doc). Monthly bands appear recurring.
**Biggest gotcha:** **There is no hard stop.** Pay-as-you-go OSS never suspends; overage silently accrues against the bound card. Worst case at our scale is under 2 US cents/month, but set a billing alert on day one anyway and keep the bucket private (these are payment receipts).
Source: https://www.alibabacloud.com/help/en/oss/free-quota-for-new-users · https://www.alibabacloud.com/en/product/oss/pricing

### PostgreSQL hosting
**Neon (recommended free Postgres):** 0.5 GB storage/project, 100 CU-hours/month, 10 branches — one per teammate. Pricing page states verbatim: "The Free plan is permanent (not a trial); no credit card required." Exceeding a limit *suspends compute until next month*, never bills. **Gotcha:** scale-to-zero after 5 min idle cannot be disabled — warm the DB right before demoing or the first on-stage request looks broken. https://neon.com/pricing
**Aiven (card-free backup):** 1 GB disk / 1 GB RAM / 1 CPU, "No payment method is required to sign up", "Free services do not have any time limitations." **Gotcha:** `max_connections = 20` — set SQLAlchemy `pool_size`/`max_overflow` explicitly. https://aiven.io/docs/products/postgresql/concepts/pg-free-tier
**Alibaba ApsaraDB RDS:** 30 days free for new users (pg.n2.2c.1m, 2 vCPU / 4 GB / 20 GB ESSD). **Card and real-name verification are mandatory**, PayPal not accepted, verification can take up to 3 business days. Trial resources are released (deleted) at expiry. Only use this if judges need to see Alibaba services, and provision it deliberately at trial spec. https://www.alibabacloud.com/product/apsaradb-for-rds-postgresql
**Avoid:** Render free Postgres (deleted 30 days after creation, 14-day grace), Railway (no free tier, $5/mo floor), ElephantSQL (EOL, data deleted Feb 2025), CockroachDB (not real Postgres, card required).

### Deployment hosting
**Render Free (backend):** 750 instance hours/month, no credit card. Failure mode is safe: "If you haven't added a payment method and you would incur charges, Render instead disables your services." **Gotcha:** free services spin down after 15 min idle and take ~1 minute to wake — ping the URL a few minutes before judging. (Exact RAM/CPU figures are **unconfirmed** on Render's own docs.) https://render.com/docs/free
**Cloudflare Pages (frontend):** 500 builds/month, egress not charged, no card. https://developers.cloudflare.com/pages/platform/limits/
**Vercel Hobby (frontend alt):** pauses instead of charging, but is **non-commercial personal use only** and has a 10s function timeout — fine for React, unusable for the OCR round-trip. https://vercel.com/docs/limits
**Alibaba Function Compute — avoid:** the trial doc is explicit that "usage that exceeds the trial quota during any month is billed on a pay-as-you-go basis." Card already on file + no hard stop = the single biggest budget risk in this whole report. https://www.alibabacloud.com/help/en/functioncompute/fc/product-overview/trial-quota-1
**Hugging Face Spaces — no longer viable:** Hub docs now say Docker/Gradio Spaces require PRO ($9/mo) to create. The marketing pricing page contradicts this; check the create-Space UI before planning around it.

### Hackathon credits
Confirmed pattern: participant credits are **event-distributed, small, and capped** — $40 Qwen Cloud vouchers, $50 PAI coupons, "first 100 registrants only". There is **no self-serve hackathon credits page**. Separately, Qwen Cloud's own free quota needs **no payment method** and hard-stops for unverified accounts — the cleanest no-card path for vision inference. https://docs.qwencloud.com/resources/free-quota

## The zero-cost fallback

**This is not a contingency plan we would have to build — it is what the repo already does out of the box.** `backend/proofpay/config.py` sets every default to the free-and-local option, and `.env.example` says so explicitly: *"Every value below has a working default, so the application runs with no `.env` at all."*

| Cloud thing | Local default already in the code |
|---|---|
| ApsaraDB RDS / Postgres | `database_url = "sqlite:///./proofpay.db"` — SQLite is public domain, serverless, no account, no network. Same SQLAlchemy models run against either; only `PROOFPAY_DATABASE_URL` changes. |
| OSS object storage | `storage_backend = "local"`, `storage_local_path = "./storage"` — proof images go to disk behind the adapter. `storage/` is gitignored. |
| Qwen-VL vision OCR | `receipt_extractor = "deterministic"`. And `effective_receipt_extractor()` **downgrades automatically**: asking for `"qwen"` without a key silently returns `"deterministic"` rather than crashing. A missing credential degrades quality, never breaks the pipeline. |
| ECS / FC / Render hosting | `uvicorn proofpay.main:app --reload` on a laptop; expose to judges' devices with a Cloudflare Quick Tunnel (free, no account, no card) if needed. |

The cloud SDKs are not even installed by default — `oss2`, `dashscope`, and `psycopg` sit in optional extras (`.[oss]`, `.[qwen]`, `.[postgres]`) in `pyproject.toml`. A fresh clone that runs `pip install -r requirements.lock.txt` has **no way to contact a paid service**.

**Consequence: cloud is an upgrade, never a dependency.** If credits arrive late, an account fails verification, a quota expires mid-judging, or the venue Wi-Fi dies, ProofPay still runs end-to-end. Keep it that way — no code outside `adapters/` should ever import `oss2` or `dashscope`. Also cache a set of pre-processed sample receipts and record a 60-second screen capture as the last-resort demo.

## Rules to avoid an accidental bill

- **Turn on Model Studio's "Free Quota Only" toggle before the first API call.** It is the only hard stop that survives someone adding a card.
- **Do not enter a card unless a component genuinely requires one.** Neon, Aiven, Render, Cloudflare Pages, Cloudflare Tunnel, and the Model Studio free quota all work without one. If a card is unavoidable, one nominated teammate's card on one nominated account — trials cannot be merged later, and one account per identity is the rule.
- **Do not deploy to Alibaba Function Compute or SAE.** FC auto-converts to pay-as-you-go with no hard stop; SAE bills from the first second and adds separate charges for load balancer, NAT, DB, and logging.
- **Set a billing alert on day one** on any Alibaba account with a card attached. OSS and FC never fail closed, and the card is only auto-charged once fees hit a deduction threshold (~USD 1,000), so a runaway bill accrues invisibly before anyone notices.
- **Downscale receipt images to ~1024px on the long edge, server-side with Pillow, before upload.** Image resolution is the entire vision-model cost driver — this one line is the difference between 500 receipts fitting in the free quota and not. Do it in FastAPI, not with OSS image processing, which is excluded from the free trial.
- **Never commit an API key.** `.env` is gitignored; keep it that way, use `.env.example` for shape only, and never paste a key into chat or a PR.
- **Never `pip install python-Levenshtein` or `fuzzywuzzy`** as a "speedup" — both are GPL and would impose copyleft on our source in a judged competition. RapidFuzz (MIT) needs no helper.
- **Delete every cloud resource the moment the demo ends** — RDS instances, OSS buckets, any deployed service — and put a calendar reminder before any trial's day-30 mark. Alibaba trial resources are released automatically, but anything provisioned *outside* trial scope is not.
- **Watch for auto-renewal and stale offers.** Alibaba leaves dead campaign pages online (a $20 coupon page with 2022 terms still serves today); verify the date on any offer before counting on it.
- **Ship a `THIRD-PARTY-LICENSES` file** with the MIT/BSD notices and the Apache-2.0 NOTICE text. That is the only obligation in the entire open-source stack.

## What to ask the organisers

Credits are never self-serve for these events — if nobody asks, nobody gets them. Send this the day registration opens, and **register all four teammates immediately**, since vouchers are often capped by headcount ("first 100 registered participants only"), not by team.

Ask for, in one message:

1. **A participant cloud-credit voucher code and its exact USD value.** Expect $40–$50 per person; larger figures in announcements are usually *prize* money for winners, not participation support.
2. **The voucher application form URL and its deadline.** This closes *earlier* than the submission deadline and is announced separately — one past event cut off applications weeks before submissions.
3. **Whether the voucher is headcount-capped or first-come.**
4. **Which products the coupon can offset.** A PAI-scoped coupon will not pay for OSS, RDS, or Model Studio. General coupons cover most products but exclude cloud communications, domains, and marketplace items. Confirm it covers exactly what we deploy on.
5. **The coupon's expiry date.**
6. **Whether redeeming it still requires a card on file** — for us this is the deciding question.
7. **An escalation contact.** Distribution is slow and unreliable; past participants sat at "under review" for over a week. Get the Discord/email channel up front.

Also worth applying for in parallel, since it is self-serve and reviewed in ~3 business days: the SMB AI credits campaign offers **$200 in credits with no minimum spend** for a 100-word use-case description (https://www.alibabacloud.com/en/campaign/smb-coupon). Whether it requires a payment method is **unconfirmed** — the page does not say.

**Regardless of the answers, treat credits as a bonus for the deployed demo only. Nothing on the critical path should depend on a voucher arriving.**