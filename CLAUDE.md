# CLAUDE.md — project handoff

## Project

McGill MMA Capstone (BUSA 693) with Maples Group (AML/KYC & Data Management, Montreal).
Team: Miles (lead), Cathy (co-lead, slides), Hazel (synthetic data), Yorkin (classify/extract demo).
Client contacts: Jervis, Andrew, Marc-Olivier. Final presentation April 2027.

Goal (client's words): drag an investor's documents into a model, extract the KYC fields, flag what is
missing, and show a traffic light for what was extracted correctly vs what a human must verify.
Start with individual investors; entities and ownership structures (directors, UBOs, trusts) come later.

## Hard rules

- **Synthetic and public data only.** Maples will not share client documents. Never add real people,
  real passports, client names or anything that looks like client data. Flag it if you see some.
- **Proof of concept, not production.** No auth, deployment, databases or heavy infrastructure.
  Push back on scope creep.
- Business rules are Maples' Cayman (CIMA) rules: proof of address within 90 days (unconfirmed vs a
  "6 years" note), 10% ownership threshold (Canada/EU use 25%). Keep rules in `config.py`.

## How I want code written

- Intermediate level: plain functions, standard library, pandas/openpyxl where useful. No clever tricks,
  no deep class hierarchies, no frameworks unless clearly needed.
- Readable first. Short functions, clear names, flat logic.
- Comments explain *why*, not *what*. Well commented but not verbose.
- Very brief docstrings (one line is usually enough).
- Keep visuals few and sharp. No plots that don't earn their place.
- Match the existing style of the repo before adding new patterns.

## How the pipeline works

```
generate/  → synthetic investors (ground truth first) → passport PNG + subscription agreement PDF
extract/   → two independent methods per document
validate/  → traffic light per field + cross-check passport vs subscription
evaluate.py, report.py → metrics against labels.json + Excel tracker (output/kyc_tracker.xlsx)
```

| Document | Method A | Method B |
|---|---|---|
| Passport | MRZ (OCR + parse + check digits) | Printed zone (OCR labels) |
| Subscription agreement | PDF text layer | OCR of rendered page (works on scans) |

Traffic light: GREEN = two sources agree (two methods or two documents) or a checksum passes (IBAN);
AMBER = one source or sources disagree; RED = expired, unreadable, failed checksum, or contradiction.

Contracts that keep the pieces pluggable:
- Extractors return a plain dict `{field: value}`.
- Validated fields are records `{document, field, value, light, sources, note}` (+ `investor_id`, `correct`).

Known finding: an MRZ check digit alone is not trustworthy (OCR 'G' → '6' still passes, since 16 and 6
collide mod 10). A check digit only earns green when the printed zone agrees.

## Commands

```bash
python run_pipeline.py --sample      # 6 committed investors, fast
python -m generate.make_dataset      # build 50 investors into data/generated/
python run_pipeline.py               # run on them (~3-4 min, Tesseract)
python run_external.py               # public passports placed in data/external/passports/
```
Requires the Tesseract binary plus `pip install -r requirements.txt`.

## Current status (Oct 17, 2026)

50 investors / 100 documents: field accuracy 1018/1018, green precision 971/971,
planted issues detected 20/20, false red flags on clean files 0/30.
Heavily blurred passport photos are unreadable and flagged red (request new copy).

## Next tasks, in order

1. **`notebooks/results.ipynb`**: an overview notebook for the team and the client meeting. It should
   import the pipeline (not copy code), run it on the generated set, and show, briefly:
   - what the data is (one example passport and subscription agreement image),
   - the evaluation metrics table,
   - the method comparison (accuracy per method per field),
   - the investor tracker with traffic lights (styled DataFrame),
   - one or two worked examples (a clean file, a mismatch, the G/6 check-digit case).
   Short markdown between cells. At most one or two charts.
2. Run `run_external.py` on 30-50 Kaggle synthetic passports (`simongraves/passport-dataset`, check the
   licence; do not commit the images) and add the result to the notebook.
3. Third document type: proof of address (utility bill / bank statement), cross-checked against the
   passport name and the subscription address.
4. A document classifier so files no longer need labelled folders.
5. An LLM extractor as a third method, compared in the method-comparison sheet (API choice and budget TBD).

## Open questions for the client

- Blank subscription agreement (Jervis to send); replace our simplified layout with its structure.
- Are real submissions machine-readable or often blurry?
- 90 days vs "6 years" for proof of address.
- LLM/API budget and any provider constraint (they use Microsoft Copilot).
