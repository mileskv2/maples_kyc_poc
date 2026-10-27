"""Download real, blank subscription agreements from SEC EDGAR and keep the investor-information page.

You don't need to run this: the result is already committed in data/sec_forms/. It's kept to show
where the forms came from, and to add new forms later:

    SEC_CONTACT="you@example.com" python -m prepare.sec_forms

These are Reg A offering exhibits (form type EX1A-4): public US documents, filed blank.
SEC asks every automated request to carry a contact email, hence SEC_CONTACT.
We only keep blank forms. Never use executed agreements: those hold real investors' details.
"""

import os
import re
import time
import urllib.request

import pymupdf

from config import SEC_DOWNLOADS, SEC_FORMS

# name: (EDGAR path, pages holding the investor's details)
FORMS = {
    "commune_omni_fund": ("2046788/000110465925080221/tm2519245d2_ex4-1.htm", [14]),
    "cws_investments": ("1920508/000121390025103982/ea025989001ex4-1_cwsinvest.htm", [1]),
    "red_oak_capital_fund_vi": ("1957571/000165495423000072/redoakvi_ex4.htm", [7]),
    "rei_capital_growth": ("1905895/000168316824007051/rei_ex0401.htm", [6, 7]),
}

# Where to write each field on each form: the label printed next to the blank.
# A (label, n) pair means "the n-th line below that label" (e.g. second line of an address box).
# 'style' says where the blank is: on a drawn line ('line'), beside the label in a table row ('right'),
# or under the label in a tall table cell ('below').
FILL_SPOTS = {
    "commune_omni_fund": {
        "style": "line",
        "full_name": "Name:", "street": "Address:", "city": ("Address:", 1),
        "phone": "Phone:", "email": "Email:", "ssn": "Social Security Number:",
        "date_of_birth": "Date of Birth:",
    },
    "cws_investments": {
        "style": "below",
        "full_name": "Name of Investor/Authorized Person", "date_of_birth": "Date of Birth",
        "ssn": "Social Security Number", "citizenship": "Country of Citizenship",
        "street": "Street Address", "city": "City",
    },
    "red_oak_capital_fund_vi": {
        "style": "right",
        "full_name": "First, Middle, Last Name:", "ssn": "Social Security #:",
        "street": "Street Address:", "city": "City, State, Zip Code:", "phone": "Daytime Phone #:",
        "date_of_birth": "Date of Birth:", "citizenship": "Specify Country):",
        "email": "E-mail Address:",
    },
    "rei_capital_growth": {
        "style": "line",
        "full_name": "Name of Subscriber", "email": "Subscriber Email:",
        "citizenship": "Citizenship Country:", "street": "Address Line 1:",
        "city": "City:", "phone": "Mobile Phone Number:", "date_of_birth": "Subscriber Date of Birth:",
        "ssn": "Subscriber SSN/Tax ID:",
    },
}


def download(path):
    contact = os.environ.get("SEC_CONTACT")
    if not contact:
        raise SystemExit("Set SEC_CONTACT to your email (SEC fair-access policy).")
    request = urllib.request.Request(f"https://www.sec.gov/Archives/edgar/data/{path}",
                                     headers={"User-Agent": f"McGill MMA capstone research {contact}"})
    return urllib.request.urlopen(request).read().decode("latin-1")


def html_to_pdf(html, out_path):
    """Lay the HTML out on Letter pages, as the issuer's printed form would be."""
    html = re.sub(r"<img[^>]*>", "", html, flags=re.I)  # logos use relative links we don't have
    story = pymupdf.Story(html=html)
    writer = pymupdf.DocumentWriter(str(out_path))
    page = pymupdf.paper_rect("letter")
    more = True
    while more:
        device = writer.begin_page(page)
        more, _ = story.place(page + (54, 54, -54, -54))  # 0.75 inch margins
        story.draw(device)
        writer.end_page()
    writer.close()


def main():
    (SEC_DOWNLOADS / "raw").mkdir(parents=True, exist_ok=True)
    SEC_FORMS.mkdir(parents=True, exist_ok=True)
    for name, (path, pages) in FORMS.items():
        raw_html = SEC_DOWNLOADS / "raw" / f"{name}.htm"
        if not raw_html.exists():
            raw_html.write_text(download(path), encoding="latin-1")
            time.sleep(0.5)  # stay well under SEC's rate limit
        full_pdf = SEC_DOWNLOADS / "raw" / f"{name}.pdf"
        html_to_pdf(raw_html.read_text(encoding="latin-1"), full_pdf)

        blank = pymupdf.open()
        blank.insert_pdf(pymupdf.open(full_pdf), from_page=pages[0], to_page=pages[-1])
        blank.save(SEC_FORMS / f"{name}.pdf")
        print(f"{name}: kept page(s) {pages}")


if __name__ == "__main__":
    main()
