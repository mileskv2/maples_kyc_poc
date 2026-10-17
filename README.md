# maples_kyc_poc — Maples KYC Document Extraction (Proof of Concept)

McGill MMA Capstone (BUSA 693) with Maples Group, AML/KYC & Data Management.
**All data in this repo is synthetic**: a fictional state ("Utopia", ICAO code `UTO`),
a fictional fund and fictional banks. No client data, ever.

## Data

`data/sample/` holds 6 synthetic individual investors, each with two documents:

| Folder | Document | Format |
|---|---|---|
| `passports/` | Passport (printed zone + MRZ) | PNG |
| `subscriptions/` | Fund subscription agreement | PDF |
| `labels.json` | Ground truth for every field, plus the planted scenario | JSON |

Scenarios include a clean file, an expired passport, a low-quality photo, a scanned
subscription agreement, and details on the subscription that differ from the passport.

## Notebooks

| Notebook | Purpose |
|---|---|
| `data_overview.ipynb` | What the two datasets look like |
| `passport_extraction.ipynb` | Passport fields: MRZ vs printed zone |
| `subscription_extraction.ipynb` | Subscription fields: PDF text layer vs OCR |
| `results.ipynb` | Metrics, method comparison, traffic-light tracker |

## Working together

- Branch per task, pull request to merge, one teammate reviews.
- Synthetic and public data only. Do not commit `data/generated/`, `data/external/` or `output/`.
