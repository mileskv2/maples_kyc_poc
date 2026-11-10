"""Turn a list of processed documents into a formatted Excel workbook (bytes)."""
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FONT = Font(bold=True, color="FFFFFF")
REVIEW_FILL = PatternFill("solid", fgColor="FCE4D6")
OK_FILL = PatternFill("solid", fgColor="E2EFDA")
WRAP = Alignment(wrap_text=True, vertical="top")

SUMMARY_COLS = [
    ("Source File", "source_file", 22),
    ("Document Type", "doc_type", 22),
    ("Language", "source_language", 16),
    ("Name (Original)", "subject_name_original", 26),
    ("Name (English)", "subject_name_english", 26),
    ("Name Variants", "name_variants", 26),
    ("Document No.", "document_number", 20),
    ("Date of Birth", "date_of_birth", 13),
    ("Issue Date", "issue_date", 13),
    ("Expiry Date", "expiry_date", 13),
    ("Expired?", "is_expired", 10),
    ("Nationality / Jurisdiction", "nationality_or_jurisdiction", 20),
    ("Address (English)", "address_english", 36),
    ("Issuing Authority", "issuing_authority_english", 26),
    ("Calendar Notes", "calendar_notes", 28),
    ("MRZ Check", "mrz_status", 11),
    ("MRZ Lines", "mrz_lines", 48),
    ("Overall Confidence", "overall_confidence", 12),
    ("Needs Human Review", "needs_human_review", 12),
    ("Rule Flags", "rule_flags", 36),
    ("LLM Review Flags", "review_flags", 36),
]


def _fmt(v):
    if isinstance(v, list):
        return "; ".join(str(x) for x in v)
    if isinstance(v, bool):
        return "YES" if v else "NO"
    return v


def _header(ws, headers_widths):
    for i, (h, w) in enumerate(headers_widths, 1):
        c = ws.cell(row=1, column=i, value=h)
        c.fill, c.font, c.alignment = HEADER_FILL, HEADER_FONT, WRAP
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"


def to_excel(results: list[dict]) -> bytes:
    wb = Workbook()

    # Sheet 1: one row per document
    ws = wb.active
    ws.title = "Summary"
    _header(ws, [(h, w) for h, _, w in SUMMARY_COLS])
    for r, doc in enumerate(results, 2):
        for c, (_, key, _) in enumerate(SUMMARY_COLS, 1):
            cell = ws.cell(row=r, column=c, value=_fmt(doc.get(key, "")))
            cell.alignment = WRAP
        mrz_col = [k for _, k, _ in SUMMARY_COLS].index("mrz_status") + 1
        if doc.get("mrz_status") in ("PASS", "FAIL"):
            ws.cell(row=r, column=mrz_col).fill = OK_FILL if doc["mrz_status"] == "PASS" else REVIEW_FILL
        fill = REVIEW_FILL if doc.get("needs_human_review") else OK_FILL
        ws.cell(row=r, column=len(SUMMARY_COLS)).fill = fill
        ws.cell(row=r, column=SUMMARY_COLS.index(("Needs Human Review", "needs_human_review", 12)) + 1).fill = fill
    ws.auto_filter.ref = ws.dimensions

    # Sheet 2: every extracted field (long format)
    ws2 = wb.create_sheet("All Fields")
    _header(ws2, [("Source File", 22), ("Field", 26), ("Original Value", 36),
                  ("English Value", 36), ("Confidence", 12)])
    r = 2
    for doc in results:
        for f in doc.get("fields", []):
            vals = [doc.get("source_file"), f.get("name"), f.get("value_original"),
                    f.get("value_english"), f.get("confidence")]
            for c, v in enumerate(vals, 1):
                ws2.cell(row=r, column=c, value=v).alignment = WRAP
            if (f.get("confidence") or 0) < 0.8:
                ws2.cell(row=r, column=5).fill = REVIEW_FILL
            r += 1
    ws2.auto_filter.ref = ws2.dimensions

    # Sheet 3: full translations
    ws3 = wb.create_sheet("Translations")
    _header(ws3, [("Source File", 22), ("Language", 16), ("Full English Translation", 110)])
    for r, doc in enumerate(results, 2):
        for c, v in enumerate([doc.get("source_file"), doc.get("source_language"),
                               doc.get("full_translation_english")], 1):
            ws3.cell(row=r, column=c, value=v).alignment = WRAP

    # Sheet 4: run info / disclaimer
    ws4 = wb.create_sheet("About")
    ws4["A1"] = "AI-assisted KYC extraction – proof of concept (demo data only)"
    ws4["A1"].font = Font(bold=True, size=13)
    ws4["A3"] = "Model"; ws4["B3"] = results[0].get("model", "") if results else ""
    ws4["A4"] = "Documents processed"; ws4["B4"] = len(results)
    ws4["A5"] = "Flagged for review"; ws4["B5"] = sum(bool(d.get("needs_human_review")) for d in results)
    ws4["A7"] = ("Machine translation supports analyst review only; it does not replace a certified/notarised "
                 "translation where one is required (see CIMA Guidance Notes on ML/TF/PF, Aug 2023, para 18 "
                 "on documents in unfamiliar languages).")
    ws4.column_dimensions["A"].width = 24
    ws4.column_dimensions["B"].width = 40

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
