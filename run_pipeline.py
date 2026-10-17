"""Run the pipeline on every investor folder and write the analyst tracker.

    python run_pipeline.py            # all investors in data/demo
    python run_pipeline.py 10         # only the first 10 (quick check)

Each folder holds an investor's uploads with neutral names. The pipeline classifies each file,
reads the ID and the subscription agreement two ways each, cross-checks them, and scores it all.
"""

import json
import sys

from classify import classify
from config import DEMO, OUTPUT, TODAY
from evaluate import evaluate
from extract.id_document import read_id_document
from extract.subscription import read_subscription
from report import write_tracker
from validate.checks import check_id, check_subscription, cross_check

CONTACT_FIELDS = ["ssn", "email", "phone"]


def process_investor(folder, truth):
    files = []
    for path in sorted(p for p in folder.iterdir() if p.is_file()):
        kind, reason = classify(path)
        files.append({"name": path.name, "path": path, "predicted": kind, "reason": reason,
                      "actual": truth["files"].get(path.name)})

    id_files = [f for f in files if f["predicted"] in ("passport", "id_card")]
    subscription_files = [f for f in files if f["predicted"] == "subscription"]
    raw, records = {}, []

    if id_files:
        kind = id_files[0]["predicted"]
        raw["id"] = read_id_document([f["path"] for f in id_files])
        id_records = check_id(raw["id"], kind)
    else:
        id_records = [{"document": "id", "field": "document", "value": None, "light": "red",
                       "sources": [], "note": "no passport or ID card found in the upload"}]
    if subscription_files:
        # A multi-page form photographed page by page arrives as several files: merge what each holds
        raw["subscription"] = {"text_layer": {}, "ocr": {}}
        for f in subscription_files:
            for method, fields in read_subscription(f["path"]).items():
                for field, value in fields.items():
                    raw["subscription"][method].setdefault(field, value)
        sub_records = check_subscription(raw["subscription"])
    else:
        sub_records = [{"document": "subscription", "field": "document", "value": None, "light": "red",
                        "sources": [], "note": "no subscription agreement found in the upload"}]
    if id_files and subscription_files:
        cross_check(id_records, raw["id"], sub_records)

    records = id_records + sub_records
    for r in records:
        r["investor_id"] = truth["investor_id"]
    for f in files:
        del f["path"]  # keep results printable
    return files, records, raw


def case_status(records):
    """Worst light across the identity fields. Contact details (SSN, phone, email) are shown but
    don't drive the status: a scan only ever gives one reading of them, and they aren't KYC identity."""
    lights = {r["light"] for r in records if r["field"] not in CONTACT_FIELDS}
    return "red" if "red" in lights else "amber" if "amber" in lights else "green"


def main(limit=None):
    labels = json.loads((DEMO / "labels.json").read_text())[:limit]

    results = []
    for truth in labels:
        files, records, raw = process_investor(DEMO / truth["investor_id"], truth)
        results.append({"truth": truth, "files": files, "records": records, "raw": raw,
                        "status": case_status(records)})
        print(f"{truth['investor_id']}  {results[-1]['status']:5}  {truth['id_kind']:8} "
              f"{truth['condition']:8} {truth['scenario']}")

    metrics, method_rows = evaluate(results)
    expired = {r["truth"]["investor_id"] for r in results if r["truth"]["id"]["expiry_date"] < TODAY.isoformat()}
    OUTPUT.mkdir(exist_ok=True)
    write_tracker(results, metrics, method_rows, OUTPUT / "kyc_tracker.xlsx", expired)
    print()
    for k, v in metrics.items():
        print(f"{k:52} {v}")
    return results, metrics, method_rows


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else None)
