"""Shared settings. Change rules here, not inside the pipeline code."""

from datetime import date
from pathlib import Path

TODAY = date(2026, 10, 20)  # fixed so results are reproducible (demo day)

# Folders
DATA = Path("data")
EXTERNAL = DATA / "external"     # downloaded public data (not committed, see prepare/)
DOCXPAND = EXTERNAL / "docxpand"
SEC_DOWNLOADS = EXTERNAL / "sec_subscriptions"
SEC_FORMS = DATA / "sec_forms"   # the 4 blank forms, committed: public filings, no personal data
DEMO = DATA / "demo"             # the 40 investors, built by prepare/build_demo.py (committed)
SAMPLES = Path("samples")        # 6 of them with IDs cropped, for a quick run (committed)
DATASET = DEMO if (DEMO / "labels.json").exists() else SAMPLES  # full set unless someone removed it
OUTPUT = Path("output")

# Business rules (Maples' Cayman/CIMA matrix; confirm with the client)
ADDRESS_MAX_AGE_DAYS = 90        # proof of address issued within 3 months
OWNERSHIP_THRESHOLD = 0.10       # 10% (Canada/EU baseline is 25%)

# Demo set
N_INVESTORS = 40
SEED = 7
