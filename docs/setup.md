# ProofPay — Local Setup

## Do we all need identical versions?

**Interpreter: same minor version. Packages: exactly identical.**

| Thing | Must match? | Why |
|---|---|---|
| Python **minor** version (3.12) | Yes | 3.12 vs 3.13 differ in stdlib behaviour and, more often, in **wheel availability** — a package with no wheel for your version compiles from source, which on Windows means installing Visual C++ Build Tools and losing an hour. |
| Python **patch** version (3.12.4 vs 3.12.14) | No | Never matters. |
| Python **packages** | **Yes, exactly, including transitive ones** | This is where "works on my machine" actually comes from. |
| Node **major** version (22 LTS) | Yes | Same wheel-style reasoning for native modules. |
| Operating system | No | The lockfile is cross-platform and adapters keep storage portable. |

**You do not have to manage the Python version yourself.** `uv` reads `.python-version`,
downloads CPython 3.12 if the machine doesn't have it, and builds the virtualenv from it. A
teammate with only Python 3.10 installed gets a correct 3.12 environment without noticing.

The failure mode teams actually hit is not the interpreter. It is that you installed `pydantic`
2.13 on Tuesday, a teammate installed 2.15 on Thursday, a validator behaves differently, and the
app now misbehaves on exactly one laptop — usually the one running the demo. And it is almost
never a direct dependency; it is something three levels down that nobody typed.

So: **pin every transitive dependency in a committed lockfile, and let the patch version float.**

`pyproject.toml` declares what we *depend on* (loose ranges, for humans).
`uv.lock` declares what actually *gets installed* (exact pins with hashes, for machines).
Both are committed. `uv.lock` is **universal** — one file resolved for Windows, macOS and Linux
together, so all four machines get the same versions from the same lock.

---

## First-time setup

### 1. Install uv (once per machine)

**Windows (PowerShell):**

```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**macOS / Linux:**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

If you would rather not run an install script, `pip install uv` works too.

uv replaces pip, virtualenv, pyenv and pip-tools with one binary. Nothing else needs installing —
not even Python.

### 2. Set up the backend

```bash
cd backend
uv sync
uv run alembic upgrade head
```

That is the whole setup. It creates `.venv`, fetches Python 3.12 if needed, installs the exact
locked versions, and brings the local database schema to the current migration head.

### 3. Check it works

```bash
uv run pytest
uv run uvicorn proofpay.main:app --reload
```

Open <http://127.0.0.1:8000/health> — expect `{"status":"ok", ...}`.
Interactive API docs are at <http://127.0.0.1:8000/docs>.

> Use `127.0.0.1`, not `localhost`. On some Windows setups `localhost` resolves to IPv6 `::1`
> while uvicorn binds IPv4, producing a connection-refused that looks like a code bug.

---

## Every time you pull

```bash
cd backend
uv sync --frozen
uv run alembic upgrade head
```

`--frozen` installs the lockfile exactly and **fails loudly** if `pyproject.toml` and `uv.lock`
disagree. That turns "someone forgot to commit the lock" into an obvious error instead of a
mystery bug at 2am. Applying migrations after the sync is safe to repeat and ensures local schema
changes are present before the application starts.

---

## Adding a dependency

**Nobody runs a bare `pip install`.** It works for you and breaks for everyone else.

```bash
uv add rapidfuzz          # runtime dependency
uv add --dev pytest-cov   # development-only
```

This updates `pyproject.toml` and `uv.lock` together. Commit **both**, and mention it in the PR so
teammates know to re-run `uv sync`.

**Check the licence before adding, not after.** MIT / BSD / Apache-2.0 / ISC are fine. Avoid
GPL and especially **AGPL** — AGPL's copyleft triggers on *network* use, so deploying a demo URL
containing AGPL code would oblige us to release all of ProofPay under AGPL. Two live traps in this
problem space:

- **`PyMuPDF` / `fitz` is AGPL-3.0.** Tempting for receipt handling. Use `pypdfium2` or Pillow.
- **`fuzzywuzzy` / `python-Levenshtein` are GPL.** We use `rapidfuzz` (MIT), which needs no helper.

---

## Configuration

No `.env` file is required. Every setting has a working default, so a fresh clone runs immediately
with SQLite, local file storage, and the offline extractor — no cloud account, no API key.

To override anything, copy `.env.example` to `.env`. `.env` is gitignored.
**Never commit a real credential**, and never paste an API key into a chat or a PR.

---

## Local data

`*.db` is gitignored, and seeded data is produced by a script — never by hand.

This matters more than it sounds. The classic hackathon failure is that the demo only works on one
laptop because that person hand-inserted a row weeks ago and forgot. If the seed script is the only
way anyone gets data, the demo is reproducible on any machine.

---

## Platform notes

- **Line endings.** `.gitattributes` normalises to LF in the repository, so Windows and macOS
  contributors don't produce whole-file diffs against each other.
- **Native builds.** `bcrypt` and `Pillow` ship prebuilt wheels for Python 3.12 on all three
  platforms, so no C compiler is needed. This is the practical reason we pin 3.12 rather than
  chasing the newest release.
- **Database.** Development uses SQLite, which needs no server and no account. The same SQLAlchemy
  models run against PostgreSQL in deployment; only `PROOFPAY_DATABASE_URL` changes.
