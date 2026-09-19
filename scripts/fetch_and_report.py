#!/usr/bin/env python
"""
Weekly Stafford Borough Council planning application checker.

Downloads the latest "Planning Weekly List" PDF(s) from staffordbc.gov.uk,
extracts each application, flags any that mention keywords of interest
(HMOs, migrants/asylum seekers, Serco), writes a running history to
data/applications.json, regenerates docs/index.html, and emails a summary
when a new week has been processed.
"""
import json
import os
import re
import smtplib
import sys
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

import pdfplumber
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "applications.json"
STATE_FILE = ROOT / "data" / "state.json"
HTML_FILE = ROOT / "docs" / "index.html"
INDEX_URL = "https://www.staffordbc.gov.uk/planning-weekly-list"
PUBLIC_ACCESS_URL = "https://www12.staffordbc.gov.uk/online-applications/search.do?action=simple"

# Column left-edges (in PDF points) for: Heading, Application Information,
# Applicant/Agent, Proposal and Location, Type of Application.
# Derived from the header row of the weekly list PDF; re-detected per page
# where possible, with this as a fallback.
DEFAULT_COL_BOUNDS = [86.4, 134.4, 242.4, 341.4, 449.4]

REF_RE = re.compile(r"\b\d{2}/\d{5}/[A-Z0-9]+\b")

KEYWORDS = {
    "HMO": [
        "hmo",
        "house in multiple occupation",
        "houses in multiple occupation",
        "house of multiple occupation",
    ],
    "Migrants / asylum seekers": [
        "asylum",
        "migrant",
        "refugee",
        "resettlement",
        "dispersal accommodation",
    ],
    "Serco": [
        "serco",
    ],
}


def log(*args):
    print(*args, file=sys.stderr)


def col_bounds_for_page(page):
    words = page.extract_words()
    try:
        heading = next(w for w in words if w["text"] == "Heading")
        appinfo = next(w for w in words if w["text"] == "Application")
        applicant = next(w for w in words if w["text"] == "Applicant")
        proposal = next(w for w in words if w["text"] == "Proposal")
        type_ = next(w for w in words if w["text"] == "Type")
        return [heading["x0"], appinfo["x0"], applicant["x0"], proposal["x0"], type_["x0"]]
    except StopIteration:
        return DEFAULT_COL_BOUNDS


def col_index(x0, bounds):
    idx = 0
    for i, b in enumerate(bounds):
        if x0 >= b - 3:
            idx = i
    return idx


def parse_pdf(pdf_bytes, week_label, source_url):
    """Split a weekly-list PDF into individual application records."""
    records = []
    import io

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            bounds = col_bounds_for_page(page)
            words = page.extract_words()
            for w in words:
                w["col"] = col_index(w["x0"], bounds)

            starts = sorted(w["top"] for w in words if w["col"] == 0 and w["text"] == "APP")
            if not starts:
                continue
            boundaries = starts + [page.height]

            for i in range(len(starts)):
                top, bottom = boundaries[i], boundaries[i + 1]
                rec_words = [w for w in words if top - 0.5 <= w["top"] < bottom - 0.5]
                full_text = " ".join(
                    w["text"] for w in sorted(rec_words, key=lambda w: (round(w["top"]), w["x0"]))
                )
                proposal_words = [w for w in rec_words if w["col"] == 3]
                proposal_text = " ".join(
                    w["text"]
                    for w in sorted(proposal_words, key=lambda w: (round(w["top"]), w["x0"]))
                )
                type_words = [w for w in rec_words if w["col"] == 4]
                type_text = " ".join(
                    w["text"] for w in sorted(type_words, key=lambda w: (round(w["top"]), w["x0"]))
                )

                m = REF_RE.search(full_text)
                if not m:
                    continue
                ref = m.group(0)

                matched = []
                lower_text = full_text.lower()
                for category, terms in KEYWORDS.items():
                    if any(term in lower_text for term in terms):
                        matched.append(category)

                records.append(
                    {
                        "ref": ref,
                        "week": week_label,
                        "source_pdf": source_url,
                        "proposal": clean_text(proposal_text),
                        "type": clean_text(type_text),
                        "flags": matched,
                    }
                )
    return records


def clean_text(text):
    return re.sub(r"\s+", " ", text).strip()


def fetch_weekly_links():
    """Return list of (label, url) for weekly list PDFs, newest first."""
    resp = requests.get(INDEX_URL, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "planning-weekly-list-" in href:
            label = href.rstrip("/").rsplit("/", 1)[-1].replace("planning-weekly-list-", "")
            full_url = href if href.startswith("http") else f"https://www.staffordbc.gov.uk/{href.lstrip('/')}"
            links.append((label, full_url))
    # de-dupe, preserve order
    seen = set()
    unique = []
    for label, url in links:
        if label not in seen:
            seen.add(label)
            unique.append((label, url))
    return unique


def load_json(path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def week_sort_key(label):
    try:
        return datetime.strptime(label.title(), "%d-%B-%Y")
    except ValueError:
        return datetime.min


def generate_html(all_records):
    weeks = {}
    for rec in all_records:
        weeks.setdefault(rec["week"], []).append(rec)
    week_labels = sorted(weeks.keys(), key=week_sort_key, reverse=True)

    def esc(s):
        return (
            (s or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    sections = []
    for label in week_labels:
        recs = weeks[label]
        flagged = [r for r in recs if r["flags"]]
        rows = []
        for r in sorted(recs, key=lambda r: (not r["flags"], r["ref"])):
            flag_html = (
                f'<span class="flag">{esc(", ".join(r["flags"]))}</span>' if r["flags"] else ""
            )
            row_class = "flagged" if r["flags"] else ""
            rows.append(
                f"""<tr class="{row_class}">
  <td>{esc(r['ref'])}</td>
  <td>{esc(r['proposal'])}</td>
  <td>{esc(r['type'])}</td>
  <td>{flag_html}</td>
</tr>"""
            )
        sections.append(
            f"""<section>
  <h2>{esc(label.replace('-', ' ').title())}</h2>
  <p class="meta">{len(recs)} application(s), {len(flagged)} flagged.</p>
  <table>
    <thead><tr><th>Reference</th><th>Proposal &amp; location</th><th>Type</th><th>Flags</th></tr></thead>
    <tbody>
    {''.join(rows)}
    </tbody>
  </table>
</section>"""
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Stafford Planning Watch</title>
<style>
  :root {{
    color-scheme: light dark;
    --bg: #ffffff;
    --fg: #1a1a1a;
    --muted: #666666;
    --border: #dddddd;
    --link: #0b5fff;
    --flag-bg: #fff3cd;
    --flag-fg: #7a4a00;
    --flag-border: #e0c060;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #121212;
      --fg: #e8e8e8;
      --muted: #a0a0a0;
      --border: #3a3a3a;
      --link: #6ea8ff;
      --flag-bg: #4a3a00;
      --flag-fg: #ffd873;
      --flag-border: #8a6d1a;
    }}
  }}
  body {{ background: var(--bg); color: var(--fg); font-family: system-ui, -apple-system, Segoe UI, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }}
  h1 {{ margin-bottom: 0.2rem; }}
  .sub {{ color: var(--muted); margin-top: 0; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 1.5rem; }}
  th, td {{ text-align: left; padding: 0.5rem; border-bottom: 1px solid var(--border); vertical-align: top; font-size: 0.92rem; }}
  tr.flagged {{ background: var(--flag-bg); }}
  tr.flagged td {{ color: var(--flag-fg); border-bottom-color: var(--flag-border); }}
  .flag {{ font-weight: 600; }}
  .meta {{ color: var(--muted); font-size: 0.9rem; }}
  a {{ color: var(--link); }}
  footer {{ color: var(--muted); font-size: 0.8rem; margin-top: 2rem; }}
</style>
</head>
<body>
<h1>Stafford Planning Watch</h1>
<p class="sub">Weekly planning applications from Stafford Borough Council, flagged for HMOs, migrants/asylum seekers, and Serco.
Search any reference at <a href="{PUBLIC_ACCESS_URL}">Public Access</a>.</p>
{''.join(sections) if sections else '<p>No applications recorded yet.</p>'}
<footer>Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}. Source: <a href="{INDEX_URL}">Planning Weekly List</a>.</footer>
</body>
</html>"""
    HTML_FILE.parent.mkdir(parents=True, exist_ok=True)
    HTML_FILE.write_text(html, encoding="utf-8")


def send_email(new_week_labels, all_records, pages_url):
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")
    mail_to = os.environ.get("MAIL_TO")

    if not (smtp_user and smtp_pass and mail_to):
        log("Email not configured (SMTP_USER/SMTP_PASS/MAIL_TO missing) - skipping send.")
        return

    new_records = [r for r in all_records if r["week"] in new_week_labels]
    flagged = [r for r in new_records if r["flags"]]

    lines = [
        f"Stafford planning update: {len(new_records)} new application(s) across {len(new_week_labels)} week(s).",
        "",
    ]
    if flagged:
        lines.append(f"FLAGGED ({len(flagged)}):")
        for r in flagged:
            lines.append(f"- [{', '.join(r['flags'])}] {r['ref']}: {r['proposal']}")
        lines.append("")
    else:
        lines.append("No applications matched HMO / migrant-asylum / Serco keywords this time.")
        lines.append("")

    lines.append(f"Full list: {pages_url}")
    lines.append(f"Search any reference: {PUBLIC_ACCESS_URL}")

    body = "\n".join(lines)
    subject = f"Stafford Planning: {len(flagged)} flagged of {len(new_records)} new"

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = mail_to

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, [mail_to], msg.as_string())
    log(f"Email sent to {mail_to}")


def main():
    state = load_json(STATE_FILE, {"processed_weeks": []})
    processed = set(state["processed_weeks"])

    links = fetch_weekly_links()
    if not links:
        log("No weekly list links found on index page.")
        return

    new_links = [(label, url) for label, url in links if label not in processed]
    all_records = load_json(DATA_FILE, [])

    if not new_links:
        log("No new weekly lists since last run.")
        generate_html(all_records)
        return

    log(f"Found {len(new_links)} new weekly list(s): {[l for l, _ in new_links]}")

    for label, url in new_links:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        records = parse_pdf(resp.content, label, url)
        log(f"  {label}: {len(records)} application(s) parsed")
        all_records.extend(records)
        processed.add(label)

    save_json(DATA_FILE, all_records)
    save_json(STATE_FILE, {"processed_weeks": sorted(processed)})
    generate_html(all_records)

    pages_url = os.environ.get("PAGES_URL", "")
    send_email([label for label, _ in new_links], all_records, pages_url)


if __name__ == "__main__":
    main()
