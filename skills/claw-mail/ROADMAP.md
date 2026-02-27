# clawMail Skill — Roadmap

Living roadmap for the clawMail skill. Items are grouped by priority tier
and checked off as they land.

---

## Tier 1 — Core workflow gaps

- [x] **1. Attach files from disk** — `--attach` flag on `compose_mail.py` and
  `send_mail.py` so users can send file attachments without building JSON by hand.

- [x] **2. Save attachments to disk** — `--save-attachments <dir>` option on
  `read_mail.py` (and a standalone `save_attachments.py` helper) to download
  attachments from fetched messages.

- [x] **3. IMAP SEARCH** — `search_mail.py` script with `--subject`, `--from`,
  `--to`, `--body`, `--since`, `--before`, `--flagged`, `--unseen`, and
  free-text criteria. Wraps the IMAP SEARCH command.

- [x] **4. Standalone forward script** — `forward_mail.py` that forwards an
  existing message (inline-quoted or as attached `.eml`) to new recipients.

- [x] **5. Reply with original quoting** — Enhance `compose_reply()` and add a
  `reply_mail.py` script that inserts `> On date, sender wrote:` quoted blocks.

- [x] **6. Draft save / resume** — `draft_mail.py` script that saves a composed
  message to the IMAP Drafts folder and can resume (fetch + edit + send) a draft.

## Tier 2 — Robustness & infrastructure

- [x] **7. Message deduplication in heartbeat** — Track processed Message-IDs in
  the state file so the heartbeat never processes the same message twice.

- [x] **8. OAuth2 authentication** — Support OAuth2 (XOAUTH2) for IMAP and SMTP
  so users can connect to Gmail / Outlook 365 without app-passwords.
  OAuth2 credentials (`client_secret`, `refresh_token`) are resolved through
  `credential_store` for secure storage.

- [x] **9. IMAP IDLE (push notifications)** — Long-lived connection that waits
  for new-mail events instead of polling, for real-time monitoring.
  `idle_monitor.py` + `idle_start/idle_check/idle_done` methods on IMAPClient.

- [x] **10. Connection pooling / reuse** — Cache and reuse IMAP/SMTP connections
  across multiple operations within a single heartbeat cycle.
  `lib/pool.py` — `ConnectionPool` with max-age, liveness checks, context manager.

- [x] **11. IMAP Outbox for reliable delivery** — Messages are staged in a
  temporary IMAP "Outbox" folder before SMTP delivery (Apple Mail pattern).
  If SMTP fails, the message stays for retry. After all messages are sent,
  the Outbox folder is automatically removed.
  `lib/outbox.py` — `Outbox.stage()`, `Outbox.drain()`, auto-cleanup.
  `retry_send.py` drains Outbox instead of the legacy file-backed queue.

## Tier 3 — Security & compliance

- [x] **12. TLS 1.2+ enforcement** — All IMAP and SMTP connections enforce
  TLS 1.2 or higher with hardened cipher suites. Weak ciphers (MD5, RC4, 3DES)
  are explicitly blocked. Certificate verification is always enabled.
  `_create_secure_context()` in both `imap_client.py` and `smtp_client.py`.

- [x] **13. Secure credential storage** — Passwords in config and CLI flags are
  resolved via `credential_store.resolve()` supporting 1Password CLI (`op://`),
  macOS Keychain (`keychain://`), and environment variables (`env://`).
  All scripts, OAuth2 credentials, and S/MIME key passwords use this module.
  `lib/credential_store.py`.

- [x] **14. RFC 5322 compliance** — All outgoing emails automatically include
  required Date, Message-ID, and MIME-Version headers. Prevents emails from
  being flagged as spam by missing headers.

- [x] **15. Optional --config** — All scripts auto-detect `config.yaml` in the
  skill root directory when `--config` is not provided. `lib/defaults.py`.

## Tier 4 — Nice-to-have

- [x] **16. S/MIME signing & encryption** — Sign outgoing messages with an
  S/MIME certificate; optionally encrypt to recipient certificates.
  `lib/smime.py` — `SMIMESigner` and `SMIMEEncryptor` (requires `cryptography`).
  Key passwords are resolved through `credential_store`.

- [x] **17. Calendar invitations (iCalendar)** — Compose and send `text/calendar`
  MIME parts for meeting invites (VEVENT).
  `calendar_invite.py` with VEVENT builder, recurrence rules, and REQUEST/CANCEL.

- [x] **18. Mail merge** — Batch personalised sends from a template + CSV/JSON
  data source.
  `mail_merge.py` with `{{placeholder}}` syntax, CSV/JSON data loading, dry-run.

- [x] **19. Conversation threading** — Group messages into threads by
  `References` / `In-Reply-To` headers for a threaded view.
  `thread_mail.py` groups messages into threads via header graph traversal.

- [x] **20. Webhook / HTTP actions in rules** — A `webhook` rule action that
  POSTs a JSON payload to a URL when triggered.
  `WEBHOOK` action in `RuleAction` enum, `webhook_url` field, HTTP POST via urllib.

- [x] **21. Folder archival** — Auto-archive messages older than N days, moving
  them to yearly archive folders.
  `archive_mail.py` scans a folder, groups by year, moves to `Archive/YYYY` folders.

- [x] **22. OpenAgentSkills spec compliance** — `SKILL.md` frontmatter follows
  the OpenAgentSkills specification. Directory name `claw-mail` matches the
  `name` field (lowercase-alphanumeric-hyphens). Branding "clawMail" used in prose.

---

*Last updated: 2026-02-26 — All 22 items complete!*
