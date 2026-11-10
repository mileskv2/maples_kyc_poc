"""Streamlit demo: upload Chinese / Arabic KYC documents -> English translation + structured fields -> Excel.
Run:  streamlit run app.py
"""
import json
import os
import time
from pathlib import Path

import pandas as pd
import streamlit as st

from excel_export import to_excel
from extractor import DEFAULT_MODEL, process_file

CACHE = Path("results/results.json")   # last successful run, used as offline backup for the live demo

st.set_page_config(page_title="KYC Document Translator", page_icon="📄", layout="wide")
st.title("📄 AI KYC Document Translator & Extractor")
st.caption("Chinese / Arabic → English · structured KYC fields · Excel export  —  proof of concept, demo data only")

with st.sidebar:
    st.header("Settings")
    api_key = st.text_input("Gemini API key", value=os.getenv("GEMINI_API_KEY", ""), type="password")
    model = st.text_input("Model", value=DEFAULT_MODEL)
    st.divider()
    st.markdown("**Backup for live demo**")
    if st.button("Load last saved results", disabled=not CACHE.exists()):
        st.session_state["results"] = json.loads(CACHE.read_text(encoding="utf-8"))
        saved = CACHE.parent / "files"
        st.session_state["files"] = {f.name: (f.read_bytes(), "image/" + f.suffix.lstrip(".").replace("jpg", "jpeg"))
                                     for f in saved.glob("*") if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")}
    st.caption("Every successful run is saved to results/results.json so the demo still works if the network or API fails.")

uploads = st.file_uploader("Upload documents (PNG, JPG, PDF)", type=["png", "jpg", "jpeg", "webp", "pdf"],
                           accept_multiple_files=True)

if st.button("🚀 Translate & extract", type="primary", disabled=not uploads):
    results, files = [], {}
    progress = st.progress(0.0)
    for i, up in enumerate(uploads):
        data = up.getvalue()
        files[up.name] = (data, up.type)
        with st.spinner(f"Reading {up.name} ..."):
            t0 = time.time()
            try:
                doc = process_file(data, up.name, api_key=api_key or None, model=model)
                doc["seconds"] = round(time.time() - t0, 1)
                results.append(doc)
            except Exception as e:
                st.error(f"{up.name}: {e}")
        progress.progress((i + 1) / len(uploads))
    if results:
        CACHE.parent.mkdir(exist_ok=True)
        CACHE.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        (CACHE.parent / "files").mkdir(exist_ok=True)
        for name, (data, _) in files.items():
            (CACHE.parent / "files" / name).write_bytes(data)
    st.session_state["results"], st.session_state["files"] = results, files

results = st.session_state.get("results", [])
files = st.session_state.get("files", {})

if results:
    n_review = sum(bool(d.get("needs_human_review")) for d in results)
    c1, c2, c3 = st.columns(3)
    c1.metric("Documents processed", len(results))
    c2.metric("Auto-cleared", len(results) - n_review)
    c3.metric("Flagged for analyst review", n_review)

    st.download_button("⬇️ Download Excel", data=to_excel(results), file_name="kyc_extraction.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       type="primary")

    for doc in results:
        badge = "🟠 Needs review" if doc.get("needs_human_review") else "🟢 OK"
        title = f"{badge} · {doc.get('source_file')} · {doc.get('doc_type')} · {doc.get('source_language')}"
        with st.expander(title, expanded=True):
            left, right = st.columns([1, 1.4])
            with left:
                data, mtype = files.get(doc.get("source_file"), (None, None))
                if data and mtype and mtype.startswith("image"):
                    st.image(data, use_container_width=True)
                elif data:
                    st.info("PDF uploaded (preview not shown)")
                else:
                    st.caption("(loaded from saved results)")
            with right:
                st.markdown(f"**Name:** {doc.get('subject_name_original')} → **{doc.get('subject_name_english')}**")
                if doc.get("name_variants"):
                    st.caption("Name variants for screening: " + ", ".join(doc["name_variants"]))
                key_rows = {
                    "Document No.": doc.get("document_number"),
                    "Date of birth": doc.get("date_of_birth"),
                    "Issue date": doc.get("issue_date"),
                    "Expiry date": doc.get("expiry_date"),
                    "Expired?": "YES" if doc.get("is_expired") else "NO",
                    "Nationality / Jurisdiction": doc.get("nationality_or_jurisdiction"),
                    "Address": doc.get("address_english"),
                    "Issuing authority": doc.get("issuing_authority_english"),
                    "Overall confidence": doc.get("overall_confidence"),
                }
                st.table(pd.DataFrame({"Value": {k: str(v) for k, v in key_rows.items() if v not in ("", None)}}))
                if doc.get("calendar_notes"):
                    st.info("📅 " + doc["calendar_notes"])
                mrz = doc.get("mrz_result")
                if mrz and mrz.get("format") != "unrecognised":
                    ok = doc.get("mrz_status") == "PASS"
                    st.markdown(f"**MRZ check ({mrz.get('format')}):** {'✅ PASS' if ok else '❌ FAIL'}")
                    st.code("\n".join(doc.get("mrz_lines", [])), language=None)
                    st.caption("ICAO 9303 check digits: " + ", ".join(
                        f"{k} {'✓' if v else '✗'}" for k, v in mrz.get("checks", {}).items())
                        + " · cross-checked against printed page")
                for f in doc.get("rule_flags", []):
                    st.warning("Rule check: " + f)
                for f in doc.get("review_flags", []):
                    st.warning("AI flag: " + f)
            if doc.get("fields"):
                st.markdown("**All extracted fields**")
                st.dataframe(pd.DataFrame(doc["fields"]), use_container_width=True, hide_index=True)
            with st.popover("Full English translation"):
                st.write(doc.get("full_translation_english", ""))
else:
    st.info("Upload one or more documents and click **Translate & extract**.")

st.divider()
st.caption("Machine translation assists analyst review and does not replace a certified/notarised translation "
           "where one is required. Risk decisions remain with the analyst.")
