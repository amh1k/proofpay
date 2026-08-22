# ProofPay — Local Setup

## Do we all need identical versions?

**No for the interpreter. Yes for the dependencies.**

| Thing | Must match? | Why |
|---|---|---|
| Python **interpreter** (3.10.x / 3.11.x / 3.12.x) | No — 3.10+ is enough | The code uses no version-specific behaviour. Patch versions never matter. |
| Python **packages** | **Yes — pinned exactly** | This is where "works on my machine" actually comes from. |
| Node **runtime** | No — 20 LTS or newer | |
| Node **packages** | **Yes — via lockfile** | Same reason. |
| Operating system | No | Adapters keep paths and storage portable. |

The failure mode teams hit is never "you have Python 3.11 and I have 3.10". It is that one person
installed FastAPI 0.141 and another got 0.115 a week later, an argument was renamed in between, and
the app now crashes only on one machine — usually the machine doing the demo.

So: **pin the packages, relax about the interpreter.**

Dependency versions are frozen in [`backend/requirements.lock.txt`](backend/requirements.lock.txt).
Everyone installs from that file, so all four machines get byte-identical packages.

`pyproject.toml` declares what we *depend on* (loose ranges, for humans).
`requirements.lock.txt` declares what we *install* (exact pins, for machines).
Both are committed. Never install a package ad hoc — add it to `pyproject.toml`, then regenerate the lock.

---

## Backend setup

Requires Python **3.10 or newer** (`python --version` to check).

**Windows (PowerShell):**

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.lock.txt
pip install -e ".[dev]" --no-deps
```

**macOS / Linux:**

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock.txt
pip install -e ".[dev]" --no-deps
```

`--no-deps` on the second command matters: it installs ProofPay itself as an editable package
without letting pip re-resolve and drift away from the locked versions.

### Verify the install

```bash
pytest
uvicorn proofpay.main:app --reload
```

Then open <http://127.0.0.1:8000/health> — you should see `{"status":"ok", ...}`
and <http://127.0.0.1:8000/docs> for the interactive API.

### Configuration

No `.env` file is required. Every setting has a working default, so a fresh clone runs immediately.

To override anything, copy `.env.example` to `.env`. `.env` is gitignored —
**never commit real credentials**, and never paste an API key into a chat or a commit.

---

## Adding a dependency

Do not run a bare `pip install <package>`; it will work for you and break for everyone else.

1. Add the package to `dependencies` in `backend/pyproject.toml`.
2. Reinstall and regenerate the lock:

   ```bash
   pip install -e ".[dev]"
   pip freeze --exclude-editable > requirements.lock.txt
   ```

3. Commit **both** files together, and say so in the PR — everyone else then reruns
   `pip install -r requirements.lock.txt`.

---

## Platform notes

- **Line endings.** `.gitattributes` normalises everything to LF in the repository, so Windows and
  macOS contributors will not produce whole-file diffs against each other.
- **Windows wheels.** `bcrypt` and `Pillow` ship prebuilt wheels for Windows, so no C compiler is
  needed. If a build is ever attempted from source, upgrade pip first: `python -m pip install -U pip`.
- **Database.** Development uses SQLite, which needs no server. The same SQLAlchemy models run
  against PostgreSQL / ApsaraDB RDS in deployment; only `PROOFPAY_DATABASE_URL` changes.
