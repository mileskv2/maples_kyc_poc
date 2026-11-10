"""Send one document (image or PDF) to Gemini, get back translated + structured KYC data,
then apply deterministic rule checks in Python (expiry, proof-of-address age, confidence)."""
import json
import mimetypes
import os
import time
from datetime import date, datetime
from pathlib import Path

from google import genai
from google.genai import types

from mrz import cross_check, parse_mrz
from schema import KYCDocument

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
# If the main model is busy (503) or rate-limited (429), try these in order.
FALLBACK_MODELS = ["gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-flash-latest"]
REVIEW_THRESHOLD = 0.85          # matches the 85% target in the Maples proposal
POA_MAX_AGE_DAYS = 90            # proof of address must be < 3 months old

PROMPT = """You are a KYC document analyst for a fund administrator in the Cayman Islands.
The attached document may be in Chinese, Arabic or another language.

Tasks:
1. Identify the document type.
2. Read ALL text in the original script (Arabic is right-to-left).
3. Translate the full document faithfully into English. Do not summarise or omit.
4. Extract the KYC fields defined in the schema.
   - Keep names in the original script AND give the standard English form
     (Chinese: pinyin, surname first as on the document; Arabic: common romanisation)
     plus other plausible spellings in name_variants.
   - Convert every date to Gregorian YYYY-MM-DD. If the document uses the Hijri
     (Islamic) calendar or the Minguo / other calendar, convert it and explain in calendar_notes.
   - Use an empty string for anything that is not on the document. NEVER guess or invent values.
   - If there is a Machine Readable Zone (MRZ, lines with '<' fillers at the bottom of a
     passport or ID card), copy each line into mrz_lines EXACTLY, character by character,
     keeping every '<'. Do not correct or "fix" it. Passports have 2 lines of 44 characters.
   - For passports, take visual-zone values (name, number, dates) from the printed page, not from the MRZ.
5. Give honest confidence scores (lower them for blurry, handwritten or ambiguous text).
6. In review_flags list anything an analyst should double-check.
Return only JSON that matches the schema."""


def _client(api_key: str | None = None) -> genai.Client:
    key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("No API key. Set GEMINI_API_KEY or paste it in the app sidebar.")
    # 60 s timeout and no hidden SDK retries: our own loop below retries and switches models
    return genai.Client(api_key=key, http_options=types.HttpOptions(
        timeout=60_000, retry_options=types.HttpRetryOptions(attempts=1)))


def _mime(filename: str) -> str:
    mt, _ = mimetypes.guess_type(filename)
    return mt or "application/octet-stream"


def call_llm(file_bytes: bytes, filename: str, api_key: str | None = None,
             model: str = DEFAULT_MODEL, retries: int = 3) -> dict:
    client = _client(api_key)
    part = types.Part.from_bytes(data=file_bytes, mime_type=_mime(filename))
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=KYCDocument,
        temperature=0,
    )
    last_err = None
    chain = [model] + [m for m in FALLBACK_MODELS if m != model]
    for m in chain:
        for attempt in range(retries):
            try:
                resp = client.models.generate_content(model=m, contents=[part, PROMPT], config=config)
                data = resp.parsed.model_dump(mode="json") if resp.parsed is not None else json.loads(resp.text)
                data["model"] = m          # record which model actually answered
                return data
            except Exception as e:
                last_err = e
                msg = str(e)
                if "404" in msg or "NOT_FOUND" in msg:
                    break                  # model not available to this key -> next model
                if "503" in msg or "UNAVAILABLE" in msg or "429" in msg or "RESOURCE_EXHAUSTED" in msg \
                        or "timeout" in msg.lower() or "timed out" in msg.lower():
                    if attempt == retries - 1:
                        break              # still busy -> next model
                    time.sleep(3 * (attempt + 1))
                    continue
                raise                      # other errors (bad key, bad file) -> show immediately
    raise RuntimeError(f"All models busy or unavailable. Last error: {last_err}")


def _parse(d: str):
    try:
        return datetime.strptime(d, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def apply_rules(doc: dict, today: date | None = None) -> dict:
    """Deterministic checks done in code, NOT by the LLM (auditable)."""
    today = today or date.today()
    flags = []

    exp = _parse(doc.get("expiry_date", ""))
    doc["is_expired"] = bool(exp and exp < today)
    if doc["is_expired"]:
        flags.append(f"Document expired on {exp.isoformat()}")

    if doc.get("doc_type") in ("proof_of_address", "bank_statement"):
        iss = _parse(doc.get("issue_date", ""))
        if iss is None:
            flags.append("Proof of address: issue date not found")
        elif (today - iss).days > POA_MAX_AGE_DAYS:
            flags.append(f"Proof of address older than 3 months (issued {iss.isoformat()})")

    mrz = parse_mrz(doc.get("mrz_lines") or [])
    doc["mrz_result"] = mrz
    if mrz:
        flags.extend(mrz.get("issues", []))
        if mrz.get("format") != "unrecognised":
            flags.extend(cross_check(doc, mrz))
        doc["mrz_status"] = "PASS" if mrz.get("valid") and not cross_check(doc, mrz) else "FAIL"
    else:
        doc["mrz_status"] = "N/A"
        if doc.get("doc_type") == "passport":
            flags.append("Passport but no MRZ detected")

    low = [f["name"] for f in doc.get("fields", []) if f.get("confidence", 1) < 0.8]
    if low:
        flags.append("Low-confidence fields: " + ", ".join(low))

    doc["rule_flags"] = flags
    doc["needs_human_review"] = bool(
        flags or doc.get("review_flags") or doc.get("overall_confidence", 0) < REVIEW_THRESHOLD
    )
    return doc


def process_file(file_bytes: bytes, filename: str, api_key: str | None = None,
                 model: str = DEFAULT_MODEL) -> dict:
    doc = call_llm(file_bytes, filename, api_key=api_key, model=model)
    doc["source_file"] = filename
    doc["processed_at"] = datetime.now().isoformat(timespec="seconds")
    return apply_rules(doc)


if __name__ == "__main__":
    # CLI: python extractor.py samples/*.png  -> results/results.json + results/kyc_results.xlsx
    import sys
    from excel_export import to_excel

    paths = [Path(p) for p in sys.argv[1:]]
    if not paths:
        sys.exit("usage: python extractor.py <file> [<file> ...]")
    results = []
    for p in paths:
        print(f"Processing {p.name} ...")
        results.append(process_file(p.read_bytes(), p.name))
        time.sleep(4)  # stay under free-tier per-minute limits
    out = Path("results"); out.mkdir(exist_ok=True)
    (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "kyc_results.xlsx").write_bytes(to_excel(results))
    print("Saved results/results.json and results/kyc_results.xlsx")
