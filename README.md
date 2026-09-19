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
  5. Emails a summary — always stating how many were flagged, even if zero —
     to everyone in `MAIL_TO` plus anyone who has signed up via the Google
     Form (see below), if `SMTP_USER` / `SMTP_PASS` / `MAIL_TO` secrets are
     set. Each recipient is emailed individually so subscribers can't see
     each other's addresses.

## One-time setup

1. Enable GitHub Pages: repo Settings → Pages → Source = `main` branch,
   folder `/docs`.
2. Add repo secrets (Settings → Secrets and variables → Actions):
   - `SMTP_USER` — sending email address (e.g. a Gmail address)
   - `SMTP_PASS` — an [app password](https://myaccount.google.com/apppasswords)
     for that account (not your normal password)
   - `MAIL_TO` — comma-separated fixed recipients, e.g.
     `you@example.com,team@example.org`
   - `GOOGLE_FORM_CSV_URL` — optional, see below
3. Run the workflow once manually (Actions tab → "Check Stafford planning
   list" → Run workflow) to do the initial backfill.

### Self-service signup via Google Form

1. Create a Google Form with one short-answer question, e.g. "Email
   address" (the field name just needs to contain the word "email").
2. In the Form's *Responses* tab, click the Sheets icon to create a linked
   response spreadsheet.
3. In that Sheet: File → Share → Publish to web → select the responses
   sheet/tab → format **Comma-separated values (.csv)** → Publish. Copy the
   resulting URL.
4. Add it as the `GOOGLE_FORM_CSV_URL` repo secret.
5. Share the Form's public link with anyone who wants to subscribe. Each
   run of the checker re-reads the sheet and emails everyone in it, so new
   signups start receiving the digest from the next run onward.

Note: publishing a sheet "to the web" makes it readable by anyone who has
that exact URL (it isn't discoverable, but it isn't access-controlled
either) — don't publish a sheet that has other columns you'd rather keep
private.

## Local run

```
pip install -r requirements.txt
python scripts/fetch_and_report.py
```

Without the SMTP secrets set as environment variables, it skips sending
email but still updates `data/` and `docs/index.html`.
