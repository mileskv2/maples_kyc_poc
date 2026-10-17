"""Two independent ways to read a subscription agreement, on any issuer's layout.

Method A (text_layer): words embedded in the PDF. Exact, but scans and photos have none.
Method B (ocr):        Tesseract on the page image. Works on everything, makes mistakes.

Both feed the same parser. It knows the usual wordings of each label ("Date of Birth",
"Subscriber Date of Birth"...) but nothing about where a given issuer puts them: it reads the
value beside the label, or just below it when the form leaves the blank under the label.
"""

import re
from difflib import SequenceMatcher

from extract.pages import group_lines, ocr_words, text_layer_words

# Longest wordings first, so "Date of Birth" is not grabbed by a shorter label
LABELS = {
    "full_name": ["Name of Investor/Authorized Person", "First, Middle, Last Name", "Name of Subscriber", "Name"],
    "date_of_birth": ["Subscriber Date of Birth", "Date of Birth"],
    "citizenship": ["Citizenship (If Not a US Citizen, Specify Country)", "Country of Citizenship",
                    "Citizenship Country"],
    "street": ["Street Address", "Address Line 1", "Address"],
    "city": ["City, State, Zip Code", "City"],
    "ssn": ["Social Security Number", "Social Security #", "Subscriber SSN/Tax ID"],
    "email": ["Subscriber Email", "E-mail Address", "Email Address", "Email"],
    "phone": ["Daytime Phone #", "Mobile Phone Number", "Telephone Number", "Phone"],
}
# Labels we don't extract but must stop at, so their text never ends up inside a value
STOP_LABELS = ["Joint Owner", "Joint Subscriber", "if different than Owner", "Title", "Address Line 2",
               "State", "Zip Code"]

# What a valid value looks like; anything else is treated as not found
PATTERNS = {
    "date_of_birth": r"^\d{1,2}/\d{1,2}/\d{4}$",
    "ssn": r"^\d{3}-?\d{2}-?\d{4}$",
    "email": r"^\S+@\S+\.\S+$",
    "phone": r"^[\d\s()+.-]{7,}$",
}


def tokens(text):
    return re.sub(r"[^a-z0-9#@ ]", " ", text.lower()).split()


def similar(a, b):
    """OCR turns 'Birth' into 'Bith': accept close matches, but short words must be exact."""
    return a == b or (len(b) > 3 and SequenceMatcher(None, a, b).ratio() >= 0.8)


def phrase_matches(window, phrase):
    """Word by word, or for long labels the whole phrase at once (OCR mangles small italic words)."""
    if all(similar(a, b) for a, b in zip(window, phrase)):
        return True
    return len(phrase) >= 4 and SequenceMatcher(None, " ".join(window), " ".join(phrase)).ratio() >= 0.85


def all_phrases():
    phrases = [(field, tokens(p)) for field, ps in LABELS.items() for p in ps]
    phrases += [(None, tokens(p)) for p in STOP_LABELS]
    return sorted(phrases, key=lambda p: -len(p[1]))


def find_labels(lines):
    """Every label occurrence: (field, line index, first word, last word)."""
    found = []
    phrases = all_phrases()
    for li, line in enumerate(lines):
        words = [" ".join(tokens(w["text"])) for w in line]
        i = 0
        while i < len(line):
            # A label starts a line or a column (big gap before it), never mid-sentence
            gap = line[i]["x0"] - line[i - 1]["x1"] if i else 1e9
            match = None
            # Labels are capitalised ("Name:"); the same word inside a sentence is not ("in the name of").
            # One-word labels must also start a column; longer ones are distinctive enough on their own.
            capital = re.sub(r"^\W+", "", line[i]["text"])[:1].isupper()
            column_start = gap > 1.0 * (line[i]["y1"] - line[i]["y0"])
            if capital:
                for field, phrase in phrases:
                    if len(phrase) == 1 and not column_start:
                        continue
                    window = " ".join(words[i:]).split()[:len(phrase)]
                    if len(window) == len(phrase) and phrase_matches(window, phrase):
                        match = (field, phrase)
                        break
            if match:
                n_words = count_words(words[i:], len(match[1]))
                found.append((match[0], li, i, i + n_words - 1))
                i += n_words
            else:
                i += 1
    return found


def count_words(words, n_tokens):
    """How many OCR words cover n tokens (one OCR word like 'Middle,Last' can hold two)."""
    total = 0
    for k, w in enumerate(words, start=1):
        total += len(w.split()) or 1
        if total >= n_tokens:
            return k
    return len(words)


def value_after(lines, labels, field, li, start, end):
    """Words to the right of the label, up to the next label on the same line."""
    stops = [s for (_, l, s, _) in labels if l == li and s > end]
    stop = min(stops) if stops else len(lines[li])
    return " ".join(w["text"] for w in lines[li][end + 1:stop]).strip(" :_")


def value_below(lines, labels, li, start, end):
    """The next line's words under the label's column, when the blank sits below the label."""
    if li + 1 >= len(lines):
        return ""
    label_words = lines[li][start:end + 1]
    left = label_words[0]["x0"] - 20
    height = label_words[0]["y1"] - label_words[0]["y0"]
    if lines[li + 1][0]["y0"] - label_words[-1]["y1"] > 2 * height:
        return ""
    right_labels = [lines[li][s]["x0"] for (_, l, s, _) in labels if l == li and s > end]
    right = min(right_labels) if right_labels else 1e9
    labelled = {(l, i) for (_, l, s, e) in labels for i in range(s, e + 1)}
    words = [w for i, w in enumerate(lines[li + 1])
             if left <= w["x0"] < right and (li + 1, i) not in labelled]
    return " ".join(w["text"] for w in words).strip(" :_")


def parse_fields(words):
    # Table borders come out of OCR as '|' words: drop anything with no letters or digits
    words = [w for w in words if re.search(r"[A-Za-z0-9@#]", w["text"])]
    lines = group_lines(words)
    labels = find_labels(lines)
    fields = {}
    for field, li, start, end in labels:
        if field is None or field in fields:
            continue  # first occurrence wins: the primary investor comes before any joint owner
        value = value_after(lines, labels, field, li, start, end) or value_below(lines, labels, li, start, end)
        if field in PATTERNS and not re.match(PATTERNS[field], value):
            value = ""
        if value:
            fields[field] = value
        if field == "street" and "city" not in [lab[0] for lab in labels]:
            # Some forms give the address two blank lines and no 'City' label: the second line is the city
            fields["city"] = continuation(lines, li)
    return {k: v for k, v in fields.items() if v}


def continuation(lines, li):
    """The second line of an address box: the next line, if it holds no label at all."""
    if li + 1 >= len(lines):
        return ""
    nxt = lines[li + 1]
    if find_labels([nxt]) or nxt[0]["y0"] - lines[li][-1]["y1"] > 2 * (nxt[0]["y1"] - nxt[0]["y0"]):
        return ""
    return " ".join(w["text"] for w in nxt)


def read_subscription(path):
    return {"text_layer": parse_fields(text_layer_words(path)), "ocr": parse_fields(list(ocr_words(path)))}
