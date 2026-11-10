"""Generate clearly-labelled FICTITIOUS sample KYC documents for the demo.

The document content (Chinese / Arabic text) lives in samples/templates/*.html.
Each template starts with a comment `<!-- dir=ltr -->` or `<!-- dir=rtl -->`.
Run:  python tools/make_samples.py   (requires playwright + chromium)
"""
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "samples"
TEMPLATES = OUT / "templates"
BASE = """<html><head><meta charset="utf-8"><style>
body{margin:0;background:#fff;font-family:'Noto Sans CJK SC','Noto Serif CJK SC','DejaVu Sans',sans-serif}
.page{width:900px;padding:48px 56px;position:relative;box-sizing:border-box;color:#222}
.wm{position:absolute;top:40%;left:-5%;width:110%;text-align:center;transform:rotate(-25deg);
    font-size:64px;font-weight:700;color:rgba(200,0,0,.16);letter-spacing:4px;pointer-events:none}
.foot{margin-top:28px;font-size:13px;color:#b00;border-top:1px dashed #b00;padding-top:8px}
table{border-collapse:collapse;width:100%} td,th{border:1px solid #999;padding:8px 10px;font-size:17px;text-align:start}
th{background:#f2f2f2} h1{text-align:center;margin:6px 0 4px} .sub{text-align:center;color:#555;margin-bottom:20px}
.kv td:first-child{width:30%;background:#fafafa;font-weight:600}
</style></head><body><div class="page" dir="%DIR%">%BODY%<div class="wm">SAMPLE · FICTITIOUS · DEMO ONLY</div>
<div class="foot" dir="ltr">SAMPLE DOCUMENT – fictitious data created for a McGill capstone demo. Not a real document.</div>
</div></body></html>"""


def load_templates():
    for path in sorted(TEMPLATES.glob("*.html")):
        text = path.read_text(encoding="utf-8")
        m = re.match(r"<!--\s*dir=(ltr|rtl)\s*-->\s*", text)
        direction = m.group(1) if m else "ltr"
        body = text[m.end():] if m else text
        yield path.stem + ".png", direction, body


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 900, "height": 600}, device_scale_factor=1.5)
    for name, direction, body in load_templates():
        page.set_content(BASE.replace("%DIR%", direction).replace("%BODY%", body))
        page.locator(".page").screenshot(path=str(OUT / name))
        print("wrote", name)
    browser.close()
