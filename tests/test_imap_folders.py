"""Tests for IMAP mailbox-name quoting, list parsing, and modified-UTF-7."""

import os
import sys

# Make the library importable
sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "skills", "claw-mail", "scripts"),
)

from lib.imap_client import (
    _decode_mutf7,
    _encode_mutf7,
    _quote_mailbox,
    IMAPClient,
)


# ── _quote_mailbox ──────────────────────────────────────────────────


class TestQuoteMailbox:
    def test_simple_name(self):
        assert _quote_mailbox("INBOX") == '"INBOX"'

    def test_name_with_spaces(self):
        assert _quote_mailbox("Needs Review") == '"Needs Review"'

    def test_name_with_multiple_spaces(self):
        assert _quote_mailbox("My Important Folder") == '"My Important Folder"'

    def test_nested_with_spaces(self):
        assert _quote_mailbox("Archive/Needs Review") == '"Archive/Needs Review"'

    def test_embedded_backslash(self):
        assert _quote_mailbox("back\\slash") == '"back\\\\slash"'

    def test_embedded_double_quote(self):
        assert _quote_mailbox('say "hello"') == '"say \\"hello\\""'

    def test_both_special_chars(self):
        assert _quote_mailbox('a\\"b') == '"a\\\\\\"b"'

    def test_empty_string(self):
        assert _quote_mailbox("") == '""'

    def test_unicode_chars(self):
        # Non-ASCII chars are passed through; IMAP modified-UTF-7 encoding
        # is handled separately before quoting.
        assert _quote_mailbox("Réunions") == '"Réunions"'

    def test_delimiter_chars(self):
        assert _quote_mailbox("Work/Projects/Q1 2024") == '"Work/Projects/Q1 2024"'


# ── _decode_mutf7 ──────────────────────────────────────────────────


class TestDecodeMutf7:
    def test_plain_ascii(self):
        assert _decode_mutf7("INBOX") == "INBOX"

    def test_literal_ampersand(self):
        assert _decode_mutf7("Tom &- Jerry") == "Tom & Jerry"

    def test_encoded_non_ascii(self):
        # "Réunions" in modified-UTF-7: é = U+00E9
        # UTF-16BE for é = 0x00E9
        # base64("\\x00\\xe9") = "AOk=" -> strip padding -> "AOk"
        # modified-UTF-7 uses , instead of / so "AOk" stays "AOk"
        assert _decode_mutf7("R&AOk-unions") == "Réunions"

    def test_japanese_folder(self):
        # 下書き (drafts) — common folder name on Japanese mail servers
        # U+4E0B U+66F8 U+304D
        # UTF-16BE: 4E0B 66F8 304D
        import base64

        raw = "\u4e0b\u66f8\u304d".encode("utf-16-be")
        b64 = base64.b64encode(raw).decode("ascii").rstrip("=")
        mutf7 = "&" + b64.replace("/", ",") + "-"
        assert _decode_mutf7(mutf7) == "下書き"

    def test_mixed_ascii_and_encoded(self):
        # "Dossier spécial" — "sp&AOk-cial"
        assert _decode_mutf7("Dossier sp&AOk-cial") == "Dossier spécial"

    def test_empty_string(self):
        assert _decode_mutf7("") == ""

    def test_malformed_no_closing_dash(self):
        # Malformed sequence — should not crash, treats rest as literal
        result = _decode_mutf7("test&abc")
        assert isinstance(result, str)

    def test_multiple_encoded_segments(self):
        # Two encoded segments in one name
        assert _decode_mutf7("&AOk-l&AOg-ve") == "élève"


# ── _encode_mutf7 ──────────────────────────────────────────────────


class TestEncodeMutf7:
    def test_plain_ascii(self):
        assert _encode_mutf7("INBOX") == "INBOX"

    def test_literal_ampersand(self):
        assert _encode_mutf7("Tom & Jerry") == "Tom &- Jerry"

    def test_non_ascii(self):
        encoded = _encode_mutf7("Réunions")
        assert _decode_mutf7(encoded) == "Réunions"

    def test_japanese(self):
        text = "下書き"
        encoded = _encode_mutf7(text)
        assert _decode_mutf7(encoded) == text

    def test_empty_string(self):
        assert _encode_mutf7("") == ""

    def test_roundtrip_mixed(self):
        text = "Dossier spécial"
        assert _decode_mutf7(_encode_mutf7(text)) == text

    def test_roundtrip_ampersand(self):
        text = "A & B & C"
        assert _decode_mutf7(_encode_mutf7(text)) == text

    def test_roundtrip_emoji(self):
        text = "Stars \u2605"
        assert _decode_mutf7(_encode_mutf7(text)) == text


# ── list_folders parsing ────────────────────────────────────────────


class TestListFoldersParsing:
    """Test list_folders by mocking the IMAP connection."""

    @staticmethod
    def _make_client_with_list_data(data_lines: list[bytes]) -> IMAPClient:
        """Create an IMAPClient with a mocked connection returning data_lines."""
        client = IMAPClient(host="fake", port=993)

        class FakeConn:
            def list(self):
                return ("OK", data_lines)

        client._connection = FakeConn()
        return client

    def test_quoted_folder_with_spaces(self):
        data = [b'(\\HasNoChildren) "/" "Needs Review"']
        client = self._make_client_with_list_data(data)
        folders = client.list_folders()
        assert len(folders) == 1
        assert folders[0]["name"] == "Needs Review"
        assert folders[0]["delimiter"] == "/"

    def test_unquoted_folder(self):
        data = [b'(\\HasNoChildren) "/" INBOX']
        client = self._make_client_with_list_data(data)
        folders = client.list_folders()
        assert len(folders) == 1
        assert folders[0]["name"] == "INBOX"

    def test_multiple_folders_mixed(self):
        data = [
            b'(\\HasNoChildren) "/" INBOX',
            b'(\\HasNoChildren) "/" Sent',
            b'(\\HasChildren) "/" "Project Files"',
            b'(\\HasNoChildren) "/" "Archive/Q1 2024"',
        ]
        client = self._make_client_with_list_data(data)
        folders = client.list_folders()
        assert len(folders) == 4
        names = [f["name"] for f in folders]
        assert "INBOX" in names
        assert "Sent" in names
        assert "Project Files" in names
        assert "Archive/Q1 2024" in names

    def test_folder_with_escaped_quotes(self):
        # Folder name containing a literal double-quote: say "hi"
        data = [b'(\\HasNoChildren) "/" "say \\"hi\\""']
        client = self._make_client_with_list_data(data)
        folders = client.list_folders()
        assert len(folders) == 1
        assert folders[0]["name"] == 'say "hi"'

    def test_folder_with_escaped_backslash(self):
        data = [b'(\\HasNoChildren) "/" "back\\\\slash"']
        client = self._make_client_with_list_data(data)
        folders = client.list_folders()
        assert len(folders) == 1
        assert folders[0]["name"] == "back\\slash"

    def test_dot_delimiter(self):
        data = [b'(\\HasNoChildren) "." "INBOX.Needs Review"']
        client = self._make_client_with_list_data(data)
        folders = client.list_folders()
        assert len(folders) == 1
        assert folders[0]["delimiter"] == "."
        assert folders[0]["name"] == "INBOX.Needs Review"

    def test_nil_delimiter(self):
        data = [b'(\\Noselect) NIL "Virtual Folder"']
        client = self._make_client_with_list_data(data)
        folders = client.list_folders()
        assert len(folders) == 1
        assert folders[0]["delimiter"] == ""
        assert folders[0]["name"] == "Virtual Folder"

    def test_modified_utf7_folder(self):
        # é encoded as modified-UTF-7: &AOk-
        data = [b'(\\HasNoChildren) "/" "R&AOk-unions"']
        client = self._make_client_with_list_data(data)
        folders = client.list_folders()
        assert len(folders) == 1
        assert folders[0]["name"] == "Réunions"

    def test_flags_preserved(self):
        data = [b'(\\HasNoChildren \\Marked) "/" "Important Stuff"']
        client = self._make_client_with_list_data(data)
        folders = client.list_folders()
        assert len(folders) == 1
        assert "\\Marked" in folders[0]["flags"]
        assert folders[0]["name"] == "Important Stuff"

    def test_empty_list(self):
        client = self._make_client_with_list_data([])
        folders = client.list_folders()
        assert folders == []

    def test_non_bytes_items_skipped(self):
        # Some servers may return non-bytes items; they should be skipped
        client = self._make_client_with_list_data([None, 42])
        folders = client.list_folders()
        assert folders == []
