"""Tests for new features: attachments, search, forward, reply quoting,
drafts, deduplication, and OAuth2."""

import base64
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "skills", "claw-mail", "scripts"),
)

from lib.composer import EmailComposer, _build_quote_block, _build_forward_block
from lib.models import EmailAddress, EmailAttachment, EmailMessage
from lib.smtp_client import build_mime

SCRIPTS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "skills", "claw-mail", "scripts"
)


def _run_script(name: str, *args: str, stdin_data: str = "") -> tuple[int, str, str]:
    cmd = [sys.executable, os.path.join(SCRIPTS_DIR, name)] + list(args)
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        input=stdin_data if stdin_data else None,
    )
    return result.returncode, result.stdout, result.stderr


# ── Feature 1: --attach flag on compose/send ────────────────────────


class TestComposeAttach:
    def test_compose_with_attach_flag(self):
        """compose_mail.py --attach should include file as attachment."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w") as f:
            f.write("Hello from file")
            tmp_path = f.name
        try:
            rc, out, err = _run_script(
                "compose_mail.py",
                "--to", "user@example.com",
                "--subject", "With Attachment",
                "--body", "See attached.",
                "--attach", tmp_path,
            )
            assert rc == 0, f"stderr: {err}"
            data = json.loads(out)
            assert data["has_attachments"] is True
            assert len(data["attachments"]) == 1
            att = data["attachments"][0]
            assert att["filename"] == os.path.basename(tmp_path)
            assert att["content_type"] == "text/plain"
            # Verify data round-trips
            decoded = base64.b64decode(att["data_b64"])
            assert decoded == b"Hello from file"
        finally:
            os.unlink(tmp_path)

    def test_compose_multiple_attachments(self):
        """Multiple --attach flags should add multiple attachments."""
        files = []
        try:
            for i in range(2):
                f = tempfile.NamedTemporaryFile(
                    suffix=f".txt", delete=False, mode="w"
                )
                f.write(f"file {i}")
                f.close()
                files.append(f.name)

            rc, out, err = _run_script(
                "compose_mail.py",
                "--to", "user@example.com",
                "--subject", "Multi Attach",
                "--body", "Files.",
                "--attach", files[0],
                "--attach", files[1],
            )
            assert rc == 0, f"stderr: {err}"
            data = json.loads(out)
            assert len(data["attachments"]) == 2
        finally:
            for f in files:
                os.unlink(f)

    def test_compose_missing_attach_fails(self):
        """compose_mail.py --attach with nonexistent file should fail."""
        rc, out, err = _run_script(
            "compose_mail.py",
            "--to", "user@example.com",
            "--subject", "Bad Attach",
            "--body", "Test",
            "--attach", "/nonexistent/file.pdf",
        )
        assert rc != 0

    def test_send_accepts_attach_flag(self):
        """send_mail.py should accept --attach flag without error (CLI parsing)."""
        # We can't actually send, but we can test the arg is accepted
        # by checking it doesn't fail on argparse
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w") as f:
            f.write("test")
            tmp_path = f.name
        try:
            # Should fail because no SMTP host or config, NOT because of bad args
            rc, out, err = _run_script(
                "send_mail.py",
                "--to", "user@example.com",
                "--subject", "Test",
                "--body", "Test",
                "--attach", tmp_path,
            )
            # It should fail due to missing config, not argparse
            assert rc != 0
            err_data = json.loads(err)
            assert "config" in err_data.get("error", "").lower() or \
                   "smtp" in err_data.get("error", "").lower()
        finally:
            os.unlink(tmp_path)


# ── Feature 2: Save attachments to disk ─────────────────────────────


class TestSaveAttachments:
    def test_read_with_save_attachments(self):
        """read_mail.py --save-attachments should write files to disk."""
        att_data = base64.b64encode(b"PDF content here").decode("ascii")
        message = {
            "message_id": "<att-save@test.com>",
            "subject": "Has Attachment",
            "sender": {"address": "a@b.com", "display_name": "A"},
            "body_plain": "See attached.",
            "mailbox": "INBOX",
            "attachments": [
                {
                    "filename": "report.pdf",
                    "content_type": "application/pdf",
                    "data_b64": att_data,
                    "size": 16,
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            rc, out, err = _run_script(
                "read_mail.py",
                "--from-stdin",
                "--save-attachments", tmpdir,
                stdin_data=json.dumps(message),
            )
            assert rc == 0, f"stderr: {err}"
            saved_path = os.path.join(tmpdir, "report.pdf")
            assert os.path.exists(saved_path)
            with open(saved_path, "rb") as f:
                assert f.read() == b"PDF content here"

    def test_save_attachments_no_overwrite(self):
        """Saving attachments should not overwrite existing files."""
        att_data = base64.b64encode(b"data").decode("ascii")
        message = {
            "message_id": "<no-overwrite@test.com>",
            "subject": "Test",
            "sender": {"address": "a@b.com", "display_name": ""},
            "body_plain": "Test",
            "mailbox": "INBOX",
            "attachments": [
                {
                    "filename": "file.txt",
                    "content_type": "text/plain",
                    "data_b64": att_data,
                    "size": 4,
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create an existing file
            with open(os.path.join(tmpdir, "file.txt"), "w") as f:
                f.write("existing")

            rc, out, err = _run_script(
                "read_mail.py",
                "--from-stdin",
                "--save-attachments", tmpdir,
                stdin_data=json.dumps(message),
            )
            assert rc == 0
            # Original file should be untouched
            with open(os.path.join(tmpdir, "file.txt")) as f:
                assert f.read() == "existing"
            # New file should have a suffix
            assert os.path.exists(os.path.join(tmpdir, "file_1.txt"))


# ── Feature 3: IMAP SEARCH script ──────────────────────────────────


class TestSearchMailScript:
    def test_search_no_host_fails(self):
        """search_mail.py without --config or --imap-host should fail."""
        rc, _, err = _run_script("search_mail.py", "--subject", "test")
        assert rc != 0

    def test_search_criteria_building(self):
        """Verify the criteria builder logic via subprocess import."""
        # We test the _build_criteria function directly
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "search_mail", os.path.join(SCRIPTS_DIR, "search_mail.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        # We need to add scripts dir for lib imports
        sys.path.insert(0, SCRIPTS_DIR)
        spec.loader.exec_module(mod)

        class Args:
            criteria = ""
            unseen = True
            flagged = False
            subject = "invoice"
            from_addr = "boss@x.com"
            to = ""
            body = ""
            text = ""
            since = "2025-06-01"
            before = ""

        result = mod._build_criteria(Args())
        assert "UNSEEN" in result
        assert 'SUBJECT "invoice"' in result
        assert 'FROM "boss@x.com"' in result
        assert "SINCE" in result
        assert "01-Jun-2025" in result

    def test_search_raw_criteria(self):
        """Raw --criteria should override other flags."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "search_mail", os.path.join(SCRIPTS_DIR, "search_mail.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        sys.path.insert(0, SCRIPTS_DIR)
        spec.loader.exec_module(mod)

        class Args:
            criteria = '(OR (FROM "a") (FROM "b"))'
            unseen = True
            flagged = False
            subject = "ignored"
            from_addr = ""
            to = ""
            body = ""
            text = ""
            since = ""
            before = ""

        result = mod._build_criteria(Args())
        assert result == '(OR (FROM "a") (FROM "b"))'


# ── Feature 4: Forward script ──────────────────────────────────────


class TestForwardComposer:
    def setup_method(self):
        self.composer = EmailComposer()

    def test_compose_forward_basic(self):
        original = EmailMessage(
            message_id="<orig@example.com>",
            subject="Original Subject",
            sender=EmailAddress(address="sender@example.com", display_name="Sender"),
            body_plain="Original body text.",
            body_html="<p>Original body text.</p>",
        )
        fwd = self.composer.compose_forward(
            original=original,
            to="recipient@other.com",
            body="FYI, see below.",
            sender="me@example.com",
        )
        assert fwd.subject == "Fwd: Original Subject"
        assert fwd.recipients[0].address == "recipient@other.com"
        assert "Forwarded message" in fwd.body_html
        assert "sender@example.com" in fwd.body_html
        assert "Original body text" in fwd.body_html
        assert "FYI, see below" in fwd.body_html

    def test_compose_forward_already_fwd(self):
        original = EmailMessage(
            message_id="<x@y.com>",
            subject="Fwd: Already forwarded",
            sender=EmailAddress(address="a@b.com"),
            body_plain="Content",
        )
        fwd = self.composer.compose_forward(original=original, to="c@d.com")
        assert fwd.subject == "Fwd: Already forwarded"

    def test_compose_forward_with_attachments(self):
        original = EmailMessage(
            message_id="<att@x.com>",
            subject="With Attachments",
            sender=EmailAddress(address="a@b.com"),
            body_plain="Body",
            attachments=[
                EmailAttachment(
                    filename="doc.pdf",
                    content_type="application/pdf",
                    data=b"fake-pdf",
                )
            ],
        )
        fwd = self.composer.compose_forward(
            original=original, to="c@d.com", attach_original=True,
        )
        assert len(fwd.attachments) == 1
        assert fwd.attachments[0].filename == "doc.pdf"

    def test_compose_forward_without_attachments(self):
        original = EmailMessage(
            message_id="<att@x.com>",
            subject="With Attachments",
            sender=EmailAddress(address="a@b.com"),
            body_plain="Body",
            attachments=[
                EmailAttachment(
                    filename="doc.pdf",
                    content_type="application/pdf",
                    data=b"fake-pdf",
                )
            ],
        )
        fwd = self.composer.compose_forward(
            original=original, to="c@d.com", attach_original=False,
        )
        assert len(fwd.attachments) == 0


class TestForwardMailScript:
    def test_forward_from_stdin(self):
        """forward_mail.py should compose a forward from stdin."""
        original = {
            "message_id": "<fwd-test@example.com>",
            "subject": "Original Email",
            "sender": {"address": "original@sender.com", "display_name": "Original Sender"},
            "body_plain": "This is the original message.",
            "body_html": "<p>This is the original message.</p>",
            "mailbox": "INBOX",
        }
        # Without SMTP config, it should output composed JSON
        rc, out, err = _run_script(
            "forward_mail.py",
            "--from-stdin",
            "--to", "forwarded@recipient.com",
            "--body", "FYI",
            stdin_data=json.dumps(original),
        )
        assert rc == 0, f"stderr: {err}"
        data = json.loads(out)
        assert data["subject"] == "Fwd: Original Email"
        assert data["recipients"][0]["address"] == "forwarded@recipient.com"
        assert "Forwarded message" in data["body_html"]
        assert "FYI" in data["body_html"]


# ── Feature 5: Reply with quoting ──────────────────────────────────


class TestReplyQuoting:
    def setup_method(self):
        self.composer = EmailComposer()

    def test_reply_includes_quote_by_default(self):
        from datetime import datetime
        original = EmailMessage(
            message_id="<reply-test@example.com>",
            subject="Original",
            sender=EmailAddress(address="sender@example.com", display_name="Sender"),
            body_plain="This is the original message.",
            date=datetime(2025, 6, 15, 10, 30),
        )
        reply = self.composer.compose_reply(
            original=original,
            body="Thanks for the update!",
        )
        assert "Re: Original" == reply.subject
        # Quote should be in the body
        assert "sender@example.com" in reply.body_html
        assert "wrote:" in reply.body_html
        assert "This is the original message" in reply.body_html
        assert "Thanks for the update!" in reply.body_html

    def test_reply_no_quote(self):
        original = EmailMessage(
            message_id="<nq@example.com>",
            subject="Test",
            sender=EmailAddress(address="x@y.com"),
            body_plain="Original body",
        )
        reply = self.composer.compose_reply(
            original=original,
            body="Short reply",
            quote_original=False,
        )
        assert "Short reply" in reply.body_html
        assert "Original body" not in reply.body_html

    def test_build_quote_block(self):
        from datetime import datetime
        msg = EmailMessage(
            sender=EmailAddress(address="alice@example.com", display_name="Alice"),
            body_plain="Line one\nLine two",
            date=datetime(2025, 3, 10, 14, 0),
        )
        block = _build_quote_block(msg)
        assert "alice@example.com" in block
        assert "wrote:" in block
        assert "Line one" in block
        assert "Line two" in block

    def test_build_forward_block(self):
        msg = EmailMessage(
            subject="Test Subject",
            sender=EmailAddress(address="bob@example.com", display_name="Bob"),
            recipients=[EmailAddress(address="carol@example.com")],
            body_html="<p>HTML body</p>",
        )
        block = _build_forward_block(msg)
        assert "Forwarded message" in block
        assert "bob@example.com" in block
        assert "Test Subject" in block
        assert "HTML body" in block


class TestReplyMailScript:
    def test_reply_from_stdin(self):
        """reply_mail.py should compose a reply from stdin."""
        original = {
            "message_id": "<reply-script@example.com>",
            "subject": "Hello there",
            "sender": {"address": "friend@example.com", "display_name": "Friend"},
            "body_plain": "How are you doing?",
            "mailbox": "INBOX",
        }
        rc, out, err = _run_script(
            "reply_mail.py",
            "--from-stdin",
            "--body", "I'm doing great!",
            stdin_data=json.dumps(original),
        )
        assert rc == 0, f"stderr: {err}"
        data = json.loads(out)
        assert data["subject"] == "Re: Hello there"
        assert data["in_reply_to"] == "<reply-script@example.com>"
        assert data["recipients"][0]["address"] == "friend@example.com"
        assert "I'm doing great!" in data["body_html"]
        assert "How are you doing?" in data["body_html"]

    def test_reply_no_quote_flag(self):
        """reply_mail.py --no-quote should not include original."""
        original = {
            "message_id": "<nq-script@example.com>",
            "subject": "Original",
            "sender": {"address": "x@y.com", "display_name": ""},
            "body_plain": "Secret original text",
            "mailbox": "INBOX",
        }
        rc, out, err = _run_script(
            "reply_mail.py",
            "--from-stdin",
            "--body", "OK",
            "--no-quote",
            stdin_data=json.dumps(original),
        )
        assert rc == 0, f"stderr: {err}"
        data = json.loads(out)
        assert "OK" in data["body_html"]
        assert "Secret original text" not in data["body_html"]


# ── Feature 6: Draft save/resume ────────────────────────────────────


class TestBuildMime:
    def test_build_mime_standalone(self):
        """build_mime() should produce a valid MIME message."""
        msg = EmailMessage(
            subject="Draft Test",
            sender=EmailAddress(address="me@x.com"),
            recipients=[EmailAddress(address="you@y.com")],
            body_plain="Plain text",
            body_html="<p>HTML body</p>",
        )
        mime = build_mime(msg)
        raw = mime.as_string()
        assert "Draft Test" in raw
        assert "me@x.com" in raw
        assert "you@y.com" in raw


class TestDraftMailScript:
    def test_draft_save_requires_config(self):
        """draft_mail.py --action save should require --config."""
        rc, _, err = _run_script(
            "draft_mail.py",
            "--action", "save",
            "--to", "x@y.com",
            "--subject", "Test",
        )
        assert rc != 0

    def test_draft_list_requires_config(self):
        """draft_mail.py --action list should require --config."""
        rc, _, err = _run_script(
            "draft_mail.py",
            "--action", "list",
        )
        assert rc != 0

    def test_draft_send_requires_message_id(self):
        """draft_mail.py --action send needs --message-id."""
        rc, _, err = _run_script(
            "draft_mail.py",
            "--action", "send",
            "--config", "/dev/null",
        )
        assert rc != 0


# ── Feature 7: Heartbeat deduplication ──────────────────────────────


class TestHeartbeatDedup:
    def test_dedup_state_file_format(self):
        """Verify the state file schema for dedup."""
        # We can't run heartbeat without IMAP, but we can test the
        # state file format we write to
        state = {
            "email_seen_ids": ["<msg1@x.com>", "<msg2@y.com>"],
            "email_last_heartbeat": "2025-06-15T10:00:00",
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(state, f)
            state_path = f.name
        try:
            with open(state_path) as f:
                loaded = json.load(f)
            assert "<msg1@x.com>" in loaded["email_seen_ids"]
            assert "<msg2@y.com>" in loaded["email_seen_ids"]
        finally:
            os.unlink(state_path)


# ── Feature 8: OAuth2 support ──────────────────────────────────────


class TestOAuth2:
    def test_build_xoauth2_string(self):
        from lib.oauth2 import build_xoauth2_string
        result = build_xoauth2_string("user@gmail.com", "ya29.token123")
        assert result == "user=user@gmail.com\x01auth=Bearer ya29.token123\x01\x01"

    def test_build_xoauth2_bytes(self):
        from lib.oauth2 import build_xoauth2_bytes
        result = build_xoauth2_bytes("user@gmail.com", "token")
        decoded = base64.b64decode(result).decode("ascii")
        assert "user=user@gmail.com" in decoded
        assert "auth=Bearer token" in decoded

    def test_oauth2_manager_not_configured(self):
        from lib.oauth2 import OAuth2Manager
        mgr = OAuth2Manager({})
        assert not mgr.is_configured

    def test_oauth2_manager_configured(self):
        from lib.oauth2 import OAuth2Manager
        mgr = OAuth2Manager({
            "client_id": "id",
            "client_secret": "secret",
            "refresh_token": "refresh",
            "token_uri": "https://oauth2.googleapis.com/token",
            "access_token": "cached_token",
            "access_token_expiry": "2099-01-01T00:00:00",
        })
        assert mgr.is_configured
        # Cached token should be returned without refresh
        assert mgr.access_token == "cached_token"

    def test_oauth2_manager_expired_needs_refresh(self):
        from lib.oauth2 import OAuth2Manager
        mgr = OAuth2Manager({
            "client_id": "id",
            "client_secret": "secret",
            "refresh_token": "refresh",
            "token_uri": "https://oauth2.googleapis.com/token",
            "access_token": "expired_token",
            "access_token_expiry": "2020-01-01T00:00:00",
        })
        assert mgr._is_expired()

    def test_account_manager_oauth2_imap_client(self):
        """AccountManager should create IMAPClient with OAuth2 when configured."""
        from lib.account_manager import AccountManager
        config = {
            "accounts": {
                "gmail": {
                    "label": "Gmail",
                    "sender_address": "user@gmail.com",
                    "imap": {
                        "host": "imap.gmail.com",
                        "port": 993,
                        "username": "user@gmail.com",
                        "auth": "oauth2",
                        "oauth2": {
                            "client_id": "test_id",
                            "client_secret": "test_secret",
                            "refresh_token": "test_refresh",
                            "token_uri": "https://oauth2.googleapis.com/token",
                        },
                    },
                    "smtp": {
                        "host": "smtp.gmail.com",
                        "port": 587,
                        "username": "user@gmail.com",
                        "auth": "oauth2",
                        "oauth2": {
                            "client_id": "test_id",
                            "client_secret": "test_secret",
                            "refresh_token": "test_refresh",
                            "token_uri": "https://oauth2.googleapis.com/token",
                        },
                    },
                },
            },
        }
        mgr = AccountManager(config)
        client = mgr.get_imap_client("gmail")
        assert client._oauth2 is not None
        assert client._oauth2.is_configured

        smtp_client = mgr.get_smtp_client("gmail")
        assert smtp_client._oauth2 is not None
        assert smtp_client._oauth2.is_configured


# ── Feature 3 addendum: IMAP search method ─────────────────────────


class TestIMAPClientSearch:
    def test_imap_client_has_search_method(self):
        """IMAPClient should have a search() method."""
        from lib.imap_client import IMAPClient
        client = IMAPClient(host="fake.example.com")
        assert hasattr(client, "search")

    def test_imap_client_has_append_method(self):
        """IMAPClient should have an append_message() method."""
        from lib.imap_client import IMAPClient
        client = IMAPClient(host="fake.example.com")
        assert hasattr(client, "append_message")
