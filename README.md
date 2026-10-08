# padel-outage-watch

(Kept here so it isn't lost; it runs from its own public GitHub repository,
`padel-outage-watch`. `bash tools/set_outage_secrets.sh` sets it up.)

Plan B for the Royal Padel Academy website. If the site is down for about four
minutes, everyone with an email on file gets their own schedule by email (admins
the whole schedule, each coach and player only theirs), once per outage, and one short
"working again" email afterwards. On a normal day nothing is sent.

- `.github/workflows/watch.yml` — runs every 5 minutes, keeps an encrypted copy of
  the schedule, sends the emails.
- `outage_mail.py` — builds and sends the emails (tested in `test_outage_mail.py`).

This repository is public only so GitHub's free minutes cover running all day. It
contains no data and no secrets: settings live in the repository's Actions secrets
(`CRON_SECRET`, `SNAPSHOT_PASSPHRASE`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`,
`SMTP_PASSWORD`, `EMAIL_FROM`), and the logs never show an address or schedule.

Dry run: **Actions → Watch the website → Run workflow**, choose `down` or `back`
and enter your own address. Only that address is emailed.
