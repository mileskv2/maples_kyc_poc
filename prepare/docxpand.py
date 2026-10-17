"""Download a small slice of DocXPand-25k (synthetic ID documents on real photo backgrounds).

    python -m prepare.docxpand

The full dataset is ~18 GB in 12 parts. We stream the parts through tarfile and keep only
a capped number of passports and ID cards, so nothing large ever lands on disk. Images already
on disk count towards the caps, so the script can be stopped and rerun.
Licence: CC BY-NC-SA 4.0 (non-commercial, cite the paper). Images are NOT committed.
"""

import shutil
import subprocess
import tarfile
from pathlib import Path

from config import DOCXPAND

RELEASE = "https://github.com/QuickSign/docxpand/releases/download/v1.0.0/DocXPand-25k.tar.gz.{:02d}"
PASSPORTS = {"PP_TD3_A": 60, "PP_TD3_B": 60, "PP_TD3_C": 60}
ID_CARD = "ID_CARD_TD1_A"
ID_CARD_PAIRS = 60     # an ID card needs both sides: front (photo, name) and back (MRZ, address)
FRONT_POOL = 400       # fronts and backs arrive in random order, so hold more fronts than we need


def stream_parts():
    """One process whose stdout is all 12 parts glued together (a single .tar.gz stream)."""
    urls = " ".join(RELEASE.format(i) for i in range(12))
    return subprocess.Popen(f"for u in {urls}; do curl -sL $u; done", shell=True, stdout=subprocess.PIPE)


def parse_name(name):
    """'.../PP_TD3_A/uuid-PP_TD3_A-front.jpg' -> (uuid, 'PP_TD3_A', 'front')."""
    stem = Path(name).stem
    template, side = stem[37:].rsplit("-", 1)  # a uuid is 36 characters plus the dash
    return stem[:36], template, side


def on_disk(template):
    return sorted((DOCXPAND / "images" / template).glob("*.jpg"))


def save(tar, member, template):
    target = DOCXPAND / "images" / template / Path(member.name).name
    target.parent.mkdir(parents=True, exist_ok=True)
    with tar.extractfile(member) as src, open(target, "wb") as dst:
        shutil.copyfileobj(src, dst)


def main():
    counts = {t: len(on_disk(t)) for t in PASSPORTS}
    fronts = {p.name[:36] for p in on_disk(ID_CARD) if "-front" in p.name}
    backs = {p.name[:36] for p in on_disk(ID_CARD) if "-back" in p.name}

    def done():
        return all(counts[t] >= cap for t, cap in PASSPORTS.items()) and len(fronts & backs) >= ID_CARD_PAIRS

    proc = stream_parts()
    with tarfile.open(fileobj=proc.stdout, mode="r|gz") as tar:
        for member in tar:
            # Skip label files and the field crops (portraits, barcodes): we only want whole documents
            if done():
                break
            if not member.isfile() or "/fields/" in member.name or not member.name.endswith(".jpg"):
                continue
            uuid, template, side = parse_name(member.name)
            if template in PASSPORTS and counts[template] < PASSPORTS[template]:
                save(tar, member, template)
                counts[template] += 1
            elif template == ID_CARD and len(fronts & backs) < ID_CARD_PAIRS:
                if side == "front" and len(fronts) < FRONT_POOL:
                    save(tar, member, template)
                    fronts.add(uuid)
                elif side == "back" and uuid in fronts and uuid not in backs:
                    save(tar, member, template)
                    backs.add(uuid)
            else:
                continue
            print(f"passports {counts}  ID card pairs {len(fronts & backs)}", flush=True)
    proc.kill()

    # Keep only complete ID cards
    for p in on_disk(ID_CARD):
        if p.name[:36] not in fronts & backs:
            p.unlink()
    print(f"done: passports {counts}, ID card pairs {len(fronts & backs)}")


if __name__ == "__main__":
    main()
