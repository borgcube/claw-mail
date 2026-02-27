"""Integration tests for the CLI scripts."""

import json
import os
import subprocess
import sys

SCRIPTS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "skills", "claw-mail", "scripts"
)


def _run_script(name: str, *args: str, stdin_data: str = "") -> tuple[int, str, str]:
    """Run a skill script and return (returncode, stdout, stderr)."""
    cmd = [sys.executable, os.path.join(SCRIPTS_DIR, name)] + list(args)
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        input=stdin_data if stdin_data else None,
    )
    return result.returncode, result.stdout, result.stderr


class TestComposeMailScript:
    def test_compose_basic(self):
        rc, out, err = _run_script(
            "compose_mail.py",
            "--to", "user@example.com",
            "--subject", "Test Script",
            "--body", "<p>Hello from the script!</p>",
        )
        assert rc == 0, f"stderr: {err}"
        data = json.loads(out)
        assert data["subject"] == "Test Script"
        assert len(data["recipients"]) == 1
        assert data["recipients"][0]["address"] == "user@example.com"
        assert "<p>Hello from the script!</p>" in data["body_html"]
        assert data["body_plain"]

    def test_compose_with_template_vars(self):
        rc, out, _ = _run_script(
            "compose_mail.py",
            "--to", "a@b.com",
            "--subject", "Styled",
            "--body", "Content here",
            "--template", "default",
            "--greeting", "Hi!",
            "--sign-off", "Bye!",
            "--header-text", "My Header",
            "--footer-text", "Footer note",
        )
        assert rc == 0
        data = json.loads(out)
        assert "My Header" in data["body_html"]
        assert "Hi!" in data["body_html"]

    def test_compose_digest(self):
        rc, out, _ = _run_script(
            "compose_mail.py",
            "--to", "admin@x.com",
            "--subject", "Report",
            "--template", "digest",
            "--items", '[{"Name":"Alice","Score":"95"}]',
            "--columns", '["Name","Score"]',
            "--summary", "Results:",
        )
        assert rc == 0
        data = json.loads(out)
        assert "Alice" in data["body_html"]
        assert "95" in data["body_html"]

    def test_compose_no_to_fails(self):
        rc, _, err = _run_script(
            "compose_mail.py",
            "--subject", "No recipient",
        )
        assert rc != 0

    def test_compose_minimal_template(self):
        rc, out, _ = _run_script(
            "compose_mail.py",
            "--to", "x@y.com",
            "--subject", "Minimal",
            "--body", "Quick note",
            "--template", "minimal",
        )
        assert rc == 0
        data = json.loads(out)
        assert "Quick note" in data["body_html"]


class TestProcessMailScript:
    def test_process_with_inline_rules(self):
        messages = {
            "messages": [
                {
                    "subject": "Urgent task",
                    "sender": {"address": "boss@example.com", "display_name": "Boss"},
                    "body_plain": "Do this now",
                    "message_id": "<1@x.com>",
                    "mailbox": "INBOX",
                }
            ]
        }
        rules = json.dumps([
            {
                "name": "flag_urgent",
                "sender_pattern": "boss@",
                "subject_pattern": "urgent",
                "actions": ["flag", "tag"],
                "tag": "urgent",
                "priority": 10,
            }
        ])

        rc, out, err = _run_script(
            "process_mail.py",
            "--rules", rules,
            stdin_data=json.dumps(messages),
        )
        assert rc == 0, f"stderr: {err}"
        data = json.loads(out)
        assert data["messages_processed"] == 1
        assert data["rules_matched"] == 1
        result = data["results"][0]
        assert "flag_urgent" in result["matched_rules"]
        assert "urgent" in result["tags"]
        assert result["should_flag"] is True

    def test_process_no_rules_fails(self):
        messages = {"messages": [{"subject": "x", "message_id": "1"}]}
        rc, _, err = _run_script(
            "process_mail.py",
            stdin_data=json.dumps(messages),
        )
        assert rc != 0

    def test_process_with_move_action(self):
        messages = {
            "messages": [
                {
                    "subject": "Invoice #5678",
                    "sender": {"address": "billing@vendor.com", "display_name": "Vendor"},
                    "body_plain": "Please find attached invoice",
                    "message_id": "<inv@vendor.com>",
                    "mailbox": "INBOX",
                }
            ]
        }
        rules = json.dumps([
            {
                "name": "sort_invoices",
                "subject_pattern": "invoice",
                "actions": ["move", "tag"],
                "move_to": "Finances",
                "tag": "invoice",
                "priority": 8,
            }
        ])
        rc, out, err = _run_script(
            "process_mail.py",
            "--rules", rules,
            stdin_data=json.dumps(messages),
        )
        assert rc == 0, f"stderr: {err}"
        data = json.loads(out)
        result = data["results"][0]
        assert result["move_to"] == "Finances"
        assert "invoice" in result["tags"]
        assert "sort_invoices" in result["matched_rules"]

    def test_process_no_matches(self):
        messages = {
            "messages": [
                {
                    "subject": "Hello",
                    "sender": {"address": "friend@x.com", "display_name": ""},
                    "body_plain": "Hi",
                    "message_id": "<2@x.com>",
                    "mailbox": "INBOX",
                }
            ]
        }
        rules = json.dumps([
            {
                "name": "boss_only",
                "sender_pattern": "boss@company\\.com",
                "actions": ["flag"],
                "priority": 1,
            }
        ])
        rc, out, _ = _run_script(
            "process_mail.py",
            "--rules", rules,
            stdin_data=json.dumps(messages),
        )
        assert rc == 0
        data = json.loads(out)
        assert data["rules_matched"] == 0


class TestReadMailScript:
    def test_read_from_stdin_json(self):
        """Read a message from stdin JSON and output as JSON."""
        message = {
            "message_id": "<test123@example.com>",
            "subject": "Test Message",
            "sender": {"address": "sender@example.com", "display_name": "Sender"},
            "body_plain": "Hello, this is a test.",
            "body_html": "<p>Hello, this is a test.</p>",
            "mailbox": "INBOX",
        }
        rc, out, err = _run_script(
            "read_mail.py",
            "--from-stdin",
            stdin_data=json.dumps(message),
        )
        assert rc == 0, f"stderr: {err}"
        data = json.loads(out)
        assert data["subject"] == "Test Message"
        assert data["message_id"] == "<test123@example.com>"

    def test_read_from_stdin_cli_format(self):
        """Read a message from stdin and render as CLI output."""
        message = {
            "message_id": "<cli-test@example.com>",
            "subject": "CLI Render Test",
            "sender": {"address": "alice@example.com", "display_name": "Alice"},
            "body_plain": "This should be rendered in CLI format.",
            "mailbox": "INBOX",
        }
        rc, out, err = _run_script(
            "read_mail.py",
            "--from-stdin", "--format", "cli",
            stdin_data=json.dumps(message),
        )
        assert rc == 0, f"stderr: {err}"
        assert "CLI Render Test" in out
        assert "Alice" in out or "alice@example.com" in out
        assert "This should be rendered in CLI format." in out

    def test_read_from_stdin_messages_wrapper(self):
        """Read from stdin when input has a 'messages' wrapper."""
        data = {
            "messages": [
                {
                    "message_id": "<wrap@example.com>",
                    "subject": "Wrapped Message",
                    "sender": {"address": "bob@example.com", "display_name": "Bob"},
                    "body_plain": "Wrapped body.",
                    "mailbox": "INBOX",
                }
            ]
        }
        rc, out, err = _run_script(
            "read_mail.py",
            "--from-stdin",
            stdin_data=json.dumps(data),
        )
        assert rc == 0, f"stderr: {err}"
        result = json.loads(out)
        assert result["subject"] == "Wrapped Message"

    def test_read_no_message_id_fails(self):
        """Fail when neither --message-id nor --from-stdin is provided."""
        rc, _, err = _run_script("read_mail.py")
        assert rc != 0
        assert "error" in err.lower() or "required" in err.lower()


class TestFetchMailScript:
    def test_fetch_from_stdin(self):
        """Fetch script can accept JSON messages from stdin."""
        messages = {
            "messages": [
                {
                    "message_id": "<stdin1@test.com>",
                    "subject": "Stdin Test",
                    "sender": {"address": "x@y.com", "display_name": "X"},
                    "body_plain": "From stdin",
                    "mailbox": "INBOX",
                }
            ]
        }
        rc, out, err = _run_script(
            "fetch_mail.py",
            "--from-stdin",
            stdin_data=json.dumps(messages),
        )
        assert rc == 0, f"stderr: {err}"
        data = json.loads(out)
        assert data["count"] == 1
        assert data["messages"][0]["subject"] == "Stdin Test"

    def test_fetch_from_stdin_cli_format(self):
        """Fetch script CLI format shows message list."""
        messages = {
            "messages": [
                {
                    "message_id": "<cli1@test.com>",
                    "subject": "CLI Fetch Test",
                    "sender": {"address": "sender@test.com", "display_name": "Sender"},
                    "body_plain": "Test",
                    "mailbox": "INBOX",
                }
            ]
        }
        rc, out, err = _run_script(
            "fetch_mail.py",
            "--from-stdin", "--format", "cli",
            stdin_data=json.dumps(messages),
        )
        assert rc == 0, f"stderr: {err}"
        assert "CLI Fetch Test" in out

    def test_fetch_no_host_fails(self):
        """Fetch without host or config should fail."""
        rc, _, err = _run_script("fetch_mail.py")
        assert rc != 0


class TestManageFoldersScript:
    def test_manage_no_host_fails(self):
        """manage_folders without IMAP host should fail."""
        rc, _, err = _run_script(
            "manage_folders.py",
            "--action", "list",
        )
        assert rc != 0
        assert "error" in err.lower()

    def test_manage_create_needs_folder(self):
        """manage_folders create without --folder should fail."""
        rc, _, err = _run_script(
            "manage_folders.py",
            "--action", "create",
            "--imap-host", "fake.example.com",
        )
        assert rc != 0

    def test_manage_rename_needs_both(self):
        """manage_folders rename without --new-name should fail."""
        rc, _, err = _run_script(
            "manage_folders.py",
            "--action", "rename",
            "--folder", "OldName",
            "--imap-host", "fake.example.com",
        )
        assert rc != 0

    def test_manage_move_needs_new_parent(self):
        """manage_folders move without --new-parent should fail."""
        rc, _, err = _run_script(
            "manage_folders.py",
            "--action", "move",
            "--folder", "Projects",
            "--imap-host", "fake.example.com",
        )
        assert rc != 0


class TestMoveMailScript:
    def test_move_no_ids_fails(self):
        """move_mail without message IDs should fail."""
        rc, _, err = _run_script(
            "move_mail.py",
            "--to", "Archive",
            "--imap-host", "fake.example.com",
        )
        assert rc != 0

    def test_move_to_required(self):
        """move_mail without --to should fail."""
        rc, _, err = _run_script(
            "move_mail.py",
            "--message-id", "<x@y.com>",
        )
        assert rc != 0


class TestSendMailScript:
    def test_send_no_recipient_fails(self):
        """send_mail without --to should fail."""
        rc, _, err = _run_script(
            "send_mail.py",
            "--subject", "Test",
            "--body", "Hello",
        )
        assert rc != 0

    def test_send_no_subject_fails(self):
        """send_mail without --subject should fail."""
        rc, _, err = _run_script(
            "send_mail.py",
            "--to", "user@example.com",
            "--body", "Hello",
        )
        assert rc != 0


class TestAccountFieldInScripts:
    def test_fetch_preserves_account_field(self):
        """Account field flows through fetch_mail stdin passthrough."""
        messages = {
            "messages": [
                {
                    "message_id": "<acct1@test.com>",
                    "subject": "Account Test",
                    "sender": {"address": "x@y.com", "display_name": "X"},
                    "body_plain": "Test",
                    "mailbox": "INBOX",
                    "account": "work",
                }
            ]
        }
        rc, out, err = _run_script(
            "fetch_mail.py",
            "--from-stdin",
            stdin_data=json.dumps(messages),
        )
        assert rc == 0, f"stderr: {err}"
        data = json.loads(out)
        assert data["messages"][0]["account"] == "work"

    def test_process_includes_account_in_result(self):
        """Process output includes the account field from the message."""
        messages = {
            "messages": [
                {
                    "subject": "Account Process",
                    "sender": {"address": "boss@example.com", "display_name": "Boss"},
                    "body_plain": "Do this",
                    "message_id": "<acct-proc@test.com>",
                    "mailbox": "INBOX",
                    "account": "personal",
                }
            ]
        }
        rules = json.dumps([{
            "name": "catch_all",
            "sender_pattern": ".*",
            "actions": ["tag"],
            "tag": "processed",
            "priority": 1,
        }])
        rc, out, err = _run_script(
            "process_mail.py",
            "--rules", rules,
            stdin_data=json.dumps(messages),
        )
        assert rc == 0, f"stderr: {err}"
        data = json.loads(out)
        assert data["results"][0]["account"] == "personal"

    def test_read_shows_account_in_cli(self):
        """CLI render of read_mail shows the account when present."""
        message = {
            "message_id": "<acct-cli@test.com>",
            "subject": "Account CLI Test",
            "sender": {"address": "a@b.com", "display_name": "A"},
            "body_plain": "Body text.",
            "mailbox": "INBOX",
            "account": "work",
        }
        rc, out, err = _run_script(
            "read_mail.py",
            "--from-stdin", "--format", "cli",
            stdin_data=json.dumps(message),
        )
        assert rc == 0, f"stderr: {err}"
        assert "work" in out


class TestPipelineIntegration:
    def test_compose_to_process_pipe(self):
        """Compose a message, then process it through rules."""
        rc, compose_out, _ = _run_script(
            "compose_mail.py",
            "--to", "user@example.com",
            "--subject", "Urgent: Please Review",
            "--body", "This needs attention.",
        )
        assert rc == 0
        composed = json.loads(compose_out)

        messages = {"messages": [composed]}
        rules = json.dumps([{
            "name": "catch_urgent",
            "subject_pattern": "urgent",
            "actions": ["tag"],
            "tag": "needs_review",
            "priority": 5,
        }])

        rc, process_out, err = _run_script(
            "process_mail.py",
            "--rules", rules,
            stdin_data=json.dumps(messages),
        )
        assert rc == 0, f"stderr: {err}"
        data = json.loads(process_out)
        assert data["rules_matched"] == 1
        assert "needs_review" in data["results"][0]["tags"]

    def test_compose_to_read_pipe(self):
        """Compose a message, then read/render it via stdin pipe."""
        rc, compose_out, _ = _run_script(
            "compose_mail.py",
            "--to", "user@example.com",
            "--subject", "Pipe Test",
            "--body", "Piped content.",
        )
        assert rc == 0

        rc, read_out, err = _run_script(
            "read_mail.py",
            "--from-stdin", "--format", "cli",
            stdin_data=compose_out,
        )
        assert rc == 0, f"stderr: {err}"
        assert "Pipe Test" in read_out

    def test_fetch_to_read_pipe(self):
        """Fetch from stdin, then read via stdin pipe."""
        messages = {
            "messages": [
                {
                    "message_id": "<pipe@test.com>",
                    "subject": "Fetch-Read Pipe",
                    "sender": {"address": "a@b.com", "display_name": "A"},
                    "body_plain": "Pipeline test content.",
                    "mailbox": "INBOX",
                }
            ]
        }
        rc, fetch_out, err = _run_script(
            "fetch_mail.py",
            "--from-stdin",
            stdin_data=json.dumps(messages),
        )
        assert rc == 0, f"stderr: {err}"

        rc, read_out, err = _run_script(
            "read_mail.py",
            "--from-stdin", "--format", "cli",
            stdin_data=fetch_out,
        )
        assert rc == 0, f"stderr: {err}"
        assert "Fetch-Read Pipe" in read_out
