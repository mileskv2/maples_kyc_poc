"""Two independent reads of an ID document (passport, or ID card front + back).

Method A (mrz):     OCR the machine-readable zone and parse it. Check digits make it self-verifying.
Method B (printed): OCR the visual zone and look for each MRZ value as it would be printed
                    ("BLANCHARD", "03.12.1983"...). It works on any design because it doesn't need
                    to know where the labels are, only what the MRZ claims.

A check digit alone can't tell 'G' from '6', so green later needs both methods to agree.
"""

import re
import unicodedata
from datetime import datetime

import pytesseract
from PIL import ImageOps

from extract.mrz import parse_td1, parse_td3
from extract.pages import flatten_lighting, page_images

MRZ_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"
MRZ_LINE = re.compile(r"^[A-Z0-9<]{26,50}$")
TD1_LINE2 = re.compile(r"^\d{7}[MF<]\d{7}[A-Z]{3}")


# Field labels printed on almost any ID, in the languages DocXPand uses
ID_LABEL_WORDS = ["surname", "given name", "nationalit", "date of birth", "birth date", "expiry", "prénom",
                  "geburts", "staatsangeh", "vornamen", "date/date", "/nom",
                  "anschrift", "/address", "/authority", "/height"]  # back of an ID card


def id_label_hits(text):
    text = text.lower()
    return sum(w in text for w in ID_LABEL_WORDS)


def upright_by_labels(img):
    """For a page without an MRZ (an ID card front), the rotation where ID labels become readable."""
    gray = ImageOps.autocontrast(ImageOps.grayscale(img))
    best, best_hits = img, 0
    for candidate in (img, gray):  # pale print sometimes survives only one of the two
        for angle in (0, 90, 270, 180):
            rotated = candidate.rotate(angle, expand=True, fillcolor=255) if angle else candidate
            hits = id_label_hits(pytesseract.image_to_string(rotated))
            if hits > best_hits:
                best, best_hits = rotated, hits
            if hits >= 3:
                return rotated, hits
    return best, best_hits


def mrz_lines(img):
    config = f"--psm 3 -c tessedit_char_whitelist={MRZ_CHARS}"
    lines = [l.replace(" ", "") for l in pytesseract.image_to_string(img, config=config).splitlines()]
    return [l for l in lines if MRZ_LINE.match(l) and l.count("<") >= 2]


def tidy_filler(line, length):
    """Trailing '<' runs are often misread as K or E: cut the run, then pad back to full length."""
    line = re.sub(r"(<[<KEX]*|K{3,}[<KEX]*)$", "", line)
    return line.rstrip("<").ljust(length, "<")[:length]


def rebuild_td1_line2(line):
    """18 fixed characters, 11 of filler, then the final check digit."""
    last = line[-1] if line[-1].isdigit() else "<"
    return line[:18] + "<" * 11 + last


def rebuild_td3_line2(line):
    """28 fixed characters, then the optional field (usually all filler), then the final check digit.
    OCR misreads runs of '<' as K/E/X and miscounts them, so rebuild the middle from its fixed size."""
    core, middle, last = line[:28], line[28:-1], line[-1:]
    middle = re.sub(r"[KEX]", "<", middle)
    middle = "<" * 15 if set(middle) <= {"<"} else middle.ljust(15, "<")[:15]
    return core + middle + last


def read_mrz(img):
    """Returns (format, fields, checks); format is None when no MRZ is found."""
    lines = mrz_lines(img)
    # Passport: line 1 starts 'P<'; line 2 follows. Tesseract often drops long '<' runs, so line 2
    # may come out short; its first 28 characters are what matter.
    starts = [i for i, l in enumerate(lines[:-1]) if "P<" in l[:3] and len(lines[i + 1]) >= 28]
    if starts:
        line1, line2 = lines[starts[-1]], lines[starts[-1] + 1]
        line1 = line1[line1.find("P<"):]
        shift = min(max(len(line2) - 44, 0), 2)  # a stray leading character
        candidates = [rebuild_td3_line2(line2[i:]) for i in range(shift + 1)]
        fields, checks = max((parse_td3(tidy_filler(line1, 44), c) for c in candidates),
                             key=lambda result: sum(result[1].values()))
        return "TD3", fields, checks
    # ID card: line 2 is unmistakable (birth date, check, sex, expiry); line 1 is above, names below
    rows = [i for i, l in enumerate(lines) if TD1_LINE2.match(l) and i > 0]
    if rows:
        i = rows[-1]
        line1 = tidy_filler(lines[i - 1], 30)
        line2 = rebuild_td1_line2(lines[i])
        line3 = tidy_filler(lines[i + 1], 30) if i + 1 < len(lines) else ""
        fields, checks = parse_td1(line1, line2, line3)
        return "TD1", fields, checks
    return None, {}, {}


def find_mrz(img):
    """Photos come sideways or upside down: try each rotation, stop when the check digits all pass."""
    best = (None, {}, {}, img)
    for angle in (0, 90, 270, 180):
        rotated = img.rotate(angle, expand=True, fillcolor=255) if angle else img
        fmt, fields, checks = read_mrz(rotated)
        if fmt and (best[0] is None or sum(checks.values()) > sum(best[2].values())):
            best = (fmt, fields, checks, rotated)
        if checks and all(checks.values()):
            break
    return best


def plain(text):
    """Upper case, accents removed: the MRZ writes 'Adèle' as 'ADELE'."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().upper()


def printed_forms(field, value):
    """The ways an MRZ value can appear in the printed zone."""
    if field in ("date_of_birth", "expiry_date"):
        try:
            d = datetime.strptime(value, "%y%m%d")
        except ValueError:
            return []
        if field == "date_of_birth" and d.year > 2026:
            d = d.replace(year=d.year - 100)
        return [d.strftime(f) for f in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d", "%d %m %Y", "%d.%m.%y")]
    return [value] if value else []


def squash(text):
    """Keep only what matters for matching, and fold look-alikes (the same font fools both reads)."""
    return re.sub(r"[^A-Z0-9.\-/]", "", plain(text)).translate(str.maketrans("OIl", "011"))


def confirm_in_print(mrz_fields, text):
    """For each MRZ field, the printed form found in the visual zone, or None."""
    squashed = squash(text)
    words = set(re.findall(r"[A-Z0-9]+", plain(text)))
    found = {}
    for field, value in mrz_fields.items():
        if field == "sex":
            continue  # a single letter is always 'found' somewhere; it proves nothing
        if field in ("surname", "given_names"):
            # Names must match as whole words, or 'NICOLASK' would be found inside 'NICOLAS K...'
            parts = re.findall(r"[A-Z0-9]+", plain(value))
            found[field] = value if parts and all(p in words for p in parts) else None
            continue
        if field in ("date_of_birth", "expiry_date"):
            # Digit-only fields: allow one misread digit in the print (a wrong digit always breaks the
            # check digit, so the MRZ side already guards against the G/6-style collision)
            printed_dates = re.findall(r"\d{2}[.\-/ ]\d{2}[.\-/ ]\d{2,4}", plain(text))
            hits = [f for f in printed_forms(field, value)
                    if any(len(d) == len(f) and sum(a != b for a, b in zip(d, f)) <= 1 for d in printed_dates)]
            found[field] = hits[0] if hits else None
            continue
        hits = [f for f in printed_forms(field, value) if len(f) >= 2 and squash(f) in squashed]
        found[field] = hits[0] if hits else None
    return found


def enlarge(img, target=2400):
    """MRZ characters in a small phone photo are a few pixels tall; Tesseract wants ~30."""
    scale = target / max(img.size)
    return img.resize((int(img.width * scale), int(img.height * scale))) if scale > 1 else img


def read_id_document(paths):
    """paths: one passport image, or an ID card's sides in any order."""
    images = [flatten_lighting(enlarge(page_images(p)[0])) for p in paths]
    fmt, fields, checks, upright = None, {}, {}, []
    for img in images:  # the MRZ is on the passport data page or the back of the card
        found = find_mrz(img)
        if found[0] and not fmt:
            fmt, fields, checks = found[:3]
        # No MRZ on this side (an ID card front): turn it upright using its printed labels instead
        upright.append(found[3] if found[0] else upright_by_labels(img)[0])
    printed_text = "\n".join(pytesseract.image_to_string(img) for img in upright)
    # Drop the MRZ itself from the printed text, or the MRZ would end up confirming its own misreads
    printed_text = "\n".join(l for l in printed_text.splitlines() if l.count("<") < 2)
    return {"format": fmt, "mrz": fields, "mrz_checks": checks,
            "printed": confirm_in_print(fields, printed_text), "printed_text": printed_text}
