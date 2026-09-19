# Stafford Planning Watch

Automatically checks [Stafford Borough Council's Planning Weekly List](https://www.staffordbc.gov.uk/planning-weekly-list)
for new planning applications, flags any mentioning HMOs, migrants/asylum
seekers, or Serco, and publishes a browsable page via GitHub Pages plus an
email summary when a new week is published.

## How it works

- `.github/workflows/check.yml` runs daily (harmless no-op most days — the
  council only publishes a new list weekly) and on manual dispatch.
- `scripts/fetch_and_report.py`:
  1. Scrapes the weekly-list index page for links to new PDFs.
  2. Downloads and parses each new PDF (`pdfplumber`, column-position based).
  3. Flags applications matching keywords in `KEYWORDS` (edit the script to
     add more).
  4. Appends to `data/applications.json` (full history) and regenerates
     `docs/index.html`.
  5. Emails a summary if `SMTP_USER` / `SMTP_PASS` / `MAIL_TO` secrets are set.

## One-time setup

1. Enable GitHub Pages: repo Settings → Pages → Source = `main` branch,
   folder `/docs`.
2. Add repo secrets (Settings → Secrets and variables → Actions):
   - `SMTP_USER` — sending email address (e.g. a Gmail address)
   - `SMTP_PASS` — an [app password](https://myaccount.google.com/apppasswords)
     for that account (not your normal password)
   - `MAIL_TO` — where the weekly summary should go
3. Run the workflow once manually (Actions tab → "Check Stafford planning
   list" → Run workflow) to do the initial backfill.

## Local run

```
pip install -r requirements.txt
python scripts/fetch_and_report.py
```

Without the SMTP secrets set as environment variables, it skips sending
email but still updates `data/` and `docs/index.html`.
