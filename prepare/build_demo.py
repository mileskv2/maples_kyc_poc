"""Build the demo set: one folder per investor holding an ID document and a filled subscription agreement.

    python -m prepare.build_demo              # 40 investors into data/demo/ (committed)
    python -m prepare.build_demo --samples    # copy a few of them into samples/ (committed)

Each investor is a DocXPand person (fictional ID on a real photo background). We fill one of the
real SEC subscription forms with that same person's details, plant a few issues, then make the
pages look scanned or photographed. Files get neutral names, so the pipeline must work out
which document is which.

Samples: DocXPand pastes each fake document onto a photo of a real ID. For the committed samples we
crop every ID image to the fake document's own corners, so none of the real background remains.
"""

import json
import random
import shutil
import sys
import unicodedata
from datetime import datetime

import numpy as np
import pymupdf
from augraphy import (Brightness, Geometric, InkBleed, Jpeg, LightingGradient, NoiseTexturize,
                      ShadowCast, SubtleNoise)
from faker import Faker
from PIL import Image

from config import DEMO, DOCXPAND, N_INVESTORS, SAMPLES, SEC_FORMS, SEED, TODAY
from prepare.sec_forms import FILL_SPOTS

ID_TEMPLATES = {"PP_TD3_A": "passport", "PP_TD3_B": "passport", "PP_TD3_C": "passport",
                "ID_CARD_TD1_A": "id_card"}

# What can go wrong with a file (beyond what DocXPand already gives us, e.g. expired IDs)
SCENARIOS = ["clean"] * 5 + ["dob_mismatch", "name_mismatch", "address_mismatch", "missing_dob"]
CONDITIONS = ["digital", "scanned", "photo"]  # how the subscription agreement reached us

fake = Faker("en_US")


# ---------- Ground truth from DocXPand labels ----------

def iso_date(dotted):
    """DocXPand prints dates as DD.MM.YYYY."""
    return datetime.strptime(dotted, "%d.%m.%Y").date().isoformat()


def as_list(value):
    return value if isinstance(value, list) else [v.strip() for v in value.split(",")]


def id_truth(front, back, kind):
    """The KYC fields of one ID document, in our own field names."""
    def value(fields, key):
        v = fields[key]["value"] if key in fields else None  # labels also hold positions we don't use
        return " ".join(v) if isinstance(v, list) and key != "address" and key != "mrz" else v

    given = " ".join(as_list(value(front, "given_name")))
    if kind == "passport":
        address, mrz = value(front, "address"), value(front, "mrz")
        # Two of the three passport designs print no address (like many real passports)
        street, city = (address[0], address[-1]) if address else (fake.street_address(), fake.city())
    else:  # ID card: address and MRZ are on the back, address lines run city-first
        address, mrz = value(back, "address"), value(back, "mrz")
        street, city = address[-1], address[0]
    return {
        "surname": value(front, "family_name"), "given_names": given,
        "date_of_birth": iso_date(value(front, "birth_date")), "nationality": value(front, "nationality"),
        "document_number": value(front, "document_number"), "expiry_date": iso_date(value(front, "expires")),
        "street": street.strip(), "city": city.strip(), "address_on_id": bool(address), "mrz": mrz,
    }


def load_people():
    """Pair every downloaded image with its labels. ID cards need both sides."""
    labels = json.loads((DOCXPAND / "labels.json").read_text())["documents"]
    on_disk = {p.name for p in (DOCXPAND / "images").rglob("*.jpg")}
    sides = {}
    for doc in labels:
        name = doc["filename"].split("/")[-1]
        if name not in on_disk:
            continue
        uuid, template = name[:36], name[37:-4].rsplit("-", 1)[0]
        if template in ID_TEMPLATES:
            ann = doc["annotations"][0]
            side = ann["template"].rsplit("-", 1)[1]
            sides.setdefault((uuid, template), {})[side] = (doc["filename"], ann["fields"][side])

    people = []
    for (uuid, template), s in sorted(sides.items()):
        kind = ID_TEMPLATES[template]
        if "front" not in s or (kind == "id_card" and "back" not in s):
            continue
        back = s.get("back", (None, None))
        people.append({"uuid": uuid, "template": template, "kind": kind,
                       "images": [s["front"][0]] + ([back[0]] if back[0] else []),
                       "truth": id_truth(s["front"][1], back[1], kind)})
    return people


# ---------- Filling a real SEC form ----------

def plain(text):
    """US forms are filled in plain ASCII (and Helvetica has no glyph for some accents)."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def subscription_values(person, scenario):
    t = person["truth"]
    dob = datetime.fromisoformat(t["date_of_birth"]).strftime("%m/%d/%Y")  # US forms: MM/DD/YYYY
    values = {
        "full_name": f"{t['given_names']} {t['surname']}", "date_of_birth": dob,
        "citizenship": t["nationality"], "street": t["street"], "city": t["city"],
        "ssn": f"9{random.randint(10, 99)}-{random.randint(10, 99)}-{random.randint(1000, 9999)}",
        "phone": fake.numerify("(###) ###-####"),
        "email": plain(f"{t['given_names'].split()[0]}.{t['surname']}@example.com").lower(),
    }
    # Planted issues: what the investor wrote differs from their ID
    if scenario == "dob_mismatch":
        values["date_of_birth"] = dob[:-4] + str(int(dob[-4:]) + random.choice([-2, -1, 1, 2]))
    elif scenario == "name_mismatch":
        values["full_name"] = f"{t['given_names'].split()[0]} {fake.last_name()}"
    elif scenario == "address_mismatch":
        values["street"] = fake.street_address()
    elif scenario == "missing_dob":
        values["date_of_birth"] = ""
    return {k: plain(v) for k, v in values.items()}


def find_label(doc, label):
    """First place the label is printed, top to bottom (the primary investor comes before the joint owner)."""
    for page in doc:
        hits = sorted(page.search_for(label), key=lambda r: (round(r.y0), r.x0))
        if hits:
            return page, hits[0]
    raise ValueError(f"label not found: {label}")


def underlines_after(page, label):
    """Blank lines drawn to the right of a label, from its own row downwards."""
    lines = [d["rect"] for d in page.get_drawings() if d["rect"].height < 2 and d["rect"].width > 60]
    return sorted((r for r in lines if r.x0 > label.x1 - 5 and r.y0 > label.y1 - 6), key=lambda r: r.y0)


def fill_form(form, values, out_path):
    doc = pymupdf.open(SEC_FORMS / f"{form}.pdf")
    spots = dict(FILL_SPOTS[form])
    style = spots.pop("style")
    for field, spot in spots.items():
        if not values.get(field):
            continue
        label, nth = spot if isinstance(spot, tuple) else (spot, 0)
        page, rect = find_label(doc, label)
        if style == "line":
            blank = underlines_after(page, rect)[nth]
            where = (blank.x0 + 4, blank.y0 - 3)     # on the drawn line
        elif style == "below":
            where = (rect.x0 + 2, rect.y1 + 12)       # tall table cell: under the label
        else:
            where = (rect.x1 + 6, rect.y1 - 3)        # table row: after the label
        page.insert_text(where, values[field], fontsize=10, fontname="helv", color=(0.05, 0.1, 0.4))
    doc.save(out_path)


# ---------- Making documents look like they came from the real world ----------

def page_images(pdf_path, dpi=200):
    doc = pymupdf.open(pdf_path)
    for page in doc:
        pix = page.get_pixmap(dpi=dpi)
        yield np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3)


def degrade(img, condition):
    """Scanner: grey noise, streaks, slight skew. Phone photo: uneven light, shadow, stronger tilt."""
    if condition == "scanned":
        steps = [Geometric(rotate_range=(-1, 1)), InkBleed(intensity_range=(0.3, 0.5)),
                 NoiseTexturize(sigma_range=(2, 4)), SubtleNoise(),
                 Jpeg(quality_range=(50, 80))]
    else:
        steps = [Geometric(rotate_range=(-3, 3)), LightingGradient(min_brightness=60, max_brightness=255),
                 ShadowCast(shadow_opacity_range=(0.2, 0.4)), NoiseTexturize(sigma_range=(2, 5)),
                 Brightness(brightness_range=(0.85, 1.05)), Jpeg(quality_range=(40, 75))]
    for step in steps:
        img = step(img)
    return img


def save_subscription(filled_pdf, condition, folder, first_number):
    """Digital stays a PDF with a text layer; scans become image-only PDFs; photos are one JPG per page.
    Returns the file names written."""
    if condition == "digital":
        name = f"upload_{first_number}.pdf"
        shutil.copy(filled_pdf, folder / name)
        return [name]
    pages = [Image.fromarray(degrade(img, condition)).convert("RGB") for img in page_images(filled_pdf)]
    if condition == "photo":
        names = [f"upload_{first_number + i}.jpg" for i in range(len(pages))]
        for page, name in zip(pages, names):
            page.save(folder / name, quality=85)
        return names
    name = f"upload_{first_number}.pdf"
    pages[0].save(folder / name, save_all=True, append_images=pages[1:], resolution=200)
    return [name]


# ---------- Build ----------

def main():
    random.seed(SEED)
    Faker.seed(SEED)
    people = load_people()
    random.shuffle(people)
    # Keep the demo mostly current IDs, with a few expired ones as natural red flags
    current = [p for p in people if p["truth"]["expiry_date"] >= TODAY.isoformat()]
    expired = [p for p in people if p["truth"]["expiry_date"] < TODAY.isoformat()]
    chosen = current[:N_INVESTORS - 4] + expired[:4]
    random.shuffle(chosen)

    if DEMO.exists():
        shutil.rmtree(DEMO)
    forms = sorted(FILL_SPOTS)
    labels = []
    for i, person in enumerate(chosen, start=1):
        investor_id = f"INV-{i:03d}"
        folder = DEMO / investor_id
        folder.mkdir(parents=True)
        scenario = random.choice(SCENARIOS)
        form = forms[i % len(forms)]
        condition = random.choice(CONDITIONS)

        # Neutral file names: the classifier has to tell the documents apart
        files, sources = {}, {}
        for n, src in enumerate(person["images"], start=1):
            name = f"upload_{n}.jpg"
            shutil.copy(DOCXPAND / "images" / src, folder / name)
            files[name] = person["kind"]
            sources[name] = src
        values = subscription_values(person, scenario)
        fill_form(form, values, folder / "filled.pdf")
        for name in save_subscription(folder / "filled.pdf", condition, folder, len(files) + 1):
            files[name] = "subscription"
        (folder / "filled.pdf").unlink()

        labels.append({"investor_id": investor_id, "scenario": scenario, "id_kind": person["kind"],
                       "id_template": person["template"], "form": form, "condition": condition,
                       "files": files, "id_sources": sources, "id": person["truth"], "subscription": values})
        print(f"{investor_id}  {person['kind']:8}  {form:24}  {condition:8}  {scenario}")

    (DEMO / "labels.json").write_text(json.dumps(labels, indent=2, ensure_ascii=False))


# ---------- Committed samples ----------

# One per passport design plus ID cards; a mix of clean files and planted issues
SAMPLE_COUNT = {"PP_TD3_A": 1, "PP_TD3_B": 1, "PP_TD3_C": 1, "ID_CARD_TD1_A": 3}


def crop_to_document(src, corners, margin=0.01):
    """Keep only the fake document: its corners come with the DocXPand labels."""
    img = Image.open(DOCXPAND / "images" / src)
    xs = [float(c["x"]) for c in corners.values()]
    ys = [float(c["y"]) for c in corners.values()]
    box = (max(min(xs) - margin, 0) * img.width, max(min(ys) - margin, 0) * img.height,
           min(max(xs) + margin, 1) * img.width, min(max(ys) + margin, 1) * img.height)
    return img.crop(tuple(int(v) for v in box))


def make_samples():
    labels = json.loads((DEMO / "labels.json").read_text())
    corners = {d["filename"]: d["annotations"][0]["position"]
               for d in json.loads((DOCXPAND / "labels.json").read_text())["documents"]}
    if SAMPLES.exists():
        shutil.rmtree(SAMPLES)
    picked, seen_scenarios = [], set()
    for template, count in SAMPLE_COUNT.items():
        candidates = [l for l in labels if l["id_template"] == template]
        for _ in range(count):
            # Prefer a scenario we haven't shown yet, so the samples cover different flags
            fresh = [l for l in candidates if l["scenario"] not in seen_scenarios]
            choice = (fresh or candidates)[0]
            candidates.remove(choice)
            picked.append(choice)
            seen_scenarios.add(choice["scenario"])

    for l in picked:
        folder = SAMPLES / l["investor_id"]
        shutil.copytree(DEMO / l["investor_id"], folder)
        for name, src in l["id_sources"].items():
            crop_to_document(src, corners[src]).save(folder / name, quality=90)
        print(f"{l['investor_id']}  {l['id_template']:14} {l['condition']:8} {l['scenario']}")
    (SAMPLES / "labels.json").write_text(json.dumps(picked, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    make_samples() if "--samples" in sys.argv else main()
