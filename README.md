# maples_kyc_poc — Maples KYC Document Extraction (Proof of Concept)

McGill MMA Capstone (BUSA 693) with Maples Group, AML/KYC & Data Management.
**Synthetic and public data only. 

## What it does

An individual investor uploads an ID and a subscription agreement, as messy as real uploads are
(phone photos, scans, sideways, shadows). The pipeline:

```
uploads ──► classify ──► extract (2 methods per document) ──► validate ──► cross-check ──► Excel tracker
```

| Document | Method A | Method B |
|---|---|---|
| Passport / ID card (photo or scan) | MRZ: OCR, parse, verify check digits | Printed zone: find each MRZ value printed on the card |
| Subscription agreement (PDF, scan or photo) | PDF text layer | OCR (after flattening shadows and straightening the page) |

**Traffic light**

- 🟢 **Green**: two independent sources agree (two methods, or ID and subscription agreement)
- 🟡 **Amber**: one source only, sources disagree, or a check digit fails → analyst confirmation upgrades this to a green
- 🔴 **Red**: missing, expired, unreadable, or the subscription contradicts the ID → act on it

A check digit alone never earns green: it can't tell `G` from `6` (ICAO values 16 and 6 collide mod 10),
and it can flag an `O`/`0` misread without saying which one is right.

## Data

| Document | Source | Licence |
|---|---|---|
| Passports, ID cards | [DocXPand-25k](https://github.com/QuickSign/docxpand): fictional IDs with generated faces, photographed and scanned on real backgrounds, with an answer key for every field | CC BY-NC-SA 4.0 (non-commercial; images not committed) |
| Subscription agreements | Blank Reg A subscription agreements (EX1A-4) from SEC EDGAR: Commune Omni Fund, CWS Investments, Red Oak Capital Fund VI, REI Capital Growth. Filled with the same synthetic person as the ID | Public filings |

We only use **blank** SEC forms. Executed agreements filed with the SEC contain real investors' details.

**How DocXPand images are made** (Lerouge et al., QuickSign, 2024): the document designs are fictional,
names and numbers come from `faker`, and faces are generated with Stable Diffusion. Each fictional
document is composited onto a real photo or scan of an ID (the real document is replaced at the same
position; signatures and numbers inpainted; every image reviewed by the authors for leaked personal data).
So the backgrounds, e.g. the facing page of a passport booklet, are real imagery; the identity is not.

Planted issues: date of birth, name or address on the subscription differing from the ID,
a date of birth left blank, and (from DocXPand itself) expired IDs.

## Setup

```bash
brew install tesseract                 # Windows: UB-Mannheim build; Linux: apt install tesseract-ocr
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Build the data, then run

```bash
python -m prepare.docxpand                         # streams ~18 GB, keeps ~400 IDs (takes about an hour)
SEC_CONTACT="you@example.com" python -m prepare.sec_forms   # SEC asks for a contact email
python -m prepare.build_demo                       # 40 investors into data/demo/
python run_pipeline.py                             # writes output/kyc_tracker.xlsx
```

Then open the notebooks: `data_overview`, `id_extraction`, `subscription_extraction`, `results`.

## Repo layout

The folders follow the pipeline, in the order the data flows through it. Each stage is its own
folder or file, so one person can work on a stage without touching the others.

```
maples_kyc_poc/
│
├── run_pipeline.py        START HERE. Runs every stage below for each investor, in order
├── config.py              Business rules (CIMA: 90-day proof of address, 10% ownership), paths,
│                          demo settings. Rules live here so nobody hunts for them in the code
│
├── classify.py            STAGE 1. What is this file? Passport / ID card / subscription agreement,
│                          from its content only. Real uploads don't come in labelled folders
│
├── extract/               STAGE 2. Read the fields, two independent ways per document
│   ├── pages.py           Shared plumbing: file → page images → words with positions. Also fixes
│   │                      shadows and tilt before OCR, which is what makes phone photos readable
│   ├── mrz.py             The passport/ID-card machine-readable zone: parsing + check digits.
│   │                      Pure rules from the ICAO 9303 standard, no OCR, so it's easy to test
│   ├── id_document.py     Passport and ID card: method A reads the MRZ, method B checks the
│   │                      printed zone shows the same values
│   └── subscription.py    Subscription agreement: method A = PDF text layer, method B = OCR.
│                          One parser for every issuer's layout (it knows label wordings, not positions)
│
├── validate/              STAGE 3. Decide how far to trust each field
│   └── checks.py          The traffic-light rules, and the cross-check of what the investor wrote
│                          on the subscription against what their ID shows
│
├── evaluate.py            STAGE 4. Score everything against the answer key, so every claim we
│                          make to the client is a measured number, not a guess
├── report.py              STAGE 5. The Excel tracker an analyst would open
│
├── notebooks/             The story for the team and the client. They import the pipeline
│   │                      (no copied code), so they always show what the code really does
│   ├── data_overview.ipynb            What the documents look like and where they come from
│   ├── id_extraction.ipynb            Passports and ID cards; why a check digit alone isn't enough
│   ├── subscription_extraction.ipynb  Accuracy by method and by digital / scanned / photo
│   └── results.ipynb                  Metrics, method comparison, tracker, worked examples
│
├── prepare/               One-off scripts that build the test data. Not part of the pipeline:
│   │                      the pipeline never imports them, and Maples would never need them
│   ├── docxpand.py        Downloads a slice of DocXPand (the fake passports and ID cards)
│   ├── sec_forms.py       Downloads the 4 blank SEC subscription forms; records where each blank is
│   └── build_demo.py      Builds 40 investors: fills each form with the ID holder's details, plants
│                          issues, makes pages look scanned or photographed, writes the answer key
│
├── requirements.txt       Python packages
├── README.md              This file
└── CLAUDE.md              Project brief and code-style rules (read by Claude Code, useful to humans too)
```

**Created when you run it (never committed, see `.gitignore`):**

```
├── .venv/                 Your Python environment (~1 GB)
├── data/
│   ├── external/          Downloads: DocXPand images + labels, SEC forms. DocXPand images sit on
│   │                      real passport backgrounds, so they must never go on GitHub
│   └── demo/              The 40 built investors (INV-001 … INV-040) + labels.json, the answer key
├── output/
│   └── kyc_tracker.xlsx   The tracker from the last run
└── __pycache__/           Python's compiled-file cache, recreated automatically; ignore it
```

## Working together

- Extractors return a plain dict `{field: value}`. Validated fields are records
  `{document, field, value, light, sources, note}`. Keep those shapes and new methods plug in.
- Branch per task, pull request to merge, one teammate reviews.
- Never commit `data/external/`, `data/demo/` or `output/` (regenerate instead). DocXPand images
  are composited on real passport backgrounds and must stay off GitHub.

## Next steps

1. Proof of address as a third document type.
2. An LLM extractor as a third method, compared in the method-comparison sheet.
3. Replace the SEC layouts with Maples' blank subscription form if received.
