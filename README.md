# OpenClaw claw-mail Skill

A multi-account email skill for [OpenClaw](https://openclaw.ai) that manages email across multiple IMAP/SMTP accounts. Retrieves, reads, searches, processes, composes, sends, replies, forwards, and organizes emails with secure credential storage, IMAP Outbox delivery, TLS 1.2+ enforcement, OAuth2 support, and per-account rules.

## Features

- **Multi-account support** — Configure multiple email accounts with a designated default
- **IMAP email retrieval** — Fetch, read, and search emails from any IMAP server
- **SMTP email sending** — Send rich HTML emails with automatic fallback relay
- **IMAP Outbox** — Messages staged in a temporary Outbox folder for reliable delivery (Apple Mail pattern)
- **Secure credential storage** — 1Password CLI (`op://`), macOS Keychain (`keychain://`), and environment variables (`env://`)
- **TLS 1.2+ hardened** — All connections enforce TLS 1.2+ with strong cipher suites; weak ciphers blocked
- **RFC 5322 compliance** — Outgoing emails always include required Date, Message-ID, and MIME-Version headers
- **OAuth2 authentication** — XOAUTH2 support for Gmail and Outlook 365
- **Reply and forward** — Reply with original quoting; forward inline or with attachments
- **Drafts** — Save, list, resume, and send drafts via IMAP Drafts folder
- **IMAP IDLE** — Real-time push monitoring via RFC 2177
- **Conversation threading** — Group messages into threads by References / In-Reply-To
- **Calendar invitations** — Compose and send iCalendar VEVENT meeting invites
- **Mail merge** — Batch personalised sends from template + CSV/JSON data
- **S/MIME signing & encryption** — Sign and encrypt with PKCS#12 or PEM certificates
- **Folder management** — List, create, delete, rename, and move IMAP folders
- **Message flags** — Standard flags (read, flagged) plus custom keyword flags
- **Batch operations** — Move or flag multiple messages in a single IMAP session
- **Rich HTML templates** — Three built-in templates (default, minimal, digest) with inline CSS
- **Rule-based processing** — Per-account and global rules with regex matching and webhook actions
- **Connection pooling** — Reuse IMAP/SMTP connections within heartbeat cycles
- **Auto-archival** — Archive messages older than N days into dated folders (Archive-YYYYMM, Archive-Wxxxx, Archive-YYYYMMDD) with configurable frequency
- **Heartbeat-ready** — Full multi-account Outbox drain + fetch + process cycle in a single script
- **Dual output formats** — All scripts support JSON (default) and CLI-formatted output

## Requirements

- Python 3.11+
- PyYAML (`pyyaml>=6.0`)
- Optional: 1Password CLI (`op`) for `op://` credentials
- Optional: macOS for `keychain://` credentials
- Optional: `cryptography` package for S/MIME

## Installation

```bash
git clone https://github.com/borgcube/openClaw.git
cd openClaw
pip install pyyaml
```

Copy the example config and fill in your credentials:

```bash
cp skills/claw-mail/assets/config.example.yaml skills/claw-mail/config.yaml
```

## Configuration

All scripts look for `config.yaml` in the skill root directory (`skills/claw-mail/`) when `--config` is not provided.

```yaml
default_account: work

smtp_fallback:
  host: smtp-relay.example.com
  port: 587
  username: "relay-user"
  password: "op://Shared/SMTP-Relay/password"   # 1Password
  tls: true

accounts:
  work:
    label: "Work"
    sender_address: "alice@company.com"
    sender_name: "Alice Smith"
    imap:
      host: imap.company.com
      port: 993
      username: "alice@company.com"
      password: "op://Work/IMAP/password"        # 1Password CLI
      ssl: true
      timeout: 30
    smtp:
      host: smtp.company.com
      port: 587
      username: "alice@company.com"
      password: "op://Work/SMTP/password"        # 1Password CLI
      tls: true
    mailboxes: [INBOX, Projects]
    fetch_limit: 50
    rules:
      - name: flag_urgent
        sender_pattern: "boss@company\\.com"
        actions: [flag, tag]
        tag: urgent
        priority: 10

  personal:
    label: "Personal"
    sender_address: "alice@gmail.com"
    imap:
      host: imap.gmail.com
      port: 993
      username: "alice@gmail.com"
      password: "keychain://imap.gmail.com/alice@gmail.com"  # macOS Keychain
      ssl: true
    smtp:
      host: smtp.gmail.com
      port: 587
      username: "alice@gmail.com"
      password: "keychain://smtp.gmail.com/alice@gmail.com"  # macOS Keychain
      tls: true
    mailboxes: [INBOX]
    fetch_limit: 25
    rules: []

# Global rules (applied to ALL accounts)
rules:
  - name: spam_filter
    subject_pattern: "(?i)buy now|act fast"
    actions: [move]
    move_to: Junk
    priority: 100

defaults:
  fetch_limit: 50
  archive_root: Archive
  archive_frequency: monthly

Each account may override these defaults by setting `archive_root` and `archive_frequency` (daily, weekly, monthly, yearly). The heartbeat rule engine and `archive_mail.py` use those values when moving old mail into folders named like `Archive-202603`, `Archive-W09`, or `Archive-20260315`.
```

### Secure Credential Storage

Passwords in config support four backends. All scripts resolve credentials via `credential_store.resolve()`, including direct `--imap-pass` and `--smtp-pass` flags.

| Scheme | Backend | Example |
|--------|---------|---------|
| `op://` | 1Password CLI | `"op://Work/IMAP/password"` |
| `keychain://` | macOS Keychain | `"keychain://imap.gmail.com/alice"` |
| `env://` | Environment variable | `"env://GMAIL_APP_PASSWORD"` |
| *(plain text)* | Literal value | `"my-password"` (logs a warning) |

### OAuth2 Authentication (Gmail, Outlook 365)

```yaml
imap:
  host: imap.gmail.com
  username: "user@gmail.com"
  auth: oauth2
  oauth2:
    client_id: "your-client-id"
    client_secret: "op://Gmail/OAuth/client-secret"
    refresh_token: "op://Gmail/OAuth/refresh-token"
    token_uri: "https://oauth2.googleapis.com/token"
```

Legacy single-account configs (flat `imap:` / `smtp:` at root) are automatically treated as a single account named "default".

## Usage

All scripts live in `skills/claw-mail/scripts/` and output JSON by default. Every script accepts `--account <name>` to target a specific account — if omitted, the `default_account` is used. The `--config` flag is optional when `config.yaml` exists in the skill root.

### Fetch emails

```bash
python3 scripts/fetch_mail.py

python3 scripts/fetch_mail.py --account personal --unread-only --format cli
```

### Read a specific email

```bash
python3 scripts/read_mail.py --message-id "<id@example.com>" --format cli
```

### Send email (Outbox + SMTP fallback)

```bash
python3 scripts/send_mail.py \
  --account work \
  --to "recipient@example.com" \
  --subject "Weekly Report" \
  --body "<p>Results attached.</p>" \
  --template default \
  --attach report.pdf
```

### Search emails

```bash
python3 scripts/search_mail.py --subject "invoice" --unseen

python3 scripts/search_mail.py --criteria '(FROM "alice@x.com" SINCE 01-Jan-2026)'
```

### Reply and forward

```bash
python3 scripts/reply_mail.py --message-id "<id@example.com>" --body "Thanks!"

python3 scripts/forward_mail.py --message-id "<id@example.com>" --to "colleague@x.com"
```

### Manage folders

```bash
python3 scripts/manage_folders.py --action list --format cli

python3 scripts/manage_folders.py --action create --folder Projects
```

### Move emails

```bash
python3 scripts/move_mail.py --message-id "<id@example.com>" --to Archive
```

### Archive old mail

```bash
python3 scripts/archive_mail.py --config config.yaml --days 90 --frequency monthly
python3 scripts/archive_mail.py --config config.yaml --days 30 --frequency daily --archive-root "Old Mail" --dry-run --format cli
```

### Outbox and send retry

```bash
python3 scripts/retry_send.py --list

python3 scripts/retry_send.py
```

### Run a heartbeat cycle

```bash
python3 scripts/heartbeat.py

python3 scripts/heartbeat.py --account work
```

### Calendar invitations

```bash
python3 scripts/calendar_invite.py \
  --to "bob@example.com" --subject "Standup" \
  --start "2026-03-01T09:00:00" --end "2026-03-01T09:30:00" \
  --location "Zoom"
```

### Mail merge

```bash
python3 scripts/mail_merge.py \
  --data contacts.csv --subject "Hello {{name}}" \
  --body "<p>Dear {{name}}, your code is {{code}}.</p>" \
  --to-field email
```

## Project Structure

```
skills/claw-mail/
├── SKILL.md                     # Skill definition (OpenAgentSkills format)
├── ROADMAP.md                   # Feature roadmap
├── config.yaml                  # Your config (create from example)
├── assets/
│   └── config.example.yaml      # Example multi-account configuration
├── references/
│   ├── REFERENCE.md             # Full API reference for all scripts
│   ├── TEMPLATES.md             # Email template guide
│   └── RULES.md                 # Processing rules documentation
├── tests/
│   └── test_remaining_features.py
└── scripts/
    ├── fetch_mail.py            # Fetch emails from IMAP
    ├── read_mail.py             # Read/render a single email by ID
    ├── search_mail.py           # Search emails by criteria
    ├── send_mail.py             # Send emails via SMTP (Outbox pattern)
    ├── compose_mail.py          # Compose emails as JSON (no send)
    ├── reply_mail.py            # Reply with original quoting
    ├── forward_mail.py          # Forward to new recipients
    ├── draft_mail.py            # Save, list, resume, send drafts
    ├── process_mail.py          # Rule-based email processing
    ├── manage_folders.py        # IMAP folder management
    ├── move_mail.py             # Move emails between folders
    ├── heartbeat.py             # Full multi-account heartbeat cycle
    ├── idle_monitor.py          # IMAP IDLE push monitor
    ├── retry_send.py            # Drain IMAP Outbox (retry failed sends)
    ├── calendar_invite.py       # iCalendar meeting invitations
    ├── mail_merge.py            # Batch personalised sends
    ├── thread_mail.py           # Conversation threading
    ├── archive_mail.py          # Auto-archive old messages
    └── lib/
        ├── models.py            # Data models (EmailMessage, etc.)
        ├── account_manager.py   # Multi-account registry, SMTP fallback, Outbox
        ├── imap_client.py       # IMAP client (IDLE, search, TLS 1.2+)
        ├── smtp_client.py       # SMTP client (TLS 1.2+, RFC 5322)
        ├── composer.py          # HTML template engine
        ├── processor.py         # Rule engine (account-aware)
        ├── outbox.py            # IMAP Outbox for reliable delivery
        ├── credential_store.py  # Secure credential storage backends
        ├── defaults.py          # Default paths and config helpers
        ├── pool.py              # Connection pool for IMAP/SMTP reuse
        ├── oauth2.py            # OAuth2 (XOAUTH2) token management
        ├── smime.py             # S/MIME signing and encryption
        └── send_queue.py        # Legacy file-backed send queue
```

## Running Tests

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT
