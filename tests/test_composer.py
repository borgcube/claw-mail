"""Tests for the email composer."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "claw-mail", "scripts"))

from lib.composer import EmailComposer
from lib.models import EmailAddress, EmailMessage


class TestEmailComposer:
    def setup_method(self):
        self.composer = EmailComposer()

    def test_compose_basic(self):
        msg = self.composer.compose(
            to="user@example.com",
            subject="Hello",
            body="This is a test.",
        )
        assert isinstance(msg, EmailMessage)
        assert msg.subject == "Hello"
        assert len(msg.recipients) == 1
        assert msg.recipients[0].address == "user@example.com"
        assert "This is a test." in msg.body_html
        assert msg.body_plain

    def test_compose_multiple_recipients(self):
        msg = self.composer.compose(
            to=["a@b.com", "c@d.com"],
            subject="Multi",
            body="Test",
        )
        assert len(msg.recipients) == 2

    def test_compose_with_cc_bcc(self):
        msg = self.composer.compose(
            to="a@b.com",
            subject="Test",
            body="Test",
            cc=["cc@b.com"],
            bcc="bcc@b.com",
        )
        assert len(msg.cc) == 1
        assert len(msg.bcc) == 1

    def test_compose_with_sender(self):
        msg = self.composer.compose(
            to="user@example.com",
            subject="Test",
            body="Test",
            sender="me@example.com",
        )
        assert msg.sender is not None
        assert msg.sender.address == "me@example.com"

    def test_compose_with_template_vars(self):
        msg = self.composer.compose(
            to="user@example.com",
            subject="Welcome",
            body="Welcome to OpenClaw!",
            greeting="Hi there,",
            sign_off="Best regards,\nThe Team",
            header_text="Welcome!",
            header_color="#4299e1",
            footer_text="You received this because you signed up.",
        )
        assert "Welcome!" in msg.body_html
        assert "Hi there" in msg.body_html

    def test_compose_minimal_template(self):
        msg = self.composer.compose(
            to="user@example.com",
            subject="Quick note",
            body="Just a quick message.",
            template="minimal",
        )
        assert "Just a quick message." in msg.body_html
        assert msg.body_html

    def test_compose_with_action_button(self):
        msg = self.composer.compose(
            to="user@example.com",
            subject="Action Required",
            body="Please review.",
            action_url="https://example.com/review",
            action_text="Review Now",
            action_color="#48bb78",
        )
        assert "https://example.com/review" in msg.body_html
        assert "Review Now" in msg.body_html

    def test_compose_reply(self):
        original = EmailMessage(
            message_id="<abc123@example.com>",
            subject="Original Subject",
            sender=EmailAddress(address="sender@example.com"),
        )
        reply = self.composer.compose_reply(
            original=original,
            body="Thanks for your message!",
            sender="me@example.com",
        )
        assert reply.subject == "Re: Original Subject"
        assert reply.in_reply_to == "<abc123@example.com>"
        assert "<abc123@example.com>" in reply.references
        assert reply.recipients[0].address == "sender@example.com"

    def test_compose_reply_already_re(self):
        original = EmailMessage(
            message_id="<x@y.com>",
            subject="Re: Already replied",
            sender=EmailAddress(address="sender@example.com"),
        )
        reply = self.composer.compose_reply(original=original, body="More reply")
        assert reply.subject == "Re: Already replied"

    def test_compose_digest(self):
        items = [
            {"Name": "Alice", "Score": "95"},
            {"Name": "Bob", "Score": "87"},
        ]
        msg = self.composer.compose_digest(
            to="admin@example.com",
            subject="Weekly Report",
            items=items,
            columns=["Name", "Score"],
            summary="Here are this week's results.",
        )
        assert "Alice" in msg.body_html
        assert "Bob" in msg.body_html
        assert "95" in msg.body_html
        assert "Weekly Report" in msg.body_html

    def test_compose_serializable(self):
        import json
        msg = self.composer.compose(
            to="x@y.com", subject="Serialize", body="Test",
        )
        d = msg.to_dict()
        s = json.dumps(d, default=str)
        restored = EmailMessage.from_dict(json.loads(s))
        assert restored.subject == "Serialize"
