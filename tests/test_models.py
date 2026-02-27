"""Tests for email data models."""

import json
import sys
import os

# Add the skill scripts to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "claw-mail", "scripts"))

from lib.models import (
    EmailAddress,
    EmailAttachment,
    EmailMessage,
    EmailPriority,
)


class TestEmailAddress:
    def test_plain_address(self):
        addr = EmailAddress(address="test@example.com")
        assert str(addr) == "test@example.com"

    def test_address_with_name(self):
        addr = EmailAddress(address="test@example.com", display_name="Test User")
        assert str(addr) == "Test User <test@example.com>"

    def test_parse_plain(self):
        addr = EmailAddress.parse("test@example.com")
        assert addr.address == "test@example.com"
        assert addr.display_name == ""

    def test_parse_with_name(self):
        addr = EmailAddress.parse("Test User <test@example.com>")
        assert addr.address == "test@example.com"
        assert addr.display_name == "Test User"

    def test_parse_quoted_name(self):
        addr = EmailAddress.parse('"John Doe" <john@example.com>')
        assert addr.address == "john@example.com"
        assert addr.display_name == "John Doe"

    def test_parse_strips_whitespace(self):
        addr = EmailAddress.parse("  user@example.com  ")
        assert addr.address == "user@example.com"

    def test_to_dict_round_trip(self):
        addr = EmailAddress(address="a@b.com", display_name="Alice")
        d = addr.to_dict()
        restored = EmailAddress.from_dict(d)
        assert restored.address == addr.address
        assert restored.display_name == addr.display_name


class TestEmailAttachment:
    def test_auto_size(self):
        data = b"hello world"
        att = EmailAttachment(filename="test.txt", content_type="text/plain", data=data)
        assert att.size == len(data)

    def test_explicit_size(self):
        att = EmailAttachment(
            filename="test.txt", content_type="text/plain", data=b"hi", size=999
        )
        assert att.size == 999

    def test_to_dict_round_trip(self):
        att = EmailAttachment(filename="f.bin", content_type="application/octet-stream", data=b"\x00\x01\x02")
        d = att.to_dict()
        restored = EmailAttachment.from_dict(d)
        assert restored.filename == att.filename
        assert restored.data == att.data


class TestEmailMessage:
    def test_defaults(self):
        msg = EmailMessage()
        assert msg.subject == ""
        assert msg.recipients == []
        assert msg.priority == EmailPriority.NORMAL
        assert not msg.has_attachments
        assert msg.body == ""

    def test_body_prefers_html(self):
        msg = EmailMessage(body_plain="plain", body_html="<b>html</b>")
        assert msg.body == "<b>html</b>"

    def test_body_falls_back_to_plain(self):
        msg = EmailMessage(body_plain="plain text")
        assert msg.body == "plain text"

    def test_has_attachments(self):
        msg = EmailMessage(
            attachments=[
                EmailAttachment(filename="f.txt", content_type="text/plain", data=b"x")
            ]
        )
        assert msg.has_attachments

    def test_recipient_addresses(self):
        msg = EmailMessage(
            recipients=[
                EmailAddress(address="a@b.com"),
                EmailAddress(address="c@d.com", display_name="C"),
            ]
        )
        assert msg.recipient_addresses == ["a@b.com", "c@d.com"]

    def test_to_dict_round_trip(self):
        msg = EmailMessage(
            subject="Test",
            sender=EmailAddress(address="sender@x.com", display_name="Sender"),
            recipients=[EmailAddress(address="r@x.com")],
            body_plain="Hello",
            body_html="<p>Hello</p>",
            message_id="<test@x.com>",
        )
        d = msg.to_dict()
        restored = EmailMessage.from_dict(d)
        assert restored.subject == msg.subject
        assert restored.sender.address == msg.sender.address
        assert restored.body_html == msg.body_html
        assert restored.message_id == msg.message_id

    def test_account_field(self):
        msg = EmailMessage(subject="Test", account="work")
        assert msg.account == "work"
        d = msg.to_dict()
        assert d["account"] == "work"
        restored = EmailMessage.from_dict(d)
        assert restored.account == "work"

    def test_account_defaults_empty(self):
        msg = EmailMessage()
        assert msg.account == ""

    def test_json_serializable(self):
        msg = EmailMessage(subject="JSON Test", body_plain="test")
        s = json.dumps(msg.to_dict(), default=str)
        assert "JSON Test" in s
