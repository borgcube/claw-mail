"""Tests for the AccountManager multi-account registry."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "claw-mail", "scripts"))

import pytest
from lib.account_manager import AccountManager
from lib.models import EmailAddress, EmailMessage


def _multi_config():
    return {
        "default_account": "work",
        "smtp_fallback": {
            "host": "relay.example.com",
            "port": 587,
            "username": "relay",
            "password": "pass",
            "tls": True,
        },
        "accounts": {
            "work": {
                "label": "Work",
                "sender_address": "alice@company.com",
                "sender_name": "Alice Smith",
                "imap": {
                    "host": "imap.company.com",
                    "port": 993,
                    "username": "alice@company.com",
                    "password": "work-pass",
                    "ssl": True,
                },
                "smtp": {
                    "host": "smtp.company.com",
                    "port": 587,
                    "username": "alice@company.com",
                    "password": "work-pass",
                    "tls": True,
                },
                "mailboxes": ["INBOX", "Projects"],
                "fetch_limit": 50,
                "rules": [
                    {
                        "name": "flag_urgent",
                        "sender_pattern": "boss@",
                        "actions": ["flag"],
                        "priority": 10,
                    }
                ],
            },
            "personal": {
                "label": "Personal",
                "sender_address": "alice@gmail.com",
                "imap": {
                    "host": "imap.gmail.com",
                    "port": 993,
                    "username": "alice@gmail.com",
                    "password": "gmail-pass",
                    "ssl": True,
                },
                "smtp": {
                    "host": "smtp.gmail.com",
                    "port": 587,
                    "username": "alice@gmail.com",
                    "password": "gmail-pass",
                    "tls": True,
                },
                "mailboxes": ["INBOX"],
                "fetch_limit": 25,
                "rules": [],
            },
        },
        "rules": [
            {
                "name": "global_spam",
                "subject_pattern": "buy now",
                "actions": ["move"],
                "move_to": "Junk",
                "priority": 100,
            }
        ],
        "defaults": {
            "fetch_limit": 50,
        },
    }


def _legacy_config():
    """Flat single-account config (pre-multi-account format)."""
    return {
        "imap": {
            "host": "imap.example.com",
            "port": 993,
            "username": "user@example.com",
            "password": "pass",
            "ssl": True,
        },
        "smtp": {
            "host": "smtp.example.com",
            "port": 587,
            "username": "user@example.com",
            "password": "pass",
            "tls": True,
        },
        "mailboxes": ["INBOX"],
        "fetch_limit": 30,
        "sender_address": "user@example.com",
        "rules": [
            {"name": "r1", "sender_pattern": ".*", "actions": ["tag"], "tag": "all"},
        ],
    }


class TestAccountManagerInit:
    def test_list_accounts(self):
        mgr = AccountManager(_multi_config())
        assert sorted(mgr.list_accounts()) == ["personal", "work"]

    def test_default_account(self):
        mgr = AccountManager(_multi_config())
        assert mgr.default_account == "work"

    def test_auto_default_when_not_set(self):
        cfg = _multi_config()
        del cfg["default_account"]
        mgr = AccountManager(cfg)
        assert mgr.default_account in mgr.list_accounts()

    def test_get_account(self):
        mgr = AccountManager(_multi_config())
        acct = mgr.get_account("personal")
        assert acct["label"] == "Personal"

    def test_get_account_default(self):
        mgr = AccountManager(_multi_config())
        acct = mgr.get_account()
        assert acct["label"] == "Work"

    def test_get_account_unknown_raises(self):
        mgr = AccountManager(_multi_config())
        with pytest.raises(KeyError):
            mgr.get_account("nonexistent")


class TestAccountManagerLegacy:
    def test_legacy_config_creates_default_account(self):
        mgr = AccountManager(_legacy_config())
        assert mgr.list_accounts() == ["default"]
        assert mgr.default_account == "default"

    def test_legacy_config_imap(self):
        mgr = AccountManager(_legacy_config())
        acct = mgr.get_account("default")
        assert acct["imap"]["host"] == "imap.example.com"

    def test_legacy_config_smtp(self):
        mgr = AccountManager(_legacy_config())
        acct = mgr.get_account("default")
        assert acct["smtp"]["host"] == "smtp.example.com"

    def test_legacy_config_fetch_limit(self):
        mgr = AccountManager(_legacy_config())
        assert mgr.get_fetch_limit("default") == 30

    def test_legacy_config_sender(self):
        mgr = AccountManager(_legacy_config())
        sender = mgr.get_sender("default")
        assert sender.address == "user@example.com"


class TestAccountManagerProperties:
    def test_get_label(self):
        mgr = AccountManager(_multi_config())
        assert mgr.get_label("work") == "Work"
        assert mgr.get_label("personal") == "Personal"

    def test_get_sender(self):
        mgr = AccountManager(_multi_config())
        sender = mgr.get_sender("work")
        assert isinstance(sender, EmailAddress)
        assert sender.address == "alice@company.com"
        assert sender.display_name == "Alice Smith"

    def test_get_sender_default(self):
        mgr = AccountManager(_multi_config())
        sender = mgr.get_sender()
        assert sender.address == "alice@company.com"

    def test_get_sender_falls_back_to_imap_user(self):
        cfg = _multi_config()
        del cfg["accounts"]["personal"]["sender_address"]
        mgr = AccountManager(cfg)
        sender = mgr.get_sender("personal")
        assert sender.address == "alice@gmail.com"

    def test_get_mailboxes(self):
        mgr = AccountManager(_multi_config())
        assert mgr.get_mailboxes("work") == ["INBOX", "Projects"]
        assert mgr.get_mailboxes("personal") == ["INBOX"]

    def test_get_fetch_limit(self):
        mgr = AccountManager(_multi_config())
        assert mgr.get_fetch_limit("work") == 50
        assert mgr.get_fetch_limit("personal") == 25


class TestAccountManagerRules:
    def test_get_rules_per_account_plus_global(self):
        mgr = AccountManager(_multi_config())
        rules = mgr.get_rules("work")
        rule_names = [r["name"] for r in rules]
        assert "flag_urgent" in rule_names  # per-account
        assert "global_spam" in rule_names  # global
        assert len(rules) == 2

    def test_get_rules_only_global_for_empty_account(self):
        mgr = AccountManager(_multi_config())
        rules = mgr.get_rules("personal")
        assert len(rules) == 1
        assert rules[0]["name"] == "global_spam"


class TestAccountManagerClients:
    def test_get_imap_client(self):
        mgr = AccountManager(_multi_config())
        client = mgr.get_imap_client("work")
        assert client.host == "imap.company.com"
        assert client.username == "alice@company.com"
        assert client._account == "work"

    def test_get_imap_client_default(self):
        mgr = AccountManager(_multi_config())
        client = mgr.get_imap_client()
        assert client.host == "imap.company.com"

    def test_get_smtp_client(self):
        mgr = AccountManager(_multi_config())
        client = mgr.get_smtp_client("personal")
        assert client.host == "smtp.gmail.com"
        assert client.username == "alice@gmail.com"

    def test_get_imap_client_no_host_raises(self):
        cfg = _multi_config()
        cfg["accounts"]["work"]["imap"]["host"] = ""
        mgr = AccountManager(cfg)
        with pytest.raises(ValueError):
            mgr.get_imap_client("work")

    def test_get_smtp_client_no_host_raises(self):
        cfg = _multi_config()
        cfg["accounts"]["work"]["smtp"]["host"] = ""
        mgr = AccountManager(cfg)
        with pytest.raises(ValueError):
            mgr.get_smtp_client("work")


class TestAccountManagerResolve:
    def test_resolve_by_account_field(self):
        mgr = AccountManager(_multi_config())
        msg = EmailMessage(account="personal")
        assert mgr.resolve_account_for_message(msg) == "personal"

    def test_resolve_by_sender(self):
        mgr = AccountManager(_multi_config())
        msg = EmailMessage(
            sender=EmailAddress(address="alice@gmail.com"),
        )
        assert mgr.resolve_account_for_message(msg) == "personal"

    def test_resolve_falls_back_to_default(self):
        mgr = AccountManager(_multi_config())
        msg = EmailMessage(
            sender=EmailAddress(address="unknown@other.com"),
        )
        assert mgr.resolve_account_for_message(msg) == "work"
