"""Tests for the email processing pipeline."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "claw-mail", "scripts"))

from lib.models import EmailAddress, EmailAttachment, EmailMessage
from lib.processor import EmailProcessor, ProcessingRule, RuleAction


def _make_message(**kwargs) -> EmailMessage:
    defaults = {
        "subject": "Test Subject",
        "sender": EmailAddress(address="sender@example.com", display_name="Sender"),
        "body_plain": "Test body content",
        "mailbox": "INBOX",
    }
    defaults.update(kwargs)
    return EmailMessage(**defaults)


class TestProcessingRule:
    def test_matches_sender(self):
        rule = ProcessingRule(name="test", actions=[], sender_pattern="sender@example")
        assert rule.matches(_make_message())

    def test_no_match_sender(self):
        rule = ProcessingRule(name="test", actions=[], sender_pattern="other@example")
        assert not rule.matches(_make_message())

    def test_matches_subject_regex(self):
        rule = ProcessingRule(name="test", actions=[], subject_pattern="test|urgent")
        assert rule.matches(_make_message(subject="This is urgent"))

    def test_matches_body(self):
        rule = ProcessingRule(name="test", actions=[], body_pattern="body content")
        assert rule.matches(_make_message())

    def test_matches_mailbox(self):
        rule = ProcessingRule(name="test", actions=[], mailbox="INBOX")
        assert rule.matches(_make_message())
        assert not rule.matches(_make_message(mailbox="Sent"))

    def test_matches_has_attachments(self):
        rule = ProcessingRule(name="test", actions=[], has_attachments=True)
        assert not rule.matches(_make_message())
        msg_with_att = _make_message(
            attachments=[EmailAttachment(filename="f.txt", content_type="text/plain", data=b"x")]
        )
        assert rule.matches(msg_with_att)

    def test_all_criteria_must_match(self):
        rule = ProcessingRule(
            name="test", actions=[],
            sender_pattern="sender@example", subject_pattern="nomatch",
        )
        assert not rule.matches(_make_message())


class TestEmailProcessor:
    def test_no_rules_no_actions(self):
        processor = EmailProcessor()
        result = processor.process(_make_message())
        assert result.matched_rules == []
        assert result.actions_taken == []

    def test_flag_action(self):
        processor = EmailProcessor()
        processor.add_rule(ProcessingRule(
            name="flag_it", actions=[RuleAction.FLAG],
            sender_pattern="sender", flag_index=2,
        ))
        result = processor.process(_make_message())
        assert "flag_it" in result.matched_rules
        assert result.should_flag
        assert result.flag_index == 2

    def test_tag_action(self):
        processor = EmailProcessor()
        processor.add_rule(ProcessingRule(
            name="tag_it", actions=[RuleAction.TAG],
            subject_pattern="Test", tag="important",
        ))
        result = processor.process(_make_message())
        assert "important" in result.tags

    def test_mark_read_action(self):
        processor = EmailProcessor()
        processor.add_rule(ProcessingRule(
            name="read_it", actions=[RuleAction.MARK_READ], sender_pattern=".*",
        ))
        result = processor.process(_make_message())
        assert result.should_mark_read

    def test_forward_action(self):
        processor = EmailProcessor()
        processor.add_rule(ProcessingRule(
            name="fwd", actions=[RuleAction.FORWARD],
            sender_pattern=".*", forward_to="archive@example.com",
        ))
        result = processor.process(_make_message())
        assert "archive@example.com" in result.forward_to

    def test_move_action(self):
        processor = EmailProcessor()
        processor.add_rule(ProcessingRule(
            name="sort_invoices", actions=[RuleAction.MOVE],
            subject_pattern="invoice", move_to="Finances",
        ))
        result = processor.process(_make_message(subject="Your invoice #1234"))
        assert "sort_invoices" in result.matched_rules
        assert result.move_to == "Finances"

    def test_move_action_no_destination(self):
        processor = EmailProcessor()
        processor.add_rule(ProcessingRule(
            name="bad_move", actions=[RuleAction.MOVE],
            sender_pattern=".*",
            # move_to not set — should not set result.move_to
        ))
        result = processor.process(_make_message())
        assert result.move_to == ""

    def test_move_combined_with_other_actions(self):
        processor = EmailProcessor()
        processor.add_rule(ProcessingRule(
            name="sort_and_tag", actions=[RuleAction.MOVE, RuleAction.TAG, RuleAction.MARK_READ],
            subject_pattern="receipt", move_to="Finances", tag="receipt",
        ))
        result = processor.process(_make_message(subject="Your receipt"))
        assert result.move_to == "Finances"
        assert "receipt" in result.tags
        assert result.should_mark_read

    def test_auto_reply_action(self):
        processor = EmailProcessor()
        processor.add_rule(ProcessingRule(
            name="reply", actions=[RuleAction.AUTO_REPLY],
            sender_pattern=".*", reply_template="Thanks for your email!",
        ))
        result = processor.process(_make_message())
        assert result.reply_body == "Thanks for your email!"

    def test_stop_after_match(self):
        processor = EmailProcessor()
        processor.add_rule(ProcessingRule(
            name="first", actions=[RuleAction.TAG], sender_pattern=".*",
            tag="first", priority=10, stop_after_match=True,
        ))
        processor.add_rule(ProcessingRule(
            name="second", actions=[RuleAction.TAG], sender_pattern=".*",
            tag="second", priority=5,
        ))
        result = processor.process(_make_message())
        assert "first" in result.matched_rules
        assert "second" not in result.matched_rules

    def test_priority_ordering(self):
        processor = EmailProcessor()
        processor.add_rule(ProcessingRule(
            name="low", actions=[RuleAction.TAG], sender_pattern=".*",
            tag="low", priority=1,
        ))
        processor.add_rule(ProcessingRule(
            name="high", actions=[RuleAction.TAG], sender_pattern=".*",
            tag="high", priority=10,
        ))
        result = processor.process(_make_message())
        assert result.matched_rules[0] == "high"

    def test_callback_action(self):
        captured = []
        def on_match(msg):
            captured.append(msg.subject)

        processor = EmailProcessor()
        processor.add_rule(ProcessingRule(
            name="cb", actions=[RuleAction.CALLBACK],
            sender_pattern=".*", callback=on_match,
        ))
        processor.process(_make_message(subject="Captured!"))
        assert captured == ["Captured!"]

    def test_batch_processing(self):
        processor = EmailProcessor()
        processor.add_rule(ProcessingRule(
            name="tag_all", actions=[RuleAction.TAG],
            sender_pattern=".*", tag="processed",
        ))
        messages = [_make_message(subject=f"Msg {i}") for i in range(3)]
        results = processor.process_batch(messages)
        assert len(results) == 3
        assert all("processed" in r.tags for r in results)

    def test_from_config(self):
        config = [{
            "name": "config_rule",
            "sender_pattern": "test",
            "actions": ["flag", "tag"],
            "tag": "from_config",
            "flag_index": 3,
            "priority": 5,
        }]
        processor = EmailProcessor.from_config(config)
        assert len(processor.rules) == 1
        assert processor.rules[0].name == "config_rule"

    def test_from_config_with_move(self):
        config = [{
            "name": "move_rule",
            "subject_pattern": "invoice",
            "actions": ["move", "tag"],
            "move_to": "Finances",
            "tag": "invoice",
            "priority": 8,
        }]
        processor = EmailProcessor.from_config(config)
        assert processor.rules[0].move_to == "Finances"
        result = processor.process(_make_message(subject="Your invoice"))
        assert result.move_to == "Finances"
        assert "invoice" in result.tags

    def test_account_filter(self):
        processor = EmailProcessor()
        processor.add_rule(ProcessingRule(
            name="work_only", actions=[RuleAction.TAG],
            sender_pattern=".*", account="work", tag="work_tag",
        ))
        work_msg = _make_message(account="work")
        personal_msg = _make_message(account="personal")
        assert "work_only" in processor.process(work_msg).matched_rules
        assert "work_only" not in processor.process(personal_msg).matched_rules

    def test_account_filter_empty_matches_all(self):
        processor = EmailProcessor()
        processor.add_rule(ProcessingRule(
            name="global", actions=[RuleAction.TAG],
            sender_pattern=".*", tag="all",
        ))
        result = processor.process(_make_message(account="anything"))
        assert "global" in result.matched_rules

    def test_from_config_with_account(self):
        config = [{
            "name": "acct_rule",
            "sender_pattern": ".*",
            "account": "work",
            "actions": ["tag"],
            "tag": "work",
        }]
        processor = EmailProcessor.from_config(config)
        assert processor.rules[0].account == "work"

    def test_result_to_dict_includes_account(self):
        processor = EmailProcessor()
        processor.add_rule(ProcessingRule(
            name="t", actions=[RuleAction.TAG], sender_pattern=".*", tag="x",
        ))
        result = processor.process(_make_message(account="work"))
        d = result.to_dict()
        assert d["account"] == "work"

    def test_result_to_dict(self):
        processor = EmailProcessor()
        processor.add_rule(ProcessingRule(
            name="t", actions=[RuleAction.TAG], sender_pattern=".*", tag="x",
        ))
        result = processor.process(_make_message())
        d = result.to_dict()
        assert d["matched_rules"] == ["t"]
        assert "x" in d["tags"]
