import io
import json
import os
import smtplib
import tempfile
import unittest
from contextlib import redirect_stdout

import outage_mail as om

SNAP = {'generated_at': '2026-10-04 09:05', 'messages': [
    {'to': 'boss@example.com', 'subject': 'Schedule for Sun, Oct 4 — 2 sessions today', 'body': 'TODAY — everything\n'},
    {'to': 'coach@example.com', 'subject': 'Your schedule for Sun, Oct 4 — 1 session today', 'body': 'TODAY — only mine\n'},
]}
ENV = {'SMTP_HOST': 'smtp.example.com', 'SMTP_PORT': '587', 'SMTP_USER': 'u', 'SMTP_PASSWORD': 'p', 'EMAIL_FROM': 'Royal Padel <no-reply@example.com>'}


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.sent, self.logged_in, self.tls = host, port, [], None, False
        self.fail_for = set()
        FakeSMTP.instances.append(self)

    def __enter__(self): return self
    def __exit__(self, *a): return False
    def has_extn(self, name): return True
    def starttls(self): self.tls = True
    def login(self, u, p): self.logged_in = (u, p)

    def send_message(self, m):
        if m['To'] in FakeSMTP.fail_for:
            raise smtplib.SMTPRecipientsRefused({m['To']: (550, b'no')})
        self.sent.append(m)


def write(data):
    f = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False)
    json.dump(data, f); f.close()
    return f.name


class OutageMailTests(unittest.TestCase):
    def setUp(self):
        FakeSMTP.instances, FakeSMTP.fail_for = [], set()

    def run_main(self, args, env=ENV):
        out = io.StringIO()
        with redirect_stdout(out):
            code = om.main(args, env, FakeSMTP, sleep=lambda s: None)
        return code, out.getvalue()

    def test_down_emails_carry_each_persons_own_schedule_and_the_time_it_is_from(self):
        code, out = self.run_main(['down', write(SNAP)])
        self.assertEqual(code, 0)
        sent = FakeSMTP.instances[0].sent
        self.assertEqual([m['To'] for m in sent], ['boss@example.com', 'coach@example.com'])
        coach = sent[1]
        self.assertTrue(coach['Subject'].startswith('Website down — Your schedule'))
        body = coach.get_content()
        self.assertIn('only mine', body)
        self.assertNotIn('everything', body)
        self.assertIn('2026-10-04 09:05', body)
        self.assertIn('not working right now', body)

    def test_the_log_never_shows_an_address_or_any_schedule_text(self):
        _, out = self.run_main(['down', write(SNAP)])
        self.assertEqual(out.strip(), 'down: sent 2, failed 0')
        for secret in ('boss@example.com', 'coach@example.com', 'TODAY', 'only mine'):
            self.assertNotIn(secret, out)

    def test_smtp_is_started_with_tls_and_logged_in(self):
        self.run_main(['down', write(SNAP)])
        smtp = FakeSMTP.instances[0]
        self.assertEqual((smtp.host, smtp.port, smtp.tls, smtp.logged_in), ('smtp.example.com', 587, True, ('u', 'p')))

    def test_one_refused_address_does_not_stop_the_others(self):
        FakeSMTP.fail_for = {'boss@example.com'}
        code, out = self.run_main(['down', write(SNAP)])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), 'down: sent 1, failed 1')

    def test_a_failed_send_gets_one_more_try(self):
        calls = {'n': 0}
        real = FakeSMTP.send_message

        def flaky(self, m):
            if m['To'] == 'boss@example.com' and calls['n'] == 0:
                calls['n'] += 1
                raise smtplib.SMTPServerDisconnected('rate limited')
            return real(self, m)
        FakeSMTP.send_message = flaky
        try:
            code, out = self.run_main(['down', write(SNAP)])
        finally:
            FakeSMTP.send_message = real
        self.assertEqual(out.strip(), 'down: sent 2, failed 0')

    def test_an_address_that_breaks_the_headers_fails_alone_and_does_not_abort_the_batch(self):
        bad = {'generated_at': 'x', 'messages': [
            {'to': 'good@example.com', 'subject': 's', 'body': 'b'},
            {'to': 'evil@example.com\nBcc: x@y.z', 'subject': 's', 'body': 'b'},
            {'to': 'also.good@example.com', 'subject': 's', 'body': 'b'}]}
        code, out = self.run_main(['down', write(bad)])
        self.assertEqual(out.strip(), 'down: sent 2, failed 1')
        self.assertEqual([m['To'] for m in FakeSMTP.instances[0].sent], ['good@example.com', 'also.good@example.com'])

    def test_everything_failing_is_an_error_so_the_workflow_tries_again(self):
        FakeSMTP.fail_for = {'boss@example.com', 'coach@example.com'}
        code, _ = self.run_main(['down', write(SNAP)])
        self.assertEqual(code, 1)

    def test_back_is_one_short_email_per_person(self):
        dup = {'generated_at': 'x', 'messages': SNAP['messages'] + [dict(SNAP['messages'][0], to='BOSS@example.com')]}
        code, _ = self.run_main(['back', write(dup)])
        sent = FakeSMTP.instances[0].sent
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[0]['Subject'], 'Website working again — check your schedule')
        body = sent[0].get_content()
        self.assertIn('your schedule on it is up to date', body)
        self.assertIn('https://padel-academy.vercel.app/login', body)   # the default address
        self.assertNotIn('TODAY', body)

    def test_back_links_to_the_site_address_in_use(self):
        code, _ = self.run_main(['back', write(SNAP)], env=dict(ENV, SITE_URL='https://royalpadel.example/'))
        self.assertIn('https://royalpadel.example/login', FakeSMTP.instances[0].sent[0].get_content())

    def test_a_dry_run_sends_one_marked_email_to_the_tester_only(self):
        code, out = self.run_main(['down', write(SNAP), '--to', 'me@example.com'])
        sent = FakeSMTP.instances[0].sent
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]['To'], 'me@example.com')
        self.assertTrue(sent[0]['Subject'].startswith('[TEST] Website down'))
        self.assertEqual(out.strip(), 'down: sent 1, failed 0')

    def test_no_recipients_is_not_an_error(self):
        code, out = self.run_main(['down', write({'generated_at': 'x', 'messages': []})])
        self.assertEqual(code, 0)
        self.assertEqual(FakeSMTP.instances, [])

    def test_missing_smtp_settings_fail_loudly(self):
        with self.assertRaises(RuntimeError):
            self.run_main(['down', write(SNAP)], env={})

    def test_a_malformed_snapshot_is_rejected(self):
        for bad in ({'messages': 'nope'}, {'messages': [{'to': 'a@b.c', 'subject': 's'}]}):
            with self.assertRaises(ValueError):
                self.run_main(['down', write(bad)])

    def test_bad_arguments_print_usage(self):
        code, out = self.run_main(['sideways', 'x.json'])
        self.assertEqual(code, 2)
        self.assertIn('outage_mail.py down', out)


if __name__ == '__main__':
    unittest.main()
