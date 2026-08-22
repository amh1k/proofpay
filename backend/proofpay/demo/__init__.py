"""Demo dataset generation, seeding, and clock utilities.

This package contains everything related to the demo/hackathon dataset:
  - clock.py:  Deterministic time anchor (no datetime.now() anywhere)
  - (future)   Seed script, manifest reader, image builder

All demo data flows through manifest.json — the single source of truth.
The seed script reads the manifest and populates the database.
Images are committed as binary files and never regenerated at seed time.
"""
