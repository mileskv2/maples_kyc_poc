# KYC Document Translator & Extractor – Proof of Concept

Upload a Chinese or Arabic KYC document (image or PDF) and the app will:

1. Identify the document type and read the original text
2. Translate the full document into English
3. Extract structured KYC fields (name in original script + English + spelling variants, document number, dates, address, issuer, MRZ)
4. Run deterministic rule checks in Python: expired documents, proof of address older than 3 months, passport MRZ check digits (ICAO 9303) and cross-check against the printed page, low-confidence fields → "needs human review"
5. Export everything to a formatted Excel workbook (Summary / All Fields / Translations / About)

> Design principle: the LLM reads, translates and extracts; the rules that decide are written in code so they are auditable. Final decisions stay with the analyst.

⚠️ **Demo data only.** The free Gemini tier may use inputs to improve Google's models. Never upload real client documents. All files in `samples/` are fictitious and watermarked "SAMPLE".

## 1. Get a free Gemini API key
1. Go to https://aistudio.google.com and sign in with a **personal** Google account (school accounts may be blocked from creating projects)
2. **Get API key → Create API key**, keep the default project
3. Never commit the key or paste it into slides/screenshots

## 2. Install (macOS / Linux)
```bash
cd kyc_demo
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export GEMINI_API_KEY="your-key"
python check_setup.py        # checks the key and finds a model that answers right now
```
Default model is `gemini-3.8-flash`. If it is busy (503) or unavailable (404), the code automatically falls back to other Flash models (`FALLBACK_MODELS` in `extractor.py`). To pin a model:
```bash
export GEMINI_MODEL="gemini-3.6-flash"
```

## 3. Run
**Web app (used for the live demo):**
```bash
streamlit run app.py
```
Upload files from `samples/`, click **Translate & extract**, then **Download Excel**.

**Command line (batch):**
```bash
python extractor.py samples/*.png      # writes results/results.json and results/kyc_results.xlsx
```

## 4. Sample documents (`samples/`, all fictitious)
| File | Content | Expected checks |
|---|---|---|
| cn_business_licence.png | Chinese business licence | OK |
| cn_utility_bill.png | Chinese electricity bill (Oct 2026) | OK |
| ar_commercial_registration.png | Arabic commercial registration with **Hijri dates** | Hijri → Gregorian; **expired** |
| ar_bank_statement.png | Arabic bank statement (Jun 2026) | **Proof of address older than 3 months** |

Sample content lives in `samples/templates/*.html`. To regenerate the images: `python tools/make_samples.py` (requires Playwright + Chromium).

For passports, use official **SPECIMEN** images (e.g. the EU PRADO public register). Make sure the two MRZ lines at the bottom are fully visible.

## 5. Live-demo safeguards
- Every successful run is saved to `results/` (git-ignored). If the network or API fails, click **Load last saved results** in the sidebar.
- Run all samples once the day before the meeting and record a screen capture as a backup.
- The free tier sometimes returns 429/503; the code retries and switches models automatically.

## Project structure
| File | Purpose |
|---|---|
| `schema.py` | Output fields the LLM must return (edit here to add/remove fields) |
| `extractor.py` | Prompt, Gemini call with model fallback, rule checks |
| `mrz.py` | MRZ parsing and ICAO 9303 check-digit validation (no LLM) |
| `excel_export.py` | Excel formatting |
| `app.py` | Streamlit UI |
| `check_setup.py` | Verifies the API key and model availability |
| `tools/make_samples.py` | Generates the fictitious sample documents |

## Limitations / next steps
- Accuracy has only been checked on a handful of fictitious samples; a proper evaluation against the 85% target needs anonymised real samples from Maples
- Missing-document detection by investor type (using the CIMA KYC requirements matrix) is not implemented yet
- Production deployment should run inside the client's environment (e.g. Microsoft Copilot Studio / Azure OpenAI), not a public free-tier API
- Machine translation assists analyst review and does not replace a certified/notarised translation where one is required
