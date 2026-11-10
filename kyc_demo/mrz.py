"""Deterministic MRZ (Machine Readable Zone) parsing + ICAO 9303 check-digit validation.
Supports TD3 (passports: 2 lines x 44) and TD1 (ID cards: 3 lines x 30).
No LLM involved here – this is the auditable part."""
import re
from datetime import date

WEIGHTS = (7, 3, 1)


def _val(c: str) -> int:
    if c.isdigit():
        return int(c)
    if c.isalpha():
        return ord(c.upper()) - 55        # A=10 ... Z=35
    return 0                              # '<' filler


def check_digit(s: str) -> str:
    return str(sum(_val(c) * WEIGHTS[i % 3] for i, c in enumerate(s)) % 10)


def _clean(line: str) -> str:
    line = (line or "").upper().replace(" ", "").replace("«", "<")
    return re.sub(r"[^A-Z0-9<]", "<", line)


def _date(yymmdd: str, kind: str) -> str:
    """MRZ YYMMDD -> YYYY-MM-DD. Birth dates in the future roll back a century; expiry is 20xx."""
    if not re.fullmatch(r"\d{6}", yymmdd):
        return ""
    yy, mm, dd = int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:])
    year = 2000 + yy
    if kind == "birth" and year > date.today().year:
        year -= 100
    try:
        return date(year, mm, dd).isoformat()
    except ValueError:
        return ""


def _name(field: str) -> tuple[str, str]:
    parts = field.split("<<", 1)
    surname = parts[0].replace("<", " ").strip()
    given = parts[1].replace("<", " ").strip() if len(parts) > 1 else ""
    return surname, re.sub(r"\s+", " ", given)


def parse_mrz(lines: list[str]) -> dict | None:
    lines = [_clean(l) for l in lines if l and l.strip()]
    if not lines:
        return None

    checks = {}
    if len(lines) >= 2 and len(lines[0]) >= 40 and len(lines[1]) >= 40:          # TD3 passport
        l1, l2 = lines[0].ljust(44, "<")[:44], lines[1].ljust(44, "<")[:44]
        fmt = "TD3 (passport)"
        surname, given = _name(l1[5:44])
        doc_no, dob, exp, opt = l2[0:9], l2[13:19], l2[21:27], l2[28:42]
        checks["document_number"] = check_digit(doc_no) == l2[9]
        checks["date_of_birth"] = check_digit(dob) == l2[19]
        checks["expiry_date"] = check_digit(exp) == l2[27]
        checks["personal_number"] = (check_digit(opt) == l2[42]) or (set(opt) == {"<"} and l2[42] in "<0")
        checks["composite"] = check_digit(l2[0:10] + l2[13:20] + l2[21:43]) == l2[43]
        out = dict(doc_code=l1[0:2].replace("<", ""), issuing_state=l1[2:5].replace("<", ""),
                   nationality=l2[10:13].replace("<", ""), sex=l2[20].replace("<", ""))
    elif len(lines) >= 3 and all(len(l) >= 28 for l in lines[:3]):               # TD1 ID card
        l1, l2, l3 = (l.ljust(30, "<")[:30] for l in lines[:3])
        fmt = "TD1 (ID card)"
        surname, given = _name(l3)
        doc_no, dob, exp = l1[5:14], l2[0:6], l2[8:14]
        checks["document_number"] = check_digit(doc_no) == l1[14]
        checks["date_of_birth"] = check_digit(dob) == l2[6]
        checks["expiry_date"] = check_digit(exp) == l2[14]
        checks["composite"] = check_digit(l1[5:30] + l2[0:7] + l2[8:15] + l2[18:29]) == l2[29]
        out = dict(doc_code=l1[0:2].replace("<", ""), issuing_state=l1[2:5].replace("<", ""),
                   nationality=l2[15:18].replace("<", ""), sex=l2[7].replace("<", ""))
    else:
        return {"format": "unrecognised", "valid": False, "checks": {},
                "issues": ["MRZ found but length/format not recognised (possible OCR error)"]}

    out.update(format=fmt, surname=surname, given_names=given,
               document_number=doc_no.replace("<", ""),
               date_of_birth=_date(dob, "birth"), expiry_date=_date(exp, "expiry"),
               checks=checks, valid=all(checks.values()))
    out["issues"] = [f"MRZ check digit failed: {k}" for k, ok in checks.items() if not ok]
    return out


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def cross_check(doc: dict, mrz: dict) -> list[str]:
    """Compare MRZ data with what is printed on the page (visual zone) as extracted by the LLM."""
    issues = []
    if doc.get("document_number") and mrz.get("document_number") and \
            _norm(doc["document_number"]) != _norm(mrz["document_number"]):
        issues.append(f"Document number mismatch: page '{doc['document_number']}' vs MRZ '{mrz['document_number']}'")
    for key, label in (("date_of_birth", "Date of birth"), ("expiry_date", "Expiry date")):
        if doc.get(key) and mrz.get(key) and doc[key] != mrz[key]:
            issues.append(f"{label} mismatch: page {doc[key]} vs MRZ {mrz[key]}")
    page_name = set(_norm_tokens(doc.get("subject_name_english", "")))
    mrz_name = set(_norm_tokens(mrz.get("surname", "") + " " + mrz.get("given_names", "")))
    if page_name and mrz_name and not (page_name & mrz_name):
        issues.append(f"Name mismatch: page '{doc.get('subject_name_english')}' vs MRZ "
                      f"'{mrz.get('surname')} {mrz.get('given_names')}'")
    return issues


def _norm_tokens(s: str) -> list[str]:
    return [t for t in re.split(r"[^A-Z]+", (s or "").upper()) if len(t) > 1]


if __name__ == "__main__":
    # ICAO 9303 official specimen (fictional "Utopia" passport)
    r = parse_mrz(["P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<",
                   "L898902C36UTO7408122F1204159ZE184226B<<<<<10"])
    print(r)
