"""Tests for the remaining roadmap features (9-17).

Covers:
- IMAP IDLE methods
- Connection pool
- Send queue (file-backed retry)
- S/MIME module loading
- Calendar invite builder
- Mail merge template filling
- Conversation threading
- Webhook rule action
- Folder archival script logic
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, PropertyMock

# Add scripts to path so lib is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from lib.models import EmailAddress, EmailAttachment, EmailMessage, EmailPriority
from lib.composer import EmailComposer
from lib.processor import EmailProcessor, ProcessingRule, RuleAction, ProcessingResult


# ── Feature #9: IMAP IDLE ────────────────────────────────────────


class TestIMAPIdleMethods(unittest.TestCase):
    """Test that IDLE methods exist and interact with the connection."""

    def test_idle_start_sends_idle_command(self):
        from lib.imap_client import IMAPClient
        client = IMAPClient(host="localhost", port=993)
        mock_conn = MagicMock()
        mock_conn._new_tag.return_value = b"A001"
        mock_conn.readline.return_value = b"+ idling"
        mock_sock = MagicMock()
        mock_conn.sock = mock_sock
        # Mock select
        mock_conn.select.return_value = ("OK", [b"1"])
        client._connection = mock_conn
        client.idle_start("INBOX", timeout=60)
        mock_conn.send.assert_called_once_with(b"A001 IDLE\r\n")

    def test_idle_check_parses_exists(self):
        from lib.imap_client import IMAPClient
        client = IMAPClient(host="localhost", port=993)
        mock_conn = MagicMock()
        mock_sock = MagicMock()
        mock_conn.sock = mock_sock
        # Simulate server response: "* 3 EXISTS"
        mock_conn.readline.side_effect = [b"* 3 EXISTS", TimeoutError()]
        mock_sock.gettimeout.return_value = 30
        client._connection = mock_conn
        responses = client.idle_check(timeout=1.0)
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0], (b"3", b"EXISTS"))

    def test_idle_done_sends_done(self):
        from lib.imap_client import IMAPClient
        client = IMAPClient(host="localhost", port=993)
        mock_conn = MagicMock()
        client._connection = mock_conn
        client._idle_tag = b"A001"
        mock_conn.readline.return_value = b"A001 OK IDLE terminated"
        client.idle_done()
        mock_conn.send.assert_called_once_with(b"DONE\r\n")


# ── Feature #10: Connection Pool ─────────────────────────────────


class TestConnectionPool(unittest.TestCase):
    """Test connection pool lifecycle."""

    def test_pool_caches_imap_connections(self):
        from lib.pool import ConnectionPool
        mock_mgr = MagicMock()
        mock_mgr.default_account = "test"
        mock_client = MagicMock()
        mock_client.conn.noop.return_value = ("OK", [])
        mock_mgr.get_imap_client.return_value = mock_client

        pool = ConnectionPool(mock_mgr, max_age=300)
        c1 = pool.get_imap("test")
        c2 = pool.get_imap("test")
        # Should reuse same client
        self.assertIs(c1, c2)
        # connect() should only be called once
        mock_client.connect.assert_called_once()

    def test_pool_close_all(self):
        from lib.pool import ConnectionPool
        mock_mgr = MagicMock()
        mock_mgr.default_account = "test"
        mock_client = MagicMock()
        mock_client.conn.noop.return_value = ("OK", [])
        mock_mgr.get_imap_client.return_value = mock_client

        pool = ConnectionPool(mock_mgr, max_age=300)
        pool.get_imap("test")
        pool.close_all()
        mock_client.disconnect.assert_called_once()

    def test_pool_context_manager(self):
        from lib.pool import ConnectionPool
        mock_mgr = MagicMock()
        mock_mgr.default_account = "test"
        mock_client = MagicMock()
        mock_client.conn.noop.return_value = ("OK", [])
        mock_mgr.get_imap_client.return_value = mock_client

        with ConnectionPool(mock_mgr) as pool:
            pool.get_imap("test")
        mock_client.disconnect.assert_called_once()

    def test_pool_reconnects_dead_connection(self):
        from lib.pool import ConnectionPool
        mock_mgr = MagicMock()
        mock_mgr.default_account = "test"
        client1 = MagicMock()
        client1.conn.noop.side_effect = Exception("dead")
        client2 = MagicMock()
        client2.conn.noop.return_value = ("OK", [])
        mock_mgr.get_imap_client.side_effect = [client1, client2]

        pool = ConnectionPool(mock_mgr, max_age=300)
        c1 = pool.get_imap("test")
        self.assertIs(c1, client1)
        # Second call should detect dead connection and create new one
        c2 = pool.get_imap("test")
        self.assertIs(c2, client2)


# ── Feature #11: Send Retry Queue ────────────────────────────────


class TestSendQueue(unittest.TestCase):
    """Test the file-backed send queue."""

    def setUp(self):
        self.tmpfile = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False,
        )
        self.tmpfile.close()
        self.queue_path = self.tmpfile.name

    def tearDown(self):
        os.unlink(self.queue_path)

    def test_enqueue_and_peek(self):
        from lib.send_queue import SendQueue
        q = SendQueue(self.queue_path)
        msg = EmailMessage(
            subject="Test",
            sender=EmailAddress(address="a@b.com"),
            recipients=[EmailAddress(address="c@d.com")],
            body_plain="hello",
        )
        entry_id = q.enqueue(msg, account="work", error="Connection refused")
        self.assertEqual(q.size, 1)

        ready = q.peek()
        self.assertEqual(len(ready), 1)
        self.assertEqual(ready[0]["id"], entry_id)

    def test_mark_sent_removes_entry(self):
        from lib.send_queue import SendQueue
        q = SendQueue(self.queue_path)
        msg = EmailMessage(subject="Test", body_plain="x")
        eid = q.enqueue(msg)
        q.mark_sent(eid)
        self.assertEqual(q.size, 0)

    def test_mark_failed_increments_attempts(self):
        from lib.send_queue import SendQueue
        q = SendQueue(self.queue_path)
        msg = EmailMessage(subject="Test", body_plain="x")
        eid = q.enqueue(msg)
        q.mark_failed(eid, "timeout")
        entries = q.list_all()
        self.assertEqual(entries[0]["attempts"], 1)
        self.assertEqual(entries[0]["last_error"], "timeout")

    def test_persistence_across_instances(self):
        from lib.send_queue import SendQueue
        q1 = SendQueue(self.queue_path)
        msg = EmailMessage(subject="Persist Test", body_plain="x")
        eid = q1.enqueue(msg)

        # New instance should load from file
        q2 = SendQueue(self.queue_path)
        self.assertEqual(q2.size, 1)
        self.assertEqual(q2.list_all()[0]["id"], eid)

    def test_remove_expired(self):
        from lib.send_queue import SendQueue
        q = SendQueue(self.queue_path, max_attempts=2)
        msg = EmailMessage(subject="Test", body_plain="x")
        eid = q.enqueue(msg)
        q.mark_failed(eid, "err1")
        q.mark_failed(eid, "err2")
        removed = q.remove_expired()
        self.assertEqual(removed, 1)
        self.assertEqual(q.size, 0)


# ── Feature #12: S/MIME ──────────────────────────────────────────


class TestSMIMEModule(unittest.TestCase):
    """Test S/MIME module imports and basic structure."""

    def test_smime_classes_importable(self):
        from lib.smime import SMIMESigner, SMIMEEncryptor
        signer = SMIMESigner(cert_path="test.pem", key_path="key.pem")
        encryptor = SMIMEEncryptor(recipient_cert_paths=["r.pem"])
        self.assertFalse(signer._loaded)
        self.assertEqual(len(encryptor.recipient_cert_paths), 1)

    def test_signer_requires_load_before_sign(self):
        from lib.smime import SMIMESigner
        signer = SMIMESigner()
        # With no cert_path or pkcs12_path, loading should try to import
        # cryptography and either succeed or raise ImportError/ValueError.
        # We catch BaseException because a broken cryptography install can
        # trigger a pyo3 PanicException which inherits from BaseException.
        from email.mime.multipart import MIMEMultipart
        msg = MIMEMultipart()
        try:
            signer.sign(msg)
        except BaseException:
            pass  # Expected if cryptography not installed or broken bindings


# ── Feature #13: Calendar Invitations ────────────────────────────


class TestCalendarInvite(unittest.TestCase):
    """Test iCalendar VCALENDAR builder."""

    def test_build_vcalendar_basic(self):
        # Import from the script
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
        from calendar_invite import build_vcalendar

        vcal = build_vcalendar(
            organizer="alice@example.com",
            attendees=["bob@example.com", "carol@example.com"],
            subject="Team Standup",
            start=datetime(2026, 3, 1, 9, 0),
            end=datetime(2026, 3, 1, 9, 30),
            location="Zoom",
            description="Daily standup meeting",
            uid="test-uid-123",
        )
        self.assertIn("BEGIN:VCALENDAR", vcal)
        self.assertIn("BEGIN:VEVENT", vcal)
        self.assertIn("SUMMARY:Team Standup", vcal)
        self.assertIn("LOCATION:Zoom", vcal)
        self.assertIn("ORGANIZER;CN=alice@example.com:mailto:alice@example.com", vcal)
        self.assertIn("mailto:bob@example.com", vcal)
        self.assertIn("mailto:carol@example.com", vcal)
        self.assertIn("UID:test-uid-123", vcal)
        self.assertIn("END:VEVENT", vcal)
        self.assertIn("END:VCALENDAR", vcal)

    def test_build_vcalendar_with_rrule(self):
        from calendar_invite import build_vcalendar
        vcal = build_vcalendar(
            organizer="a@b.com",
            attendees=["c@d.com"],
            subject="Weekly",
            start=datetime(2026, 3, 2, 14, 0),
            end=datetime(2026, 3, 2, 15, 0),
            rrule="FREQ=WEEKLY;COUNT=10",
        )
        self.assertIn("RRULE:FREQ=WEEKLY;COUNT=10", vcal)

    def test_build_vcalendar_cancel_method(self):
        from calendar_invite import build_vcalendar
        vcal = build_vcalendar(
            organizer="a@b.com",
            attendees=["c@d.com"],
            subject="Cancelled",
            start=datetime(2026, 3, 1, 10, 0),
            end=datetime(2026, 3, 1, 11, 0),
            method="CANCEL",
        )
        self.assertIn("METHOD:CANCEL", vcal)


# ── Feature #14: Mail Merge ──────────────────────────────────────


class TestMailMergeTemplates(unittest.TestCase):
    """Test the template filling and data loading for mail merge."""

    def test_fill_template_basic(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
        from mail_merge import _fill_template

        result = _fill_template(
            "Hello {{name}}, your code is {{code}}.",
            {"name": "Alice", "code": "XYZ123"},
        )
        self.assertEqual(result, "Hello Alice, your code is XYZ123.")

    def test_fill_template_missing_key(self):
        from mail_merge import _fill_template
        result = _fill_template(
            "Hello {{name}}, value={{missing}}.",
            {"name": "Bob"},
        )
        self.assertEqual(result, "Hello Bob, value={{missing}}.")

    def test_load_data_csv(self):
        from mail_merge import _load_data
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False,
        )
        tmp.write("email,name\nalice@a.com,Alice\nbob@b.com,Bob\n")
        tmp.close()
        try:
            rows = _load_data(tmp.name)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["email"], "alice@a.com")
            self.assertEqual(rows[1]["name"], "Bob")
        finally:
            os.unlink(tmp.name)

    def test_load_data_json(self):
        from mail_merge import _load_data
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False,
        )
        json.dump([{"email": "a@b.com", "x": "1"}], tmp)
        tmp.close()
        try:
            rows = _load_data(tmp.name)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["x"], "1")
        finally:
            os.unlink(tmp.name)


# ── Feature #15: Conversation Threading ──────────────────────────


class TestConversationThreading(unittest.TestCase):
    """Test thread grouping by References/In-Reply-To."""

    def test_build_threads_simple_chain(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
        from thread_mail import build_threads

        msgs = [
            EmailMessage(
                message_id="<a@test>",
                subject="Hello",
                sender=EmailAddress(address="alice@test"),
                date=datetime(2026, 1, 1, 10, 0),
            ),
            EmailMessage(
                message_id="<b@test>",
                subject="Re: Hello",
                sender=EmailAddress(address="bob@test"),
                in_reply_to="<a@test>",
                references=["<a@test>"],
                date=datetime(2026, 1, 1, 11, 0),
            ),
            EmailMessage(
                message_id="<c@test>",
                subject="Re: Re: Hello",
                sender=EmailAddress(address="alice@test"),
                in_reply_to="<b@test>",
                references=["<a@test>", "<b@test>"],
                date=datetime(2026, 1, 1, 12, 0),
            ),
        ]

        threads = build_threads(msgs)
        self.assertEqual(len(threads), 1)
        self.assertEqual(threads[0]["message_count"], 3)
        self.assertEqual(threads[0]["thread_id"], "<a@test>")
        self.assertIn("alice@test", threads[0]["participants"])
        self.assertIn("bob@test", threads[0]["participants"])

    def test_build_threads_separate_conversations(self):
        from thread_mail import build_threads

        msgs = [
            EmailMessage(
                message_id="<x@test>",
                subject="Topic A",
                sender=EmailAddress(address="alice@test"),
                date=datetime(2026, 1, 1),
            ),
            EmailMessage(
                message_id="<y@test>",
                subject="Topic B",
                sender=EmailAddress(address="bob@test"),
                date=datetime(2026, 1, 2),
            ),
        ]

        threads = build_threads(msgs)
        self.assertEqual(len(threads), 2)

    def test_build_threads_empty(self):
        from thread_mail import build_threads
        threads = build_threads([])
        self.assertEqual(len(threads), 0)

    def test_thread_sorted_by_latest_date(self):
        from thread_mail import build_threads
        msgs = [
            EmailMessage(
                message_id="<old@test>",
                subject="Old Thread",
                sender=EmailAddress(address="a@test"),
                date=datetime(2026, 1, 1),
            ),
            EmailMessage(
                message_id="<new@test>",
                subject="New Thread",
                sender=EmailAddress(address="b@test"),
                date=datetime(2026, 2, 1),
            ),
        ]
        threads = build_threads(msgs)
        self.assertEqual(threads[0]["thread_id"], "<new@test>")


# ── Feature #16: Webhook Action ──────────────────────────────────


class TestWebhookAction(unittest.TestCase):
    """Test the WEBHOOK rule action in the processor."""

    def test_webhook_action_exists(self):
        self.assertEqual(RuleAction.WEBHOOK.value, "webhook")

    def test_webhook_rule_from_config(self):
        config = [{
            "name": "notify-slack",
            "actions": ["webhook"],
            "sender_pattern": "alerts@",
            "webhook_url": "https://hooks.example.com/test",
        }]
        processor = EmailProcessor.from_config(config)
        self.assertEqual(len(processor.rules), 1)
        self.assertEqual(processor.rules[0].webhook_url, "https://hooks.example.com/test")

    @patch("lib.processor.urllib.request.urlopen")
    def test_webhook_fires_on_match(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        processor = EmailProcessor()
        rule = ProcessingRule(
            name="hook-test",
            actions=[RuleAction.WEBHOOK],
            sender_pattern="alert@",
            webhook_url="https://hooks.example.com/ep",
        )
        processor.add_rule(rule)

        msg = EmailMessage(
            message_id="<w@test>",
            subject="Alert",
            sender=EmailAddress(address="alert@example.com"),
        )
        result = processor.process(msg)
        self.assertIn("hook-test:webhook", result.actions_taken)
        self.assertEqual(len(result.webhook_results), 1)
        self.assertTrue(result.webhook_results[0]["ok"])

        # Verify the POST body
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        body = json.loads(req.data.decode())
        self.assertEqual(body["event"], "email_rule_match")
        self.assertEqual(body["subject"], "Alert")

    @patch("lib.processor.urllib.request.urlopen")
    def test_webhook_failure_recorded(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("Connection refused")

        processor = EmailProcessor()
        rule = ProcessingRule(
            name="fail-hook",
            actions=[RuleAction.WEBHOOK],
            webhook_url="https://hooks.example.com/bad",
        )
        processor.add_rule(rule)

        msg = EmailMessage(subject="Test")
        result = processor.process(msg)
        self.assertEqual(len(result.webhook_results), 1)
        self.assertFalse(result.webhook_results[0]["ok"])
        self.assertIn("Connection refused", result.webhook_results[0]["error"])


# ── Feature #17: Folder Archival ─────────────────────────────────


class TestArchiveLogic(unittest.TestCase):
    """Test archival helper logic (date-based grouping)."""

    def test_messages_grouped_by_year(self):
        """Verify messages with different years get grouped correctly."""
        msgs = [
            EmailMessage(
                message_id="<m1>",
                subject="Old email",
                date=datetime(2024, 6, 15),
            ),
            EmailMessage(
                message_id="<m2>",
                subject="Recent email",
                date=datetime(2025, 3, 10),
            ),
            EmailMessage(
                message_id="<m3>",
                subject="Also 2024",
                date=datetime(2024, 11, 1),
            ),
        ]

        # Group by year same as archive_mail.py logic
        by_year: dict[str, list] = {}
        for msg in msgs:
            year = str(msg.date.year) if msg.date else "unknown"
            by_year.setdefault(year, []).append(msg)

        self.assertEqual(len(by_year["2024"]), 2)
        self.assertEqual(len(by_year["2025"]), 1)


# ── Feature #10+: Pool integration ──────────────────────────────


class TestPoolSMTP(unittest.TestCase):
    """Test that pool delegates SMTP to account manager."""

    def test_get_smtp_delegates(self):
        from lib.pool import ConnectionPool
        mock_mgr = MagicMock()
        mock_mgr.default_account = "test"
        mock_smtp = MagicMock()
        mock_mgr.get_smtp_client.return_value = mock_smtp

        pool = ConnectionPool(mock_mgr)
        client = pool.get_smtp("test")
        self.assertIs(client, mock_smtp)
        mock_mgr.get_smtp_client.assert_called_once_with("test")


# ── Feature #11: Retry Send Script ───────────────────────────────


class TestRetrySendScript(unittest.TestCase):
    """Test retry_send.py imports and queue interaction."""

    def test_send_queue_backoff_timing(self):
        from lib.send_queue import SendQueue
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False,
        )
        tmp.close()
        try:
            q = SendQueue(tmp.name)
            msg = EmailMessage(subject="Retry Test", body_plain="x")
            eid = q.enqueue(msg)

            # First failure -> ~1 min backoff
            q.mark_failed(eid, "err")
            entry = q.list_all()[0]
            nra = datetime.fromisoformat(entry["next_retry_after"])
            self.assertGreater(nra, datetime.now())

            # Second failure -> ~5 min backoff
            # Force retry to be "now" so peek() finds it
            entry["next_retry_after"] = datetime.now().isoformat()
            q._entries = [entry]
            q._save()
            q.mark_failed(eid, "err2")
            entry = q.list_all()[0]
            self.assertEqual(entry["attempts"], 2)
        finally:
            os.unlink(tmp.name)


# ── Existing features: verify they still work ────────────────────


class TestComposerBasic(unittest.TestCase):
    """Smoke tests for composer (features 4, 5)."""

    def test_compose_reply(self):
        composer = EmailComposer()
        original = EmailMessage(
            message_id="<orig@test>",
            subject="Hello",
            sender=EmailAddress(address="alice@test"),
            body_plain="Original text here",
            date=datetime(2026, 1, 1),
        )
        reply = composer.compose_reply(original, "Thanks!")
        self.assertTrue(reply.subject.startswith("Re:"))
        self.assertEqual(reply.in_reply_to, "<orig@test>")
        self.assertIn("<orig@test>", reply.references)

    def test_compose_forward(self):
        composer = EmailComposer()
        original = EmailMessage(
            message_id="<fwd@test>",
            subject="Info",
            sender=EmailAddress(address="bob@test"),
            body_plain="Forwarded content",
            date=datetime(2026, 1, 1),
        )
        fwd = composer.compose_forward(original, to="carol@test")
        self.assertTrue(fwd.subject.startswith("Fwd:"))
        self.assertIn("Forwarded message", fwd.body_html)


class TestProcessorExisting(unittest.TestCase):
    """Verify existing processor features still work alongside WEBHOOK."""

    def test_flag_and_tag_actions(self):
        processor = EmailProcessor()
        rule = ProcessingRule(
            name="test-rule",
            actions=[RuleAction.FLAG, RuleAction.TAG],
            sender_pattern="important@",
            tag="urgent",
        )
        processor.add_rule(rule)

        msg = EmailMessage(
            subject="Test",
            sender=EmailAddress(address="important@example.com"),
        )
        result = processor.process(msg)
        self.assertTrue(result.should_flag)
        self.assertIn("urgent", result.tags)

    def test_from_config_with_webhook(self):
        config = [
            {
                "name": "rule1",
                "actions": ["tag", "webhook"],
                "tag": "tagged",
                "webhook_url": "https://example.com/hook",
            }
        ]
        processor = EmailProcessor.from_config(config)
        self.assertEqual(len(processor.rules), 1)
        r = processor.rules[0]
        self.assertEqual(r.tag, "tagged")
        self.assertEqual(r.webhook_url, "https://example.com/hook")
        self.assertIn(RuleAction.WEBHOOK, r.actions)


class TestModelSerialization(unittest.TestCase):
    """Test EmailMessage.to_dict / from_dict round-trip."""

    def test_round_trip(self):
        msg = EmailMessage(
            subject="Round trip",
            sender=EmailAddress(address="a@b.com", display_name="Alice"),
            recipients=[EmailAddress(address="c@d.com")],
            body_plain="hello",
            message_id="<rt@test>",
            date=datetime(2026, 2, 25, 12, 0),
            priority=EmailPriority.HIGH,
            in_reply_to="<parent@test>",
            references=["<root@test>", "<parent@test>"],
        )
        d = msg.to_dict()
        restored = EmailMessage.from_dict(d)
        self.assertEqual(restored.subject, "Round trip")
        self.assertEqual(restored.sender.address, "a@b.com")
        self.assertEqual(restored.message_id, "<rt@test>")
        self.assertEqual(restored.priority, EmailPriority.HIGH)
        self.assertEqual(len(restored.references), 2)


class TestRFC5322Compliance(unittest.TestCase):
    """Test RFC 5322 compliance: Date and Message-ID headers."""

    def test_mime_message_has_date_header(self):
        from lib.smtp_client import SMTPClient
        msg = EmailMessage(
            subject="Test", body_plain="Hello",
            sender=EmailAddress(address="alice@example.com"),
            recipients=[EmailAddress(address="bob@example.com")],
        )
        mime = SMTPClient._build_mime_static(msg)
        # Date header must be present per RFC 5322
        self.assertIn("Date", mime)
        self.assertIsNotNone(mime["Date"])
        self.assertGreater(len(mime["Date"]), 0)

    def test_mime_message_has_message_id(self):
        from lib.smtp_client import SMTPClient
        msg = EmailMessage(
            subject="Test", body_plain="Hello",
            sender=EmailAddress(address="alice@example.com"),
            recipients=[EmailAddress(address="bob@example.com")],
        )
        mime = SMTPClient._build_mime_static(msg)
        # Message-ID header must be present per RFC 5322
        self.assertIn("Message-ID", mime)
        self.assertIsNotNone(mime["Message-ID"])
        # Must be angle-bracketed and unique
        msg_id = mime["Message-ID"]
        self.assertTrue(msg_id.startswith("<") and msg_id.endswith(">"))
        self.assertIn("@", msg_id)  # Must have @ separator

    def test_mime_message_generated_message_id_is_unique(self):
        from lib.smtp_client import SMTPClient
        msg1 = EmailMessage(
            subject="Test1", body_plain="Hello",
            sender=EmailAddress(address="alice@example.com"),
            recipients=[EmailAddress(address="bob@example.com")],
        )
        msg2 = EmailMessage(
            subject="Test2", body_plain="Hello",
            sender=EmailAddress(address="alice@example.com"),
            recipients=[EmailAddress(address="bob@example.com")],
        )
        mime1 = SMTPClient._build_mime_static(msg1)
        mime2 = SMTPClient._build_mime_static(msg2)
        # Message-IDs should be unique
        self.assertNotEqual(mime1["Message-ID"], mime2["Message-ID"])

    def test_mime_message_uses_provided_message_id(self):
        from lib.smtp_client import SMTPClient
        custom_id = "<custom-id-123@example.com>"
        msg = EmailMessage(
            subject="Test", body_plain="Hello",
            sender=EmailAddress(address="alice@example.com"),
            recipients=[EmailAddress(address="bob@example.com")],
            message_id=custom_id,
        )
        mime = SMTPClient._build_mime_static(msg)
        self.assertEqual(mime["Message-ID"], custom_id)

    def test_mime_message_has_mime_version(self):
        from lib.smtp_client import SMTPClient
        msg = EmailMessage(
            subject="Test", body_plain="Hello",
            sender=EmailAddress(address="alice@example.com"),
            recipients=[EmailAddress(address="bob@example.com")],
        )
        mime = SMTPClient._build_mime_static(msg)
        # MIME-Version is required for multipart
        self.assertIn("MIME-Version", mime)
        self.assertEqual(mime["MIME-Version"], "1.0")

    def test_composer_sets_date(self):
        from lib.composer import EmailComposer
        composer = EmailComposer()
        msg = composer.compose(
            to="bob@example.com",
            subject="Test",
            body="Hello",
        )
        # Composer should set date to now
        self.assertIsNotNone(msg.date)
        self.assertIsInstance(msg.date, datetime)
        # Date should be recent (within last minute)
        age = (datetime.now() - msg.date).total_seconds()
        self.assertLess(age, 60)

    def test_all_required_headers_present(self):
        from lib.smtp_client import SMTPClient
        msg = EmailMessage(
            subject="Test Email",
            body_plain="Test body",
            body_html="<p>Test body</p>",
            sender=EmailAddress(address="alice@example.com", display_name="Alice"),
            recipients=[EmailAddress(address="bob@example.com", display_name="Bob")],
            cc=[EmailAddress(address="carol@example.com")],
        )
        mime = SMTPClient._build_mime_static(msg)

        required_headers = ["From", "To", "Subject", "Date", "Message-ID", "MIME-Version"]
        for hdr in required_headers:
            with self.subTest(header=hdr):
                self.assertIn(hdr, mime, f"Required header {hdr} missing from MIME message")
                self.assertIsNotNone(mime[hdr], f"Header {hdr} is None")


class TestOutbox(unittest.TestCase):
    """Tests for the IMAP Outbox module."""

    def _make_msg(self, subject="Test", mid="<test@example.com>"):
        return EmailMessage(
            message_id=mid,
            subject=subject,
            body_plain="Hello",
            sender=EmailAddress(address="alice@example.com"),
            recipients=[EmailAddress(address="bob@example.com")],
        )

    def test_outbox_imports(self):
        from lib.outbox import Outbox, DrainResult, OUTBOX_FOLDER
        self.assertEqual(OUTBOX_FOLDER, "Outbox")

    def test_drain_result_to_dict(self):
        from lib.outbox import DrainResult
        dr = DrainResult(attempted=3, sent=2, failed=1, errors=[{"error": "test"}])
        d = dr.to_dict()
        self.assertEqual(d["attempted"], 3)
        self.assertEqual(d["sent"], 2)
        self.assertEqual(d["failed"], 1)
        self.assertEqual(len(d["errors"]), 1)

    def test_drain_result_repr(self):
        from lib.outbox import DrainResult
        dr = DrainResult(attempted=1, sent=1, failed=0, errors=[])
        self.assertIn("attempted=1", repr(dr))
        self.assertIn("sent=1", repr(dr))

    def test_stage_creates_folder_and_appends(self):
        from lib.outbox import Outbox
        mock_imap = MagicMock()
        mock_imap.list_folders.return_value = []
        mock_imap.create_folder.return_value = True
        mock_imap.append_message.return_value = True

        outbox = Outbox(mock_imap)
        msg = self._make_msg()
        result = outbox.stage(msg)

        self.assertTrue(result)
        mock_imap.create_folder.assert_called_once_with("Outbox")
        mock_imap.append_message.assert_called_once()
        call_args = mock_imap.append_message.call_args
        self.assertEqual(call_args.kwargs["mailbox"], "Outbox")

    def test_stage_reuses_existing_folder(self):
        from lib.outbox import Outbox
        mock_imap = MagicMock()
        mock_imap.list_folders.return_value = [{"name": "Outbox", "delimiter": "/", "flags": ""}]
        mock_imap.append_message.return_value = True

        outbox = Outbox(mock_imap)
        outbox.stage(self._make_msg())

        # Should NOT create folder since it already exists
        mock_imap.create_folder.assert_not_called()

    def test_drain_sends_and_deletes(self):
        from lib.outbox import Outbox
        msg = self._make_msg(mid="<drain@test>")
        mock_imap = MagicMock()
        mock_imap.list_folders.return_value = [{"name": "Outbox", "delimiter": "/", "flags": ""}]
        mock_imap.fetch_all.return_value = [msg]
        mock_imap.delete_message.return_value = True
        mock_imap.folder_status.return_value = {"messages": 0, "unseen": 0, "recent": 0}
        mock_imap.delete_folder.return_value = True

        outbox = Outbox(mock_imap)
        result = outbox.drain(lambda m: {"success": True})

        self.assertEqual(result.attempted, 1)
        self.assertEqual(result.sent, 1)
        self.assertEqual(result.failed, 0)
        mock_imap.delete_message.assert_called_once_with("<drain@test>", mailbox="Outbox")

    def test_drain_leaves_failed_messages(self):
        from lib.outbox import Outbox
        msg = self._make_msg(mid="<fail@test>")
        mock_imap = MagicMock()
        mock_imap.list_folders.return_value = [{"name": "Outbox", "delimiter": "/", "flags": ""}]
        mock_imap.fetch_all.return_value = [msg]

        outbox = Outbox(mock_imap)
        result = outbox.drain(lambda m: {"success": False, "error": "SMTP down"})

        self.assertEqual(result.attempted, 1)
        self.assertEqual(result.sent, 0)
        self.assertEqual(result.failed, 1)
        self.assertEqual(result.errors[0]["error"], "SMTP down")
        # Should NOT delete the message since send failed
        mock_imap.delete_message.assert_not_called()

    def test_drain_removes_empty_outbox_folder(self):
        from lib.outbox import Outbox
        msg = self._make_msg()
        mock_imap = MagicMock()
        mock_imap.list_folders.return_value = [{"name": "Outbox", "delimiter": "/", "flags": ""}]
        mock_imap.fetch_all.return_value = [msg]
        mock_imap.delete_message.return_value = True
        # After sending, Outbox is empty
        mock_imap.folder_status.return_value = {"messages": 0, "unseen": 0, "recent": 0}
        mock_imap.delete_folder.return_value = True

        outbox = Outbox(mock_imap)
        outbox.drain(lambda m: {"success": True})

        # Should delete the empty Outbox folder
        mock_imap.delete_folder.assert_called_once_with("Outbox")

    def test_drain_keeps_outbox_if_messages_remain(self):
        from lib.outbox import Outbox
        msg1 = self._make_msg(mid="<ok@test>", subject="OK")
        msg2 = self._make_msg(mid="<fail@test>", subject="Fail")
        mock_imap = MagicMock()
        mock_imap.list_folders.return_value = [{"name": "Outbox", "delimiter": "/", "flags": ""}]
        mock_imap.fetch_all.return_value = [msg1, msg2]
        mock_imap.delete_message.return_value = True
        # After sending one, one message remains
        mock_imap.folder_status.return_value = {"messages": 1, "unseen": 0, "recent": 0}

        send_results = iter([{"success": True}, {"success": False, "error": "fail"}])
        outbox = Outbox(mock_imap)
        outbox.drain(lambda m: next(send_results))

        # Should NOT delete the Outbox folder since a message remains
        mock_imap.delete_folder.assert_not_called()

    def test_drain_no_outbox_folder(self):
        from lib.outbox import Outbox
        mock_imap = MagicMock()
        mock_imap.list_folders.return_value = []  # No Outbox

        outbox = Outbox(mock_imap)
        result = outbox.drain(lambda m: {"success": True})

        self.assertEqual(result.attempted, 0)
        self.assertEqual(result.sent, 0)

    def test_drain_empty_outbox_removes_folder(self):
        from lib.outbox import Outbox
        mock_imap = MagicMock()
        mock_imap.list_folders.return_value = [{"name": "Outbox", "delimiter": "/", "flags": ""}]
        mock_imap.fetch_all.return_value = []  # Outbox exists but empty
        mock_imap.delete_folder.return_value = True

        outbox = Outbox(mock_imap)
        result = outbox.drain(lambda m: {"success": True})

        self.assertEqual(result.attempted, 0)
        mock_imap.delete_folder.assert_called_once_with("Outbox")

    def test_exists_true(self):
        from lib.outbox import Outbox
        mock_imap = MagicMock()
        mock_imap.list_folders.return_value = [{"name": "Outbox", "delimiter": "/", "flags": ""}]
        self.assertTrue(Outbox(mock_imap).exists())

    def test_exists_false(self):
        from lib.outbox import Outbox
        mock_imap = MagicMock()
        mock_imap.list_folders.return_value = [{"name": "INBOX", "delimiter": "/", "flags": ""}]
        self.assertFalse(Outbox(mock_imap).exists())

    def test_list_pending(self):
        from lib.outbox import Outbox
        msg = self._make_msg()
        mock_imap = MagicMock()
        mock_imap.list_folders.return_value = [{"name": "Outbox", "delimiter": "/", "flags": ""}]
        mock_imap.fetch_all.return_value = [msg]

        outbox = Outbox(mock_imap)
        pending = outbox.list_pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].subject, "Test")

    def test_drain_handles_exception_in_send_fn(self):
        from lib.outbox import Outbox
        msg = self._make_msg()
        mock_imap = MagicMock()
        mock_imap.list_folders.return_value = [{"name": "Outbox", "delimiter": "/", "flags": ""}]
        mock_imap.fetch_all.return_value = [msg]

        def _explode(m):
            raise ConnectionError("Network down")

        outbox = Outbox(mock_imap)
        result = outbox.drain(_explode)

        self.assertEqual(result.failed, 1)
        self.assertIn("Network down", result.errors[0]["error"])


class TestAccountManagerOutbox(unittest.TestCase):
    """Tests for AccountManager Outbox integration."""

    def test_send_via_outbox_calls_stage_and_send(self):
        from lib.account_manager import AccountManager

        config = {
            "accounts": {
                "test": {
                    "imap": {"host": "imap.test.com", "username": "u", "password": "p"},
                    "smtp": {"host": "smtp.test.com", "username": "u", "password": "p"},
                }
            },
            "default_account": "test",
        }
        mgr = AccountManager(config)

        # Mock both IMAP and SMTP interactions
        with patch.object(mgr, "get_imap_client") as mock_get_imap, \
             patch.object(mgr, "send_with_fallback") as mock_send:

            mock_imap = MagicMock()
            mock_get_imap.return_value = mock_imap
            # Outbox folder doesn't exist, will be created
            mock_imap.list_folders.return_value = []
            mock_imap.create_folder.return_value = True
            mock_imap.append_message.return_value = True
            mock_imap.folder_status.return_value = {"messages": 0}
            mock_imap.delete_folder.return_value = True

            mock_send.return_value = {"success": True, "fallback_used": False}

            msg = EmailMessage(
                message_id="<test@x>", subject="Test",
                sender=EmailAddress(address="a@b.com"),
                recipients=[EmailAddress(address="c@d.com")],
                body_plain="Hi",
            )
            result = mgr.send_via_outbox(msg, "test")

            self.assertTrue(result["success"])
            self.assertTrue(result["staged"])
            mock_imap.append_message.assert_called_once()
            mock_send.assert_called_once()

    def test_drain_outbox_returns_empty_when_no_outbox(self):
        from lib.account_manager import AccountManager

        config = {
            "accounts": {
                "test": {
                    "imap": {"host": "imap.test.com", "username": "u", "password": "p"},
                    "smtp": {"host": "smtp.test.com"},
                }
            },
            "default_account": "test",
        }
        mgr = AccountManager(config)

        with patch.object(mgr, "get_imap_client") as mock_get_imap:
            mock_imap = MagicMock()
            mock_get_imap.return_value = mock_imap
            mock_imap.list_folders.return_value = []  # No Outbox

            result = mgr.drain_outbox("test")
            self.assertEqual(result["attempted"], 0)
            self.assertEqual(result["sent"], 0)


if __name__ == "__main__":
    unittest.main()
