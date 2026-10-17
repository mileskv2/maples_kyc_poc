# Project brief

Context for anyone working on this repo, human or AI coding assistant. Read this before changing code.

## Project

McGill MMA Capstone (BUSA 693) with Maples Group (AML/KYC & Data Management, Montreal).
Team: Miles (lead), Cathy (co-lead, slides), Hazel (synthetic data), Yorkin (classify/extract demo).
Client contacts: Jervis, Andrew, Marc-Olivier. Final presentation April 2027.

Goal (client's words): drag an investor's documents into a model, extract the KYC fields, flag what is
missing, and show a traffic light for what was extracted correctly vs what a human must verify.
Start with individual investors; entities and ownership structures (directors, UBOs, trusts) come later.
For now: two document kinds (ID: passport or ID card; subscription agreement). More come later.

## Hard rules

- **Synthetic and public data only.** Maples will not share client documents. Never add real people,
  real passports, client names or anything that looks like client data. Flag it if you see some.
- **Never commit images or data.** `data/` and `output/` are gitignored. DocXPand images are fictional
  documents composited onto *real* passport/ID photos, so they must never go on GitHub. Commit
  notebooks without outputs (outputs would embed those images).
- **SEC forms: blank only.** Executed subscription agreements on EDGAR contain real investors' details.
- **Proof of concept, not production.** No auth, deployment, databases or heavy infrastructure.
  Push back on scope creep.
- Business rules are Maples' Cayman (CIMA) rules: proof of address within 90 days (unconfirmed vs a
  "6 years" note), 10% ownership threshold (Canada/EU use 25%). Keep rules in `config.py`.

## How code should be written

- Intermediate level: plain functions, standard library, pandas/openpyxl where useful. No clever tricks,
  no deep class hierarchies, no frameworks unless clearly needed.
- Readable first. Short functions, clear names, flat logic.
- Comments explain *why*, not *what*. Well commented but not verbose.
- Very brief docstrings (one line is usually enough).
- Keep visuals few and sharp. No plots that don't earn their place.
- Match the existing style of the repo before adding new patterns.
- Commit messages: plain, no AI co-author trailers.

## How the pipeline works

```
classify.py  → what each upload is (passport / ID card / subscription), from content only
extract/     → two independent methods per document
validate/    → traffic light per field + cross-check ID vs subscription
evaluate.py, report.py → metrics against data/demo/labels.json + output/kyc_tracker.xlsx
prepare/     → builds the test data; never imported by the pipeline
```

| Document | Method A | Method B |
|---|---|---|
| Passport / ID card (photo or scan) | MRZ (OCR, parse, check digits) | Printed zone: each MRZ value found printed on the card |
| Subscription agreement (PDF, scan, photo) | PDF text layer | OCR (after flattening shadows, deskewing) |

Traffic light: GREEN = two sources agree (two methods or two documents); AMBER = one source, sources
disagree, or a check digit fails; RED = missing, expired, unreadable, or contradicts the ID (only when
both sides were read confidently; otherwise amber "could be a reading error").
Investor status ignores contact fields (SSN, phone, email): scans only give one reading of them.

Contracts that keep the pieces pluggable:
- Extractors return a plain dict `{field: value}`.
- Validated fields are records `{document, field, value, light, sources, note}` (+ `investor_id`, `correct`).

Known findings (keep these in mind before "simplifying" the rules):
- A check digit alone is not trustworthy: `G` and `6` collide (16 vs 6 mod 10). Green needs the printed zone too.
- A failed check digit can't be repaired: swapping look-alikes (O/0, S/5, B/8) gives several candidates
  that all pass. Flag amber, don't guess.
- The printed-zone text must exclude the MRZ lines, or the MRZ "confirms" its own misreads.
- Tesseract's orientation detection is unreliable on these photos; trying 4 rotations and keeping the one
  whose check digits pass works better.
- Subscription labels: generic words ("Name") must be capitalised and start a column, or they match
  inside sentences ("in the name of").

## Data

| Document | Source | Notes |
|---|---|---|
| Passports, ID cards | DocXPand-25k (QuickSign, CC BY-NC-SA 4.0), streamed by `prepare/docxpand.py` | Fictional designs, faker values, Stable Diffusion faces, composited on real ID photos. 180 passports (3 designs) + 60 ID-card front/back pairs |
| Subscription agreements | 4 blank Reg A forms from SEC EDGAR (Commune Omni Fund, CWS Investments, Red Oak Capital Fund VI, REI Capital Growth) | Filled by `prepare/build_demo.py` with the ID holder's details; digital / scanned / photo |

Demo set: 40 investors in `data/demo/INV-xxx/` with neutral file names (`upload_1.jpg`...), answer key in
`data/demo/labels.json`. Planted: DOB / name / address mismatch, missing DOB; expired IDs come from DocXPand.

## Commands

```bash
python -m prepare.docxpand                                  # ~1 hour stream, resumable
SEC_CONTACT="you@example.com" python -m prepare.sec_forms   # SEC requires a contact email
python -m prepare.build_demo                                # 40 investors → data/demo/
python run_pipeline.py                                      # ~5 min → output/kyc_tracker.xlsx
python run_pipeline.py 5                                    # first 5 investors only (quick check)
```
Requires the Tesseract binary (`brew install tesseract`) plus `pip install -r requirements.txt`.

## Current status (Oct 17, 2026)

Working end to end on 40 investors (25 passports in 3 designs, 15 ID cards; subscriptions on 4 SEC
layouts, digital / scanned / photo), 96 files with neutral names:

| Metric | Result |
|---|---|
| Files classified correctly | 94/96 |
| Green precision (green fields that are correct) | 238/239 |
| Wrong values caught (amber/red, not green) | 48/49 |
| Planted issues flagged | 18/21 |
| Expired IDs flagged red | 4/4 |
| Field accuracy (final value) | 410/459 |

Single-method accuracy: subscription text layer 95%; subscription OCR 90% digital, 90% scanned,
79% photo; passport MRZ 63%; ID-card MRZ 43%. Takeaway: the traffic light is trustworthy (green is
almost always right) but ID photos still leave a lot of amber for analysts.

Known weak spots: ID MRZ on small/tilted photos; O/0 in document numbers; a partial OCR'd street can
match the ID and turn green (1 case); a full run takes ~10 min because IDs are OCR'd twice
(classification and extraction).

## Next tasks, in order

1. Tuesday demo: run `notebooks/results.ipynb` end to end; walk through one clean file, one mismatch,
   one missing field, and the G/6 case.
2. Improve ID reading where it fails most: alphanumeric document numbers (O/0) and short MRZ reads.
3. Third document type: proof of address (utility bill / bank statement), cross-checked against the
   ID name and the subscription address.
4. An LLM extractor as a third method, compared in the method-comparison sheet (API choice and budget TBD).
5. Replace the SEC layouts with Maples' blank subscription form once received.

## Open questions for the client

- Blank subscription agreement (Jervis to send).
- Are real submissions machine-readable or often blurry? (Our photo vs scan vs digital split answers
  "what if"; their answer tells us which number matters.)
- 90 days vs "6 years" for proof of address.
- LLM/API budget and any provider constraint (they use Microsoft Copilot).
- Is a dataset composited on real ID backgrounds (DocXPand) acceptable to them for the demo?
