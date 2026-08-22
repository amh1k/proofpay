# ProofPay Engineering Practices

Written for a 4-person team, a few days, one repo, one demo. Every rule below has a reason; where a rule costs more than it earns at hackathon scale, I say to skip it.

---

## 1. Reproducible environments across 4 machines

### The honest answer to "do we all need the exact same versions?"

**Interpreter: same *minor* version, patch version irrelevant.** 3.12.4 vs 3.12.9 will never break you. 3.11 vs 3.12 vs 3.13 will — through stdlib behaviour changes (`datetime.UTC`, `enum` repr, `asyncio` internals) and, more often, through **wheel availability**: a package that ships `cp312` wheels but not `cp313` forces the teammate on 3.13 to compile from source, and on Windows that means "install Visual C++ Build Tools" and a lost hour. Pin **Python 3.12** for ProofPay (broadest wheel coverage, fully supported by SQLAlchemy 2.x / FastAPI / pydantic 2).

**Dependencies: exact, transitively, via a lockfile. Non-negotiable.** This is where "works on my machine" actually comes from, and it's almost never your direct dependencies. It's the transitive ones. You wrote `pydantic`, someone installs on Tuesday and gets 2.9, someone installs on Thursday and gets 2.11, and a validator behaves differently. Or `rapidfuzz` bumps a scorer's tie-breaking and your matching thresholds shift under you. A hackathon has no time to debug a bug that only exists on one laptop.

So: **pin every transitive dependency in a committed lockfile; let the patch-level interpreter float.**

The other real sources of breakage, in the order they'll bite you:
1. **Uncommitted config.** Someone has `DASHSCOPE_API_KEY` in their shell, nobody else does, and the app 500s. Fix: `.env.example` committed, `.env` gitignored, `pydantic-settings` with explicit failure — the app should crash on startup with "missing DASHSCOPE_API_KEY", not produce a mystery 500 mid-demo.
2. **Local database state.** Person A's SQLite has hand-inserted rows that make the demo work. Fix: `*.db` in `.gitignore`, and a `uv run python -m proofpay.seed --reset` script that is the *only* way anyone gets data.
3. **Native builds.** See the cross-OS section.
4. **Path and case assumptions.** See the cross-OS section.

### Pick one toolchain: `uv`

| Option | Verdict for this team |
|---|---|
| `pip` + hand-written `requirements.txt` | Only pins what you typed. `pip freeze` "fixes" this by pinning your platform's resolution, which then fails on someone else's OS. Reject. |
| `pip-tools` | Real lockfiles, but a two-file `.in`/`.txt` dance, and `pip-compile` output is resolved *for the platform that ran it* — you'd need per-OS lock files for a Windows+macOS team. Extra ceremony. |
| Poetry | Solid, cross-platform lock, but ~3x slower on install and lock, and its venv/shell semantics are one more thing to explain to the git-new teammate. |
| Docker / devcontainer | The correct answer for production parity, the wrong answer for day 1. Docker Desktop on Windows plus bind-mount file watching plus rebuild-on-dependency-change will cost you more hours than it saves in a 72-hour window. |

**Use `uv`.** It is the current consensus default for new Python applications: one static Rust binary that replaces pip, virtualenv, pyenv and pip-tools; it *installs the Python interpreter itself*, so version drift stops being a human problem; and `uv.lock` is a **universal cross-platform lockfile** — one file, resolved for all markers, so Windows/macOS/Linux teammates get the same versions from the same lock. It's also fast enough (10–100x pip) that nobody skips `sync` out of impatience, which is the actual failure mode of every other tool.

Commit `pyproject.toml`, `uv.lock`, and `.python-version`. The whole onboarding is:

```bash
# once
curl -LsSf https://astral.sh/uv/install.sh | sh     # macOS/Linux
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"   # Windows

# every time you pull
uv sync --frozen        # exact lock, fails loudly if pyproject and lock disagree
uv run pytest -q
uv run uvicorn proofpay.main:app --reload
```

Rules: **nobody runs bare `pip install`.** Adding a dep is `uv add rapidfuzz` (which updates `pyproject.toml` + `uv.lock` in one shot), and the lock change goes in the PR. In CI, always `uv sync --frozen` — that's what turns "the lockfile is stale" into a red build instead of a Thursday-night mystery.

Don't bother exporting `pylock.toml` (PEP 751). It's the standardised future and uv can emit it via `uv export --format pylock.toml`, but the ecosystem's install side still doesn't handle extras/dependency groups well. Use it only if a deployment target demands plain `pip`.

**Do write a Dockerfile — on day 3, for deployment, not for development.** Multi-stage, `COPY uv.lock pyproject.toml` then `uv sync --frozen --no-dev`. Deploying to Alibaba Cloud wants a container; your laptops don't.

### Frontend side

- **Node 22 LTS.** Commit `.nvmrc` containing `22` and add `"engines": { "node": ">=22 <23" }` to `package.json` so a mismatched teammate gets a warning rather than a Vite crash.
- **One package manager, one lockfile.** Pick npm, commit `package-lock.json`, and add `"packageManager": "npm@10.x"`. A repo containing both `package-lock.json` and `pnpm-lock.yaml` is a guaranteed hour of confusion. CI and teammates use **`npm ci`**, never `npm install` — `ci` installs the lock exactly and errors if the lock is out of sync with `package.json`.
- Vite dev server proxies `/api` to `http://127.0.0.1:8000`. Use `127.0.0.1`, not `localhost` — on some Windows setups `localhost` resolves to IPv6 `::1` while uvicorn binds IPv4, and you get a connection-refused that looks like a code bug.

### Windows vs macOS vs Linux

**Line endings.** Commit a `.gitattributes` on hour one, before there is any history to churn:

```gitattributes
* text=auto eol=lf
*.sh   text eol=lf
*.ps1  text eol=crlf
*.png binary
*.jpg binary
*.jpeg binary
```

Without this, the Windows teammate's editor rewrites every line of a file they touched two characters of, and every PR becomes an unreviewable 400-line diff. This single file prevents more merge pain than any branching policy.

**Paths.** `pathlib.Path` everywhere, never string concatenation, never a literal `/` or `\` in a path. Storage keys (for the OSS adapter) are always forward-slash strings and are *never* derived from `os.path` — keep the filesystem path and the object key as separate concepts from the start, or the local→OSS swap will produce keys like `receipts\2026\abc.png`.

**Case sensitivity.** macOS and Windows filesystems are case-insensitive; your Linux CI and your Alibaba ECS box are not. `from proofpay.Models import X` will work on two laptops and fail in production. Lowercase module names, and let CI catch it.

**Native wheels.** The rule: *prefer packages that ship prebuilt wheels for cp312 on win_amd64, macosx_arm64, and manylinux.* Specifically for this project:
- **Fuzzy matching: use `rapidfuzz`, not `fuzzywuzzy`/`python-Levenshtein`.** rapidfuzz ships wheels everywhere; `python-Levenshtein` historically needs a compiler on Windows. It's also faster and MIT.
- **Pillow**: fine, wheels for everything. Do not pin an ancient version — old Pillow has no 3.12 wheels.
- **bcrypt / passlib**: this is the classic Windows compile trap, and you almost certainly don't need it. A hackathon demo does not need real password auth (see the cut list). If you truly need hashing, use `argon2-cffi` (good wheels) or `hashlib.scrypt` from the stdlib. Do not import `passlib` — it drags in the exact problem you're avoiding.
- **psycopg**: use `psycopg[binary]` when you move to Postgres, never plain `psycopg2`.

**Timezone.** Pakistan is UTC+05:00 with no DST — the one genuinely easy part of this problem. Store everything as timezone-aware UTC, convert to `Asia/Karachi` only at the display edge, and use `zoneinfo` (stdlib). On Windows `zoneinfo` needs `tzdata` installed — add `tzdata` as an explicit dependency now, because the failure (`ZoneInfoNotFoundError`) will otherwise appear only on one teammate's machine, which is precisely the class of bug this section exists to kill.

---

## 2. Git workflow for 4 people over 3 days

### Shape

**Trunk-based with short-lived branches and squash-merge PRs.** No `develop`, no release branches, no git-flow. Those exist to manage release trains you don't have.

- `main` is protected: no direct pushes, require CI green, require 1 approval.
- Branches: `<type>/<area>-<what>`, e.g. `feat/rules-duplicate-detection`, `feat/api-verify-endpoint`, `fix/matcher-tz-offset`, `chore/ci-pytest`. Types: `feat|fix|chore|docs`. Not a religion — it exists so `git branch -a` tells you who's doing what without asking.
- **Squash merge, always.** Four people's messy WIP commits, linearised into one commit per feature. It makes `git log` readable during the demo write-up and makes reverts trivial.
- Delete the branch on merge.

### Avoid merge hell by dividing *files*, not just tasks

The single most effective anti-conflict move is a **day-0 interface commit** merged before anyone else starts:

```
proofpay/schemas.py     # PaymentClaim, MerchantTxn, FieldEvidence, MatchResult, DecisionState enum
proofpay/extract/base.py  # class Extractor(Protocol): def extract(self, image: bytes) -> RawExtraction
proofpay/match/base.py    # def score(claim, candidates) -> list[MatchCandidate]  (raise NotImplementedError)
proofpay/rules/base.py    # def decide(match_result, signals) -> Decision  (raise NotImplementedError)
```

Real types, stub bodies. Now four people can work in parallel against a contract instead of against each other. Ownership:

- **A** — FastAPI routes, persistence, storage adapter, seed script
- **B** — vision extraction + normalisation (`extract/`)
- **C** — candidate retrieval, fuzzy scoring, duplicate detection, rules engine (`match/`, `rules/`)
- **D** — React frontend, demo flow, evidence panel

Conflicts then only happen in genuinely shared files: `schemas.py`, `pyproject.toml`/`uv.lock`, and `main.py`. So: **shared-file changes are announced in the group chat and merged the same hour.** Never sit on a `schemas.py` change overnight.

**Alembic head conflicts** deserve a specific ruling: two people generating migrations in parallel produces multiple heads, and resolving that at 1am is miserable. For a hackathon, **don't add Alembic until the schema stops moving** (probably day 3, when you point at Postgres). Until then, `Base.metadata.create_all()` plus a `--reset` seed script. When you do adopt Alembic, one named person owns migrations.

### PR discipline

- **Under ~400 changed lines, opened and merged the same day.** Not a style rule — a big PR sits unreviewed, diverges from main, and becomes a conflict bomb. If a feature is big, land it in two PRs behind a flag.
- **Review is a 10-minute skim, not a gate.** Look for: does it match the agreed interface, will it break the demo path, are there tests for the rules/matching logic. Do not bikeshed naming.
- **The 30-minute rule:** if CI is green and nobody has reviewed within 30 minutes, the author may merge and post the link in chat. Blocking on review is how hackathon teams stall at 3am. Correctness is defended by CI and by the always-shippable-main rule, not by ceremony.
- Everyone runs `git config pull.rebase true` on day 0 and **rebases onto main at least twice a day**. Ten small rebases hurt far less than one big one.

### CI (30 minutes to set up, pays for itself by hour six)

One GitHub Actions workflow on PR and push to main:

```yaml
- uses: astral-sh/setup-uv@v5
- run: uv sync --frozen
- run: uv run ruff check .
- run: uv run pytest -q
- run: npm ci --prefix frontend && npm run --prefix frontend build
```

Keep it under 90 seconds. The frontend `build` step matters more than it looks: it catches TypeScript errors the dev server tolerates, which is exactly the class of bug that surfaces when you deploy an hour before judging.

### For the teammate new to collaborative git

Give them this card, and give them a module they own outright (frontend or extraction) so their early mistakes can't block anyone.

```bash
git switch main && git pull                 # start of every task
git switch -c feat/ui-evidence-panel
# ... work ...
git add -A && git commit -m "add evidence panel"
git push -u origin feat/ui-evidence-panel   # then open PR on GitHub

# main moved while you worked:
git switch main && git pull
git switch feat/ui-evidence-panel
git rebase main
# conflict? open the file, fix the <<<<<<< markers, then:
git add <file> && git rebase --continue
# panicking? this is always safe:
git rebase --abort
```

Three hard rules, stated plainly:
1. **Never `git push --force` to `main`.** On your own branch after a rebase, use `git push --force-with-lease` — it refuses if someone else pushed to your branch.
2. **Never `git reset --hard` or `git checkout -- .` when you have work you care about.** Say "I'm stuck" first. `git stash` is the safe pause button.
3. **Commit is not push, and push is not merge.** Your work is only visible to others after push.

And reassurance that's actually true: almost nothing in git is unrecoverable once committed — `git reflog` finds it. The only real losses are uncommitted work and force-pushes. So commit often.

---

## 3. Testing strategy

You have maybe 15% of your time for tests. Spend it where a bug would be *silent* and would *survive to the demo*. The rules engine and the matcher are exactly that: they produce a plausible-looking answer that is wrong, and no exception tells you. UI bugs, by contrast, are loud and self-reporting. Test accordingly.

**Test these:** normalisers, fuzzy scoring, duplicate detection, the decision rules engine, the vision-output parser, one API contract test per endpoint.
**Don't test these:** React components, SQLAlchemy models (you're testing the ORM), Alembic migrations, auth, error-page rendering, anything CRUD-shaped. **No E2E browser tests** — your demo rehearsals are the E2E suite, and they're run by humans who will notice things Playwright wouldn't.

Target: **whole suite under 10 seconds.** A suite people don't run is worth zero, and the thing that stops people running it is latency, not laziness.

### The rules engine: decision tables + golden files

The decision logic is the intellectual core of ProofPay and the thing judges will poke at. Treat the rules as **data, tested exhaustively**, not as branching code tested anecdotally.

Put cases in a file, not in test bodies:

```yaml
# tests/golden/decisions.yaml
- id: exact_ref_and_amount
  signals: {ref_id_match: exact, amount_match: exact, name_score: 1.0, time_delta_s: 12, already_allocated: false, tamper_flags: []}
  expect:  {state: VERIFIED, reasons: [REF_EXACT, AMOUNT_EXACT, TIME_WITHIN_TOLERANCE]}

- id: ref_match_but_txn_allocated
  signals: {ref_id_match: exact, amount_match: exact, name_score: 1.0, time_delta_s: 12, already_allocated: true, tamper_flags: []}
  expect:  {state: DUPLICATE, reasons: [TXN_ALREADY_ALLOCATED]}

- id: amount_ok_name_weak_no_ref
  signals: {ref_id_match: none, amount_match: exact, name_score: 0.62, time_delta_s: 90, already_allocated: false, tamper_flags: []}
  expect:  {state: NEEDS_REVIEW, reasons: [NO_REF_ID, NAME_BELOW_THRESHOLD]}
```

```python
CASES = yaml.safe_load(Path("tests/golden/decisions.yaml").read_text())

@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_decision_table(case):
    d = decide(Signals(**case["signals"]))
    assert d.state == DecisionState[case["expect"]["state"]]
    assert sorted(r.code for r in d.reasons) == sorted(case["expect"]["reasons"])
```

Four things this buys you that ad-hoc tests don't:

- **Assert on reason *codes*, never on prose.** Codes are the API; the human sentence is presentation. If you assert on strings, every copy tweak breaks tests and people start deleting tests.
- **Totality.** Add a test that asserts `decide()` never returns `None` and never raises across the cartesian product of your signal buckets (a few hundred combinations — instant). A rules engine with an unreachable fall-through is a demo that shows a blank verdict.
- **Reachability.** Assert all five states appear somewhere in the golden set. If `SUSPICIOUS` is unreachable, you've built four states and a dead branch, and you'd rather learn that on day 2 than from a judge.
- **Versioning.** `Decision.rules_version = "2026-08-22.3"`, asserted in the goldens. When someone deliberately changes a rule, the diff of expected outcomes shows up **in the PR** — that diff *is* the review. This is the single highest-value review artifact in the project. If you use `syrupy`, `pytest --snapshot-update` regenerates the file and the reviewer reads the delta.

### Fuzzy matching: bands, boundaries, properties

Never assert exact float scores — you'll be updating tests all weekend. Assert three things instead:

**1. Ordering (the property that actually matters).**
```python
def test_name_scores_are_ordered():
    s = name_score
    assert s("Muhammad Ali", "Muhammad Ali") > s("Muhammad Ali", "M. Ali") \
         > s("Muhammad Ali", "Muhammad Akram") > s("Muhammad Ali", "Fatima Khan")
```
This survives any tuning of the scorer while still catching a genuinely broken one.

**2. Threshold boundaries, driven by the config constant.**
```python
@pytest.mark.parametrize("a,b,expected", [
    ("Muhammad Ali",  "M. Ali",          True),
    ("Muhammad Ali",  "Muhammad A.",     True),
    ("Muhammad Ali",  "Ali Muhammad",    True),   # token-set order, documented decision
    ("Muhammad Ali",  "Muhammad Akram",  False),  # shared first token must NOT carry it
    ("Abdul Rehman",  "Abdur Rahman",    True),   # transliteration variance
])
def test_name_threshold(a, b, expected):
    assert (name_score(a, b) >= settings.NAME_MATCH_THRESHOLD) is expected
```
Read the threshold from config so that *changing the threshold breaks a test loudly*. A silently retuned threshold is how a demo starts approving things it shouldn't. `("Muhammad Ali", "Muhammad Akram")` is the case worth agonising over — Pakistani naming means a naive token ratio will happily match those.

**3. Properties, with Hypothesis, for the normalisers only.** Keep this to four or five properties, `max_examples=50`, `deadline=None`; property tests are addictive and can eat a whole afternoon.
```python
@given(st.text())
def test_normalise_is_idempotent(s):
    assert normalise_name(normalise_name(s)) == normalise_name(s)

@given(st.text(), st.text())
def test_score_is_symmetric(a, b):
    assert name_score(a, b) == pytest.approx(name_score(b, a))

def test_score_of_identical_is_one():
    assert name_score("Ayesha Siddiqui", "Ayesha Siddiqui") == 1.0
```

**Amount and timestamp normalisation are table tests, and they're where the real bugs live.** `"Rs. 1,500.00"`, `"PKR 1500"`, `"1,500/-"`, `"Rs 1 500"`, `"1500.00 PKR"` → `Decimal("1500.00")`. Never floats — `Decimal`, or integer paisa. And explicitly test the timestamp tolerance boundary in both directions, plus the offset trap: a receipt showing `14:32` PKT against a feed row stored as `09:32Z` is a match, and the test that proves it is the test that saves your demo.

Pass datetimes in explicitly rather than reaching for `freezegun` — if your matcher takes `now` as an argument, you don't need a time-mocking library at all, and that's a better design anyway.

### Testing around the non-deterministic vision model

**No test ever calls DashScope.** Not "usually" — never, in the default suite. It's slow, flaky, costs money, and fails when hotel wifi dies.

Three implementations behind one Protocol:

```python
class Extractor(Protocol):
    def extract(self, image: bytes) -> RawExtraction: ...

class QwenVLExtractor:      # real, DashScope
class FixtureExtractor:     # replays tests/fixtures/vision/<sha256-of-image>.json
class StubExtractor:        # returns a canned RawExtraction, or raises, on demand
```

Selected by env var: `PROOFPAY_EXTRACTOR=qwen|fixture|stub`. This one seam serves **three** purposes — tests, parallel development (C and D don't wait for B), and **demo insurance when the venue network fails**. It is the highest-leverage design decision in the project; make it on day 0.

Then:

**Recorded fixtures.** A `scripts/record_vision.py --record` run, done once per receipt image, that saves the raw model response to `tests/fixtures/vision/<sha256>.json`. Commit these — they're a few KB each and they are the only reproducible record of what the model actually does.

**Contract test over every recording** — this is the test that earns its keep:
```python
@pytest.mark.parametrize("path", sorted(FIXTURE_DIR.glob("*.json")), ids=lambda p: p.stem)
def test_every_recorded_response_parses(path):
    raw = json.loads(path.read_text())
    result = parse_vision_response(raw)
    assert isinstance(result, (PaymentClaim, ExtractionError))
    if isinstance(result, PaymentClaim):
        assert result.amount is None or result.amount > 0
        assert result.provider in KNOWN_PROVIDERS
```
It proves that a prompt or schema change didn't break parsing, with zero network.

**Adversarial parser tests — hand-written, not recorded.** This is where real 2am failures come from, so write these deliberately:
```python
@pytest.mark.parametrize("body", [
    '```json\n{"amount": "1500"}\n```',        # markdown fence
    'Sure! Here is the JSON:\n{"amount": 1500}', # chatty preamble
    '{"amount": "Rs. 1,500.00"}',                # string where number expected
    '{"amount": null, "provider": "easypaisa"}', # partial extraction
    '{"amount": 1500,}',                         # trailing comma
    '{}', '', 'I cannot read this image.',       # refusal / empty
])
def test_parser_never_explodes(body):
    r = parse_vision_response(body)
    assert isinstance(r, (PaymentClaim, ExtractionError))  # never an unhandled exception
```
The requirement is not "extract correctly" — it's "**degrade to `NEEDS_REVIEW`, never to a 500**." A partially-extracted claim with a missing field must flow through the pipeline as low confidence, because that is what will happen on a judge's blurry screenshot.

**Live tests exist but are opt-in.** Mark them `@pytest.mark.live`, deselect by default, run them manually once a day and before the freeze.

### pytest configuration

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q --strict-markers -m 'not live'"
markers = [
  "live: hits real DashScope; run manually",
  "golden: decision-table cases",
]
filterwarnings = ["error::DeprecationWarning:proofpay.*"]
```

`--strict-markers` catches typo'd markers instead of silently running everything. Key `conftest.py` fixtures:

```python
@pytest.fixture
def client(tmp_path):
    app.dependency_overrides[get_extractor] = lambda: FixtureExtractor()
    app.dependency_overrides[get_storage]  = lambda: LocalStorage(tmp_path)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
```
FastAPI's `dependency_overrides` is the whole reason to inject the extractor and storage as dependencies rather than importing them — that decision is what makes this testable at all. Use `tmp_path` for the storage adapter (it also proves the adapter isn't secretly writing to a hardcoded path, which is what would break the OSS swap).

### One dataset for tests and demo

Build **one** `tests/data/merchant_feed.json` of ~30 transactions, deliberately engineered to contain: an exact ref-ID match, a name-variant-only match, two transactions with identical amounts minutes apart, one already allocated to another order, one 40 minutes outside tolerance, and several near-misses. Plus 6–8 committed receipt images with recorded vision fixtures.

The same dataset seeds the demo. One source of truth means a passing test suite is meaningful evidence that the demo works — which is the only reason a hackathon team should write tests at all.

---

## 4. Using reference repos legally and safely

### Licence tiers, decided before you `uv add`

**Safe to depend on and to borrow from, with attribution:** MIT, BSD-2/3, Apache-2.0, ISC, MIT-CMU (Pillow), PSF. Apache-2.0 adds two obligations people forget: preserve any `NOTICE` file, and mark files you modified. Both are cheap.

**Weak copyleft — MPL-2.0, LGPL:** usable as a dependency (file-level / dynamic-link scope), but read carefully if you're vendoring source. In a hackathon, just avoid it if there's a permissive alternative.

**Hard stop — GPL-2.0/3.0 and especially AGPL-3.0.** GPL makes the derivative work GPL. **AGPL's copyleft triggers on *network* use**, which is precisely a hosted demo: putting AGPL code in your FastAPI backend and showing a judge the deployed URL is a distribution event, and it obliges you to release all of ProofPay under AGPL. That is not a hypothetical for this project — it is a live risk in the document/OCR ecosystem. Concretely:

- **`PyMuPDF` / `fitz` is AGPL-3.0** (or paid commercial). Extremely tempting for receipt/PDF handling. Do not use it. Use `pypdfium2` (Apache-2.0/BSD) or stay in `Pillow`.
- **`pdf2image` is MIT but shells out to poppler, which is GPL.** The wrapper's licence is not the tool's licence.
- **PyQt is GPL** (PySide is LGPL). Irrelevant here, but it's the classic trap.
- Your actual planned stack is clean: FastAPI, Starlette, SQLAlchemy, Alembic, pydantic, rapidfuzz, uvicorn, httpx, React, Vite are all MIT/BSD/Apache-2.0. Tesseract, if you fall back to it, is Apache-2.0. Good.

**Check the licence before adding the dependency, not after.** Retrofitting a licence problem the night before submission means ripping out working code.

### Fork vs clone-for-reference vs copy — the practical difference

- **Fork** — your repo inherits their history *and* their licence, and every obligation travels with it. It's also the most visible thing a judge can see. Fork only when you are genuinely contributing back upstream. Never fork as a way to start a project.
- **Clone for reference** — clone it, read it, understand the approach, **close it**, then write your own implementation from understanding. No obligations whatsoever, because ideas and techniques aren't copyrightable — only expression is. This is legitimate and it's how good engineers learn fast. The discipline is real, though: don't have their file open in a split pane while you type.
- **Copy** — the licence applies to every copied line. Retain the copyright header, add attribution, and accept whatever terms come with it.

### Rule of thumb

> **Depend, don't vendor. Read, don't paste. Under ~20 lines from a permissive repo: keep the header and add a source comment. Over that: either add it as a dependency or write your own. If you can't name the licence, you can't use it.**

### The originality risk is separate from the legal risk

Hackathons judge *your* work, and rules typically require the submission to be built during the event. Vendoring a large chunk of an existing reconciliation or OCR project can be perfectly licence-compliant and still lose you the competition — or get you disqualified. Judges reading your repo will spot a 2,000-line file whose style doesn't match the rest.

The defensive move is also the credibility move: a **"Prior art and references"** section in the README listing repos and papers you read but did not copy, and how your approach differs. That reads as rigour, not liability. Pair it with a `THIRD_PARTY_NOTICES.md` (generate it: `uv run pip-licenses --format=markdown --with-license-file`). Ten minutes, and it's a genuine differentiator against teams who ignored it.

If your competition rules require disclosing AI-assisted code, disclose it. And note that AI-generated code doesn't exempt you from licence diligence — you still own the result.

### One project-specific hazard: the receipt images

You are handling payment screenshots containing real names, phone numbers, and amounts. **Do not scrape real Easypaisa/JazzCash screenshots from the internet, WhatsApp groups, or forums**, and do not commit real ones with visible PII. Generate synthetic receipts (an HTML template screenshotted at phone dimensions is fine and takes 20 minutes) or use the team's own transactions with the numbers redacted, with everyone's consent. Commit only the synthetic set. On a fintech project judged in a country with data-protection expectations, "we built a synthetic receipt generator so we never handled real customer data" is a slide, not an apology.

---

## 5. Execution discipline

### Write the demo script before you write any code

On day 0, before the first commit, write the literal 3-minute narration. Then build **only what appears in it.** Something like:

1. Merchant dashboard, an open order for PKR 4,500. Customer uploads an Easypaisa screenshot → **VERIFIED**, with the evidence panel: ref ID exact, amount exact, name "Muhammad Ali" ~ "M. Ali" 0.91, timestamp within 2 minutes.
2. The same screenshot uploaded against a *different* order → **DUPLICATE**, showing which order already claimed that transaction. *(This is the moment that wins the room — it's the thing a human reviewer would miss.)*
3. A screenshot with an edited amount → **SUSPICIOUS**, with tamper-evidence observations listed as *observations*, plus a mismatched-amount evidence row.
4. A screenshot whose transaction simply isn't in the feed → **UNMATCHED**, one click to **NEEDS_REVIEW**.
5. Fifteen seconds on the rules version and the reason codes: *"we never output a fraud percentage — we output evidence and a state, and the merchant decides."*

Every backlog item now gets one question: does it appear in those three minutes? If no, it's day-4 work, which is to say it doesn't exist.

### Build a vertical slice on day 1, never layer by layer

By end of day 1, `main` must do: **upload → `StubExtractor` → hardcoded feed → real rules engine → real UI showing a verdict**, deployed somewhere with a URL. Ugly is fine. Then spend days 2–3 replacing stubs with real components one at a time.

Teams that build "the whole data layer, then the whole matching layer, then the UI" have nothing to show at hour 48 and integrate under panic. Teams that own a working thin slice on day 1 are never at risk of a zero.

### "Always shippable main"

**`main` must, at every moment, start with one command and complete the demo path.** Enforced by CI plus one habit: anything half-finished lands behind an env flag rather than sitting on a branch.

```
PROOFPAY_EXTRACTOR=stub|fixture|qwen
PROOFPAY_TAMPER_CHECKS=on|off
```

Note the payoff: the flag that lets C merge before B's Qwen integration is finished is the *same* flag that saves your demo when the conference wifi drops. Flags in a hackathon aren't over-engineering; they're insurance with a development-speed dividend.

### Timeboxing

- **Two standups a day.** 10 minutes at start, 5 minutes at 16:00: what's done, what's next, what's blocked. Standing up, no laptops.
- **90-minute work blocks**, one card each. Twelve cards on a board (To Do / Doing / Done), not a backlog — if it doesn't fit on the board, it's not happening.
- **The 45-minute rule:** stuck for 45 minutes, you *must* post in the group chat. Not "may". The most expensive thing in a hackathon is one person silently burning four hours on a dependency error while three others could have solved it in five minutes. Say this out loud on day 0 so the newest member knows asking is compliance, not weakness.
- **Integrate every evening**, all four branches, before anyone sleeps. Never integrate for the first time on the final day.

### The cut list — written on day 0, ranked, before you're panicking

Deciding what to cut while behind and exhausted produces bad decisions. Decide now, in order of what dies first:

1. Authentication / multi-tenancy → one hardcoded demo merchant
2. Postgres + Alembic → SQLite (keep the SQLAlchemy layer clean so the swap is a URL change, and say so on the architecture slide)
3. Alibaba OSS → local storage adapter (**keep the adapter interface** — that's the architecture point; the implementation is 30 lines)
4. Multi-provider support → **Easypaisa done properly**, others degrade gracefully to `NEEDS_REVIEW`. Four half-working providers is strictly worse than one that works.
5. Batch upload, pagination, search, real-time updates, mobile responsive, analytics dashboard, PDF export
6. Tamper-evidence beyond two signals (EXIF/re-encode artefacts and font/alignment anomalies are enough to make the point)

**Never cut:** the five states, the per-field evidence breakdown, duplicate detection, the rules-version stamp. That set *is* the product thesis. Cutting duplicate detection to add a second provider would be trading your best demo moment for a worse one.

### The last six hours

- **T−6h: record a backup video demo**, while everything works and you're not yet panicking. Screen recording plus narration, 3 minutes. If live demo dies, you have a demo. Nobody has ever regretted doing this; plenty of teams have regretted skipping it.
- **T−4h: code freeze.** `main` is locked to bugfixes on the demo path only. New features after this point have a strongly negative expected value.
- **T−4h to T−1h: rehearse three times, with a timer**, on the actual machine and network you'll present with. You will find at least two things — a slow cold-start, a stale seed row, a console error visible in a screenshot. That's the point.
- **A reset button.** `uv run python -m proofpay.seed --reset` returns the demo to a known state in under 5 seconds. Rehearse using it. A demo you can restart is a demo that can't be killed by one bad click.
- **Roles:** one driver, one narrator, two silent. Do not pass the keyboard around. The narrator owns the story; the driver owns the clicks and never improvises off-script.
- **Prepare the three questions judges will ask**, and agree the answers now:
  - *"What if someone photoshops the screenshot perfectly?"* → "Then it's a well-formed claim that still won't reconcile against the merchant's trusted feed. The screenshot is never the source of truth — that's the design."
  - *"What's your false-positive rate?"* → "We don't emit a fraud score, so that's the wrong frame. We emit five states with per-field evidence, and ambiguity routes to NEEDS_REVIEW rather than guessing. Here's the rule version that produced this decision."
  - *"Why not just call the payment provider's API?"* → "Where an API is available, this reconciles against it — the merchant feed is an adapter. In practice small Pakistani merchants don't have that access, which is the whole reason this problem exists."
- **Don't present from a laptop that's also running a build**, and disable notifications. Someone's WhatsApp preview appearing mid-demo is a real and avoidable way to lose the room.

---

**Sources:** [uv vs Poetry vs pip (2026)](https://www.danilchenko.dev/posts/uv-vs-pip-vs-poetry/) · [Python Dependency Management in 2026 — Cuttlesoft](https://cuttlesoft.com/blog/2026/01/27/python-dependency-management-in-2026/) · [Poetry vs uv vs Hatch (2026)](https://pythonresources.com/guides/poetry-vs-uv-vs-hatch/) · [uv — Locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/) · [pylock.toml specification](https://packaging.python.org/en/latest/specifications/pylock-toml/) · [What is PEP 751?](https://pydevtools.com/handbook/explanation/what-is-pep-751/)