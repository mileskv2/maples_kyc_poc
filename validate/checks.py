"""Turn raw extractions into one record per field, each with a traffic light.

    GREEN  confident: two independent sources agree (two methods, or two documents)
    AMBER  analyst should confirm: one source only, sources disagree, or a check digit fails
    RED    act on it: missing, expired, unreadable, or contradicts another document
"""

import re
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher

from config import TODAY

ID_FIELDS = ["surname", "given_names", "date_of_birth", "nationality", "document_number", "expiry_date"]
SUBSCRIPTION_REQUIRED = ["full_name", "date_of_birth", "street", "city"]
SUBSCRIPTION_OPTIONAL = ["citizenship", "ssn", "email", "phone"]  # not every issuer's form asks


def record(document, field, value, light, sources, note=""):
    return {"document": document, "field": field, "value": value,
            "light": light, "sources": sources, "note": note}


def plain(text):
    """Upper case, no accents: 'Adèle' and the MRZ's 'ADELE' should match."""
    return unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode().upper()


def same(a, b):
    """Compare on letters and digits only, ignoring word order (forms write 'First Last', MRZ 'LAST<<FIRST')."""
    if not a or not b:
        return False
    return sorted(re.sub(r"[^A-Z0-9]", " ", plain(a)).split()) == sorted(re.sub(r"[^A-Z0-9]", " ", plain(b)).split())


def appears_in(needle, haystack, threshold=0.85):
    """Fuzzy 'is this phrase somewhere in that text', tolerant of a few OCR slips."""
    needle = re.sub(r"[^A-Z0-9]", "", plain(needle))
    haystack = re.sub(r"[^A-Z0-9]", "", plain(haystack))
    if len(needle) < 4:
        return False  # too short to mean anything ('I' is in every text)
    best = 0
    for i in range(0, max(len(haystack) - len(needle), 0) + 1):
        best = max(best, SequenceMatcher(None, needle, haystack[i:i + len(needle)]).ratio())
        if best >= threshold:
            return True
    return False


def mrz_date(yymmdd, is_expiry):
    try:
        d = datetime.strptime(yymmdd, "%y%m%d").date()
    except (TypeError, ValueError):
        return None
    if not is_expiry and d > TODAY:  # birth dates are in the past
        d = d.replace(year=d.year - 100)
    return d.isoformat()


def us_date(text):
    """US subscription forms write MM/DD/YYYY."""
    try:
        return datetime.strptime(text, "%m/%d/%Y").date().isoformat()
    except (TypeError, ValueError):
        return text


# ---------- ID document ----------

def check_id(raw, kind):
    if not raw["format"]:
        return [record(kind, "document", None, "red", [], "machine-readable zone not found: request a clearer copy")]

    mrz = dict(raw["mrz"])
    mrz["date_of_birth"] = mrz_date(mrz.get("date_of_birth"), is_expiry=False)
    mrz["expiry_date"] = mrz_date(mrz.get("expiry_date"), is_expiry=True)
    checks, printed = raw["mrz_checks"], raw["printed"]

    out = []
    for f in ID_FIELDS:
        value = mrz.get(f)
        has_digit = f in checks
        digit_ok = checks.get(f, False)
        confirmed = printed.get(f) is not None

        # A check digit alone is not enough: it can't tell 'G' from '6' (values 16 and 6 collide mod 10)
        if not value:
            light, note = "red", "not readable"
        elif has_digit and digit_ok and confirmed:
            light, note = "green", "check digit passes, printed zone agrees"
        elif has_digit and digit_ok:
            light, note = "amber", "check digit passes but printed zone does not confirm"
        elif has_digit:
            light, note = "amber", "check digit fails: OCR misread somewhere in this field"
        elif confirmed:
            light, note = "green", "MRZ and printed zone agree"
        else:
            light, note = "amber", "MRZ only, printed zone does not confirm"

        if f == "expiry_date" and value and value < TODAY.isoformat():
            light, note = "red", "document expired"
        sources = ["mrz"] + (["printed"] if confirmed else [])
        out.append(record(kind, f, value, light, sources, note))
    return out


# ---------- Subscription agreement ----------

def check_subscription(raw):
    text, ocr = raw["text_layer"], raw["ocr"]
    out = []
    for f in SUBSCRIPTION_REQUIRED + SUBSCRIPTION_OPTIONAL:
        a, b = text.get(f), ocr.get(f)
        if f == "date_of_birth":
            a, b = us_date(a), us_date(b)
        sources = [s for s, v in (("text_layer", a), ("ocr", b)) if v]
        value = a or b
        if not value:
            if f in SUBSCRIPTION_REQUIRED:
                out.append(record("subscription", f, None, "red", [], "missing or unreadable"))
        elif same(a, b):
            out.append(record("subscription", f, value, "green", sources, "text layer and OCR agree"))
        elif a and b:
            out.append(record("subscription", f, value, "amber", sources, "text layer and OCR disagree"))
        else:
            out.append(record("subscription", f, value, "amber", sources, "scan or photo: OCR only"))
    return out


# ---------- Cross-document: what the investor wrote vs what their ID shows ----------

def cross_check(id_records, id_raw, subscription_records):
    ids = {r["field"]: r for r in id_records}
    subs = {r["field"]: r for r in subscription_records}
    if "surname" not in ids:
        return  # ID unreadable: nothing to compare against

    id_name = f"{ids['given_names']['value']} {ids['surname']['value']}"
    pairs = [("full_name", id_name, ids["surname"]), ("date_of_birth", ids["date_of_birth"]["value"], ids["date_of_birth"]),
             ("citizenship", ids["nationality"]["value"], ids["nationality"])]
    for field, id_value, id_record in pairs:
        claim = subs.get(field)
        if not claim or not claim["value"] or not id_value:
            continue
        if same(claim["value"], id_value):
            claim.update(light="green", note=claim["note"] + "; matches ID")
        elif claim["light"] == "green" and id_record["light"] == "green":
            claim.update(light="red", note=f"differs from ID ({id_value})")
        else:
            # One side was read with doubt: a mismatch may just be a reading error
            claim.update(light="amber", note=f"differs from ID ({id_value}); could be a reading error")

    # Address is printed on the ID but not in the MRZ: look for it in the ID's printed text
    # The address is checked as a unit: if one line is junk or both read the same, OCR has shifted a
    # line, and finding text on the ID proves nothing about which field it belongs to
    street, city = (subs.get(f, {}).get("value") or "" for f in ("street", "city"))
    address_read = len(street) >= 4 and len(city) >= 4 and not same(street, city)
    for field in ("street", "city"):
        claim = subs.get(field)
        if not claim or not claim["value"]:
            continue
        if not address_read:
            claim.update(light="amber", note="address only partly read: confirm")
        elif appears_in(claim["value"], id_raw["printed_text"]):
            claim.update(light="green", note=claim["note"] + "; also printed on ID")
        else:
            claim.update(light="amber", note="not found on the ID: confirm address")
