"""Score the pipeline against the answer key in data/demo/labels.json."""

from config import TODAY
from validate.checks import mrz_date, same, us_date


def id_truth(t):
    i = t["id"]
    return {f: i[f] for f in ("surname", "given_names", "date_of_birth", "nationality",
                              "document_number", "expiry_date")}


def subscription_truth(t):
    s = dict(t["subscription"])
    s["date_of_birth"] = us_date(s["date_of_birth"])
    return {k: v for k, v in s.items() if v}


def truth_for(t, document):
    return subscription_truth(t) if document == "subscription" else id_truth(t)


# What each planted issue should trigger: at least an amber on the right field (red where we can be sure)
def flagged(records, document, field):
    return any(r["document"] == document and r["field"] == field and r["light"] != "green" for r in records)


EXPECTED = {
    "dob_mismatch": lambda rs: flagged(rs, "subscription", "date_of_birth"),
    "name_mismatch": lambda rs: flagged(rs, "subscription", "full_name"),
    "address_mismatch": lambda rs: flagged(rs, "subscription", "street"),
    "missing_dob": lambda rs: any(r["field"] == "date_of_birth" and r["document"] == "subscription"
                                  and r["light"] == "red" for r in rs),
}


def id_red(records):
    """An expired ID must not pass: red on its expiry date, or red because it couldn't be read at all."""
    return any(r["document"] != "subscription" and r["light"] == "red" for r in records)


def is_expired(t):
    return t["id"]["expiry_date"] < TODAY.isoformat()


def method_accuracy(results):
    """Share of documents where each method alone read the field right, split by how the file arrived."""
    rows = []
    for r in results:
        t, raw = r["truth"], r["raw"]
        mrz = dict(raw["id"]["mrz"]) if raw.get("id") else {}
        if mrz:
            mrz["date_of_birth"] = mrz_date(mrz.get("date_of_birth"), False)
            mrz["expiry_date"] = mrz_date(mrz.get("expiry_date"), True)
        for field, expected in id_truth(t).items():
            rows.append({"document": t["id_kind"], "method": "mrz", "condition": "photo/scan",
                         "field": field, "correct": same(mrz.get(field), expected)})
            # The printed zone confirms the MRZ rather than reading on its own: count it right
            # when it found the correct value printed on the page
            printed = (raw.get("id") or {}).get("printed", {}).get(field) is not None
            rows.append({"document": t["id_kind"], "method": "printed zone", "condition": "photo/scan",
                         "field": field, "correct": printed and same(mrz.get(field), expected)})
        sub = raw.get("subscription") or {"text_layer": {}, "ocr": {}}
        for field, expected in subscription_truth(t).items():
            for method in ("text_layer", "ocr"):
                if method == "text_layer" and t["condition"] != "digital":
                    continue  # scans and photos have no text layer to read
                value = sub[method].get(field)
                value = us_date(value) if field == "date_of_birth" else value
                rows.append({"document": "subscription", "method": method, "condition": t["condition"],
                             "field": field, "correct": same(value, expected)})
    return rows


def evaluate(results):
    scored, greens = [], []
    for r in results:
        for rec in r["records"]:
            expected = truth_for(r["truth"], "subscription" if rec["document"] == "subscription" else "id").get(rec["field"])
            rec["correct"] = None if expected is None or rec["value"] is None else same(rec["value"], expected)
            if rec["correct"] is not None:
                scored.append(rec)
                if rec["light"] == "green":
                    greens.append(rec)

    files = [(f["predicted"], f["actual"]) for r in results for f in r["files"]]
    planted = [r for r in results if r["truth"]["scenario"] in EXPECTED]
    for r in planted:
        r["caught"] = EXPECTED[r["truth"]["scenario"]](r["records"])
    expired = [r for r in results if is_expired(r["truth"])]
    clean = [r for r in results if r["truth"]["scenario"] == "clean" and not is_expired(r["truth"])]
    wrong = [rec for rec in scored if not rec["correct"]]

    metrics = {
        "Investors processed": len(results),
        "Documents classified correctly": f"{sum(p == a for p, a in files)}/{len(files)}",
        "Field accuracy (final value)": f"{sum(x['correct'] for x in scored)}/{len(scored)}",
        "Green precision (green fields that are correct)": f"{sum(x['correct'] for x in greens)}/{len(greens)}",
        "Wrong values caught (amber/red, not green)": f"{sum(x['light'] != 'green' for x in wrong)}/{len(wrong)}",
        "Planted issues flagged": f"{sum(r['caught'] for r in planted)}/{len(planted)}",
        "Expired IDs flagged red": f"{sum(id_red(r['records']) for r in expired)}/{len(expired)}",
        "Clean files with no red flag": f"{sum(r['status'] != 'red' for r in clean)}/{len(clean)}",
        "Clean files fully green": f"{sum(r['status'] == 'green' for r in clean)}/{len(clean)}",
    }
    return metrics, method_accuracy(results)
