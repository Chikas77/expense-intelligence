# Supabase Schema + Auth Foundation — Design

**Status:** Approved by product owner, ready for implementation planning.
**Scope:** Sub-project 1 of the expense-intelligence "Kesho" phase 2 roadmap. Everything else in that roadmap (Kesho AI, cash-crunch predictor, WhatsApp/SMS alerts, advanced analytics) is built on top of this and is explicitly out of scope here.

## Why this comes first

The app currently has no database — `app.py` builds `Transaction` objects in memory for the lifetime of a single request and discards them. Every later phase 2 feature (a login, a conversational AI that writes categories, a predictor trained on history, an alert that fires when a pattern is detected) requires transactions and users to persist. This sub-project establishes that persistence layer and the account system it depends on.

## Decisions locked in

- **One M-Pesa number per user** for v1. Multiple numbers per account (e.g. personal + business till) can be added later without breaking this schema — it would mean adding an `mpesa_accounts` table and a foreign key from `mpesa_statements`, not reshaping what exists.
- **Login is username + password.** Signup additionally collects email and phone number, plus explicit consent to the Terms and how financial data is used.
- **Statements are not stored.** Only their parsed-out transactions and upload metadata persist, matching the product's stated privacy posture ("statements are parsed, then discarded").
- **Approach:** normalized relational schema (not a JSON blob per statement, not full event sourcing) plus one lightweight audit table for category changes — see [Approaches considered](#approaches-considered).

## Tables

### `profiles`
Extends `auth.users` with the fields Supabase's built-in auth doesn't carry.

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` | PK, references `auth.users(id)` |
| `username` | `text` | unique, not null |
| `phone` | `text` | unique, not null, E.164 format (e.g. `+2547...`) |
| `consent_accepted_at` | `timestamptz` | not null — when the user agreed to the Terms/data-use policy |
| `created_at` | `timestamptz` | default `now()` |

Email itself is **not** duplicated here — it already lives on `auth.users` since that's what Supabase Auth is actually keyed on underneath the username.

### `mpesa_statements`
One row per upload (a pasted SMS or an uploaded PDF), metadata only.

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` | PK |
| `user_id` | `uuid` | references `profiles(id)` |
| `source_type` | `text` | check in (`sms_paste`, `pdf_upload`) |
| `status` | `text` | check in (`processing`, `parsed`, `failed`) |
| `transaction_count` | `int` | how many transactions this upload produced |
| `uploaded_at` | `timestamptz` | default `now()` |

No filename, no raw bytes, no extracted text — nothing that reconstructs the original statement is kept.

### `transactions`
Mirrors the existing `Transaction` class in `parser.py`, with one addition.

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` | PK |
| `user_id` | `uuid` | references `profiles(id)` |
| `statement_id` | `uuid` | references `mpesa_statements(id)`, nullable — nullable so a future manual "add transaction" entry point isn't blocked; every transaction produced by this sub-project's upload flow will have one |
| `transaction_code` | `text` | nullable — M-Pesa's 10-char receipt code |
| `description` | `text` | raw parsed description |
| `clean_name` | `text` | recipient/sender name, cleaned (existing `get_clean_recipient_name` logic) |
| `amount` | `numeric(12,2)` | |
| `is_inflow` | `boolean` | |
| `is_repayment` | `boolean` | Fuliza/loan repayment flag |
| `balance` | `numeric(12,2)` | running balance after this transaction |
| `occurred_at` | `timestamptz` | |
| `category` | `text` | e.g. Food, Transport, Chama, Family Support, Informal Tax, Fuliza, Airtime, Other |
| `sub_type` | `text` | nullable — e.g. "School fees" under Family Support |
| `category_source` | `text` | **new** — check in (`auto`, `kesho_conversation`, `user_manual`); tracks how confident to be in a category |
| `created_at` | `timestamptz` | default `now()` |

Unique constraint on `(user_id, transaction_code, amount, occurred_at)` — this mirrors the dedup key already used in `app.py`'s `process_and_deduplicate_transactions`.

### `recipients`
Foundation for recipient-profile learning (referenced in the Kesho conversation demo — "I'll remember Wanjiru is family").

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` | PK |
| `user_id` | `uuid` | references `profiles(id)` |
| `clean_name` | `text` | |
| `relationship` | `text` | nullable — family / friend / business / unknown |
| `default_category` | `text` | nullable — learned default for this recipient |
| `default_sub_type` | `text` | nullable |
| `times_seen` | `int` | default 1 |
| `last_seen_at` | `timestamptz` | |

Unique constraint on `(user_id, clean_name)`.

### `category_changes`
Lightweight audit trail — not full event sourcing, just enough for undo and a future model feedback loop.

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` | PK |
| `transaction_id` | `uuid` | references `transactions(id)` |
| `old_category` | `text` | nullable |
| `new_category` | `text` | |
| `changed_by` | `text` | check in (`kesho`, `user`) |
| `changed_at` | `timestamptz` | default `now()` |

## Row-level security

RLS is enabled on all five tables. Policy shape:

- `profiles`: `id = auth.uid()`
- `mpesa_statements`, `transactions`, `recipients`: `user_id = auth.uid()`
- `category_changes`: scoped via a join to `transactions.user_id = auth.uid()`

No table is readable or writable across users, enforced at the database level regardless of what the application code does.

## Auth flow

Supabase Auth is email-native; there is no built-in username login. The workaround:

**Signup**
1. Client collects username, email, phone, password, and consent checkbox.
2. Server checks `username` isn't already taken in `profiles`.
3. `supabase.auth.signUp({ email, password })` creates the Auth user.
4. Insert the `profiles` row (`username`, `phone`, `consent_accepted_at`) linked to the new user's `id`.

**Login**
1. Client submits username + password.
2. A `SECURITY DEFINER` Postgres function `resolve_login_email(username text)` looks up the matching email via `profiles` → `auth.users`, without exposing the `profiles` table publicly.
3. The client calls `supabase.auth.signInWithPassword({ email: resolved_email, password })`.
4. To the user, this is invisible — they only ever typed a username.

## Data flow (mapping today's code to this schema)

1. User uploads a statement or pastes SMS text → one `mpesa_statements` row is created with `status = 'processing'`.
2. The existing `parser.py` logic (ported to run server-side, e.g. as a Supabase Edge Function or backend endpoint) extracts transactions and inserts `transactions` rows with `category_source = 'auto'` wherever the existing regex/keyword categorization is confident.
3. Anything the current decision-tree in `categorization_questions.py` can't resolve automatically is left for Kesho to ask about (Kesho itself is a separate sub-project; this schema just gives it somewhere to write).
4. When a category is confirmed — automatically or via Kesho — `category_changes` gets a row, and `recipients` is upserted (increment `times_seen`, update `last_seen_at`, and set `default_category`/`relationship` once a pattern is established).
5. `mpesa_statements.status` flips to `parsed` once all rows are inserted; the original text/PDF is never written anywhere persistent.

## Approaches considered

| Approach | Verdict |
|---|---|
| **Normalized relational schema + light audit table (chosen)** | Balances query-ability (needed for the predictor and analytics phases) against build complexity. |
| Full event sourcing (every categorization decision as an immutable event, current state derived) | More powerful for audit/undo but meaningfully more complex to build and query against; not justified at this stage. |
| Denormalized JSON blob per statement | Fastest to ship but blocks per-transaction queries, recipient learning, and predictor training data — ruled out. |

## Explicitly out of scope here

- The Kesho conversational AI itself (reads/writes these tables, but its own design/build is separate).
- The cash-crunch predictor model.
- WhatsApp/SMS alert delivery.
- Multiple M-Pesa numbers per account (schema leaves room for it, not building it now).

These are each their own sub-project in the phase 2 roadmap, built on top of what's defined here.
