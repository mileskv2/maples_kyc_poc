"""Work out what each uploaded file is, from its content alone (file names mean nothing).

Rules, cheapest first:
  1. Words that only appear on subscription agreements  -> subscription
  2. A machine-readable zone: 2 x 44 characters is a passport, 3 x 30 an ID card
  3. ID field labels ("Surname", "Nationality"...), read at whichever rotation makes them legible:
     a passport if the word 'passport' is printed, otherwise an ID card (e.g. a card's front side)
Anything left over is 'unknown' and goes to an analyst.
"""

import pytesseract

from extract.id_document import enlarge, find_mrz, upright_by_labels
from extract.pages import flatten_lighting, full_text, page_images

SUBSCRIPTION_WORDS = ["subscriber", "subscription", "social security", "investor", "accredited", "joint owner",
                      "citizenship", "e-mail", "beneficial owner", "zip code", "telephone"]
PASSPORT_WORDS = ["passport", "passeport", "pasaporte", "reisepass"]


def count_hits(text, words):
    return sum(w in text for w in words)


def classify(path):
    """Returns (kind, reason)."""
    if count_hits(full_text(path).lower(), SUBSCRIPTION_WORDS) >= 2:
        return "subscription", "subscription-agreement wording"

    img = flatten_lighting(enlarge(page_images(path)[0]))
    fmt = find_mrz(img)[0]
    if fmt == "TD3":
        return "passport", "two-line MRZ (passport format)"
    if fmt == "TD1":
        return "id_card", "three-line MRZ (ID card format)"

    upright, hits = upright_by_labels(img)
    if hits >= 2:
        if count_hits(pytesseract.image_to_string(upright).lower(), PASSPORT_WORDS):
            return "passport", "ID labels and the word 'passport'"
        return "id_card", "ID labels, no MRZ (likely the front of a card)"
    return "unknown", "no wording or MRZ recognised"
