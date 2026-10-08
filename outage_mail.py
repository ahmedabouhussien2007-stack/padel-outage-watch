"""Emails for a day the website is down. Run by .github/workflows/watch.yml.

    python outage_mail.py down SNAPSHOT.json [--to ADDRESS]
    python outage_mail.py back SNAPSHOT.json [--to ADDRESS]

SNAPSHOT.json is what the academy's /cron/schedule-snapshot returned while the site
was healthy: {"generated_at": "...", "messages": [{"to", "subject", "body"}]}.

Settings come from the environment: SMTP_HOST, SMTP_PORT (587), SMTP_USER,
SMTP_PASSWORD, EMAIL_FROM — the same values the website itself uses to send mail.

This repository is public, so its run logs are readable by anyone: this script
prints only counts, never an address or a line of the schedule.

--to is for a dry run: only ONE email (the first message) goes, to that address,
marked [TEST]; nobody else is contacted.
"""
import json
import os
import smtplib
import sys
import time
from email.message import EmailMessage

DOWN_INTRO = (
    "The Royal Padel Academy website is not working right now. Sessions run as normal.\n\n"
    "Here is your schedule as it was at {generated_at} (Cairo time). Anything booked or "
    "changed after that is not included.\n\n"
)
DOWN_OUTRO = "\n--\nSent automatically because the website stayed unreachable for several minutes. You will get one short email when it is working again.\n"
BACK_BODY = ("The Royal Padel Academy website is working again, and your schedule on it is up to date.\n\n"
             "Go to the website to check your sessions:\n{site}/login\n\n--\nSent automatically.\n")
DEFAULT_SITE = 'https://padel-academy.vercel.app'


def load_snapshot(path):
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    messages = data.get('messages')
    if not isinstance(messages, list):
        raise ValueError('the snapshot has no messages list')
    for m in messages:
        if not all(isinstance(m.get(k), str) and m[k] for k in ('to', 'subject', 'body')):
            raise ValueError('a message in the snapshot is missing to/subject/body')
    return {'generated_at': str(data.get('generated_at', 'an earlier time')), 'messages': messages}


def down_emails(snapshot):
    return [(m['to'], 'Website down — ' + m['subject'],
             DOWN_INTRO.format(generated_at=snapshot['generated_at']) + m['body'] + DOWN_OUTRO)
            for m in snapshot['messages']]


def back_emails(snapshot, site=DEFAULT_SITE):
    body = BACK_BODY.format(site=site.rstrip('/'))
    seen, out = set(), []
    for m in snapshot['messages']:
        if m['to'].lower() not in seen:
            seen.add(m['to'].lower())
            out.append((m['to'], 'Website working again — check your schedule', body))
    return out


def dry_run(emails, address):
    """One email only, to the tester, clearly marked."""
    return [(address, '[TEST] ' + emails[0][1], emails[0][2])] if emails else []


def send_all(emails, env=os.environ, smtp_class=smtplib.SMTP, sleep=time.sleep):
    """(sent, failed). One connection for the lot; one bad address never stops the rest,
    and anything that failed (a rate limit, a hiccup) gets one more try after a pause."""
    host = env.get('SMTP_HOST', '').strip()
    sender = env.get('EMAIL_FROM', '').strip()
    if not host or not sender:
        raise RuntimeError('SMTP_HOST and EMAIL_FROM must be set')
    sent = 0
    pending = list(emails)
    with smtp_class(host, int(env.get('SMTP_PORT', '587') or 587), timeout=30) as smtp:
        if smtp.has_extn('starttls'):
            smtp.starttls()
        user = env.get('SMTP_USER', '').strip()
        if user:
            smtp.login(user, env.get('SMTP_PASSWORD', '').strip())
        for attempt in (1, 2):
            failed = []
            for to, subject, body in pending:
                try:
                    message = EmailMessage()
                    message['From'], message['To'], message['Subject'] = sender, to, subject
                    message.set_content(body)
                    smtp.send_message(message)
                    sent += 1
                except (smtplib.SMTPException, OSError, ValueError):   # ValueError: a malformed header
                    failed.append((to, subject, body))
            pending = failed
            if not pending or attempt == 2:
                break
            sleep(5)
    return sent, len(pending)


def main(argv, env=os.environ, smtp_class=smtplib.SMTP, sleep=time.sleep):
    args = list(argv)
    to = None
    if '--to' in args:
        i = args.index('--to')
        to = args[i + 1]
        del args[i:i + 2]
    if len(args) != 2 or args[0] not in ('down', 'back'):
        print(__doc__)
        return 2
    mode, path = args
    snapshot = load_snapshot(path)
    emails = (down_emails(snapshot) if mode == 'down'
              else back_emails(snapshot, env.get('SITE_URL') or DEFAULT_SITE))
    if to:
        emails = dry_run(emails, to)
    if not emails:
        print('Nothing to send: the saved schedule has no recipients.')
        return 0
    sent, failed = send_all(emails, env, smtp_class, sleep)
    print(f'{mode}: sent {sent}, failed {failed}')
    return 0 if sent else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
