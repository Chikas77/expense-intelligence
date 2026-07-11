# Supabase Schema + Auth Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give expense-intelligence a persistent Supabase-backed database and a username/password auth system, replacing the current in-memory-only `Transaction` handling.

**Architecture:** A Postgres schema (5 tables + RLS + one helper function) lives in a Supabase migration file. A thin Python layer (`supabase_client.py`, `auth_service.py`) wraps the `supabase-py` SDK so Flask routes never talk to Supabase directly. New `auth_routes.py` Flask Blueprint exposes `/signup`, `/login`, `/logout`, following the existing app's convention of building HTML as raw strings (see `app.py`'s `show_pages_detailed`) rather than introducing a templating system.

**Tech Stack:** Python 3, Flask (existing), `supabase-py` (new), Supabase Postgres + Auth, `unittest` (existing test convention — see `test_api_flows.py`).

## Global Constraints

- Login is username + password. Signup collects username, email, phone, password, and consent — copied verbatim from the spec.
- One M-Pesa number per user; no `mpesa_accounts` table in this plan.
- Statement content (raw SMS text or PDF bytes) is never persisted — only parsed transactions and upload metadata.
- All new Python files follow the existing flat, single-file-per-concern layout already used by `parser.py`, `categorization_questions.py`, etc. — no new package/subdirectory structure.
- All new tests use `unittest` (matching `test_api_flows.py`), mock every Supabase network call, and are run with `python -m unittest <module> -v`.
- Applying the database migration to any real/shared Supabase project is a manual, human-confirmed step (Task 2) — not something an agent executes autonomously, since it changes shared, hard-to-reverse infrastructure.

---

### Task 1: Supabase client factory

**Files:**
- Modify: `requirements.txt`
- Create: `.env.example`
- Create: `supabase_client.py`
- Test: `test_supabase_client.py`

**Interfaces:**
- Produces: `supabase_client.get_admin_client() -> Client`, `supabase_client.get_anon_client() -> Client` — used by every later task that talks to Supabase.

- [ ] **Step 1: Add the Supabase dependency**

Modify `requirements.txt` to add these two lines at the end:

```
supabase>=2.4.0
python-dotenv>=1.0.0
```

- [ ] **Step 2: Install and verify**

Run: `pip install -r requirements.txt`
Expected: install completes with no errors; `pip show supabase` reports a version `>=2.4.0`.

- [ ] **Step 3: Document the required environment variables**

Create `.env.example`:

```
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_ANON_KEY=your-anon-public-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
FLASK_SECRET_KEY=change-me-to-a-random-value
```

- [ ] **Step 4: Write the failing test**

Create `test_supabase_client.py`:

```python
import os
import unittest
from unittest.mock import patch

import supabase_client


class SupabaseClientTest(unittest.TestCase):
    @patch('supabase_client.create_client')
    def test_get_admin_client_uses_service_role_key(self, mock_create_client):
        with patch.dict(os.environ, {
            'SUPABASE_URL': 'https://example.supabase.co',
            'SUPABASE_SERVICE_ROLE_KEY': 'service-role-key',
        }, clear=False):
            supabase_client.get_admin_client()
        mock_create_client.assert_called_once_with('https://example.supabase.co', 'service-role-key')

    @patch('supabase_client.create_client')
    def test_get_anon_client_uses_anon_key(self, mock_create_client):
        with patch.dict(os.environ, {
            'SUPABASE_URL': 'https://example.supabase.co',
            'SUPABASE_ANON_KEY': 'anon-key',
        }, clear=False):
            supabase_client.get_anon_client()
        mock_create_client.assert_called_once_with('https://example.supabase.co', 'anon-key')


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 5: Run test to verify it fails**

Run: `python -m unittest test_supabase_client -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'supabase_client'`

- [ ] **Step 6: Write the implementation**

Create `supabase_client.py`:

```python
import os

from supabase import create_client, Client


def get_admin_client() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def get_anon_client() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_ANON_KEY"]
    return create_client(url, key)
```

- [ ] **Step 7: Run test to verify it passes**

Run: `python -m unittest test_supabase_client -v`
Expected: `OK` — 2 tests passed.

- [ ] **Step 8: Commit**

```bash
git add requirements.txt .env.example supabase_client.py test_supabase_client.py
git commit -m "feat: add Supabase client factory"
```

---

### Task 2: Database migration — schema, RLS, and login helper

**Files:**
- Create: `supabase/migrations/20260711120000_init_schema.sql`

**Interfaces:**
- Produces: tables `profiles`, `mpesa_statements`, `transactions`, `recipients`, `category_changes`; Postgres function `public.resolve_login_email(p_username text) returns text`, consumed by Task 4 (`log_in`).

- [ ] **Step 1: Write the migration**

Create `supabase/migrations/20260711120000_init_schema.sql`:

```sql
-- profiles: extends auth.users with username, phone, and consent
create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  username text not null unique,
  phone text not null unique,
  consent_accepted_at timestamptz not null,
  created_at timestamptz not null default now()
);

alter table public.profiles enable row level security;

create policy "profiles_select_own" on public.profiles
  for select using (id = auth.uid());
create policy "profiles_update_own" on public.profiles
  for update using (id = auth.uid());
create policy "profiles_insert_own" on public.profiles
  for insert with check (id = auth.uid());

-- mpesa_statements: upload metadata only, raw content is never stored
create table public.mpesa_statements (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  source_type text not null check (source_type in ('sms_paste', 'pdf_upload')),
  status text not null check (status in ('processing', 'parsed', 'failed')) default 'processing',
  transaction_count int not null default 0,
  uploaded_at timestamptz not null default now()
);

alter table public.mpesa_statements enable row level security;

create policy "statements_all_own" on public.mpesa_statements
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

-- transactions: mirrors parser.py's Transaction class
create table public.transactions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  statement_id uuid references public.mpesa_statements(id) on delete set null,
  transaction_code text,
  description text,
  clean_name text,
  amount numeric(12, 2) not null,
  is_inflow boolean not null default false,
  is_repayment boolean not null default false,
  balance numeric(12, 2),
  occurred_at timestamptz,
  category text,
  sub_type text,
  category_source text not null check (category_source in ('auto', 'kesho_conversation', 'user_manual')) default 'auto',
  created_at timestamptz not null default now(),
  unique (user_id, transaction_code, amount, occurred_at)
);

alter table public.transactions enable row level security;

create policy "transactions_all_own" on public.transactions
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

-- recipients: foundation for recipient-profile learning
create table public.recipients (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  clean_name text not null,
  relationship text check (relationship in ('family', 'friend', 'business', 'unknown')),
  default_category text,
  default_sub_type text,
  times_seen int not null default 1,
  last_seen_at timestamptz not null default now(),
  unique (user_id, clean_name)
);

alter table public.recipients enable row level security;

create policy "recipients_all_own" on public.recipients
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

-- category_changes: lightweight audit trail
create table public.category_changes (
  id uuid primary key default gen_random_uuid(),
  transaction_id uuid not null references public.transactions(id) on delete cascade,
  old_category text,
  new_category text not null,
  changed_by text not null check (changed_by in ('kesho', 'user')),
  changed_at timestamptz not null default now()
);

alter table public.category_changes enable row level security;

create policy "category_changes_select_own" on public.category_changes
  for select using (
    exists (
      select 1 from public.transactions t
      where t.id = category_changes.transaction_id and t.user_id = auth.uid()
    )
  );
create policy "category_changes_insert_own" on public.category_changes
  for insert with check (
    exists (
      select 1 from public.transactions t
      where t.id = category_changes.transaction_id and t.user_id = auth.uid()
    )
  );

-- resolve_login_email: lets the app translate a username into the email
-- Supabase Auth actually authenticates with, without exposing profiles publicly
create or replace function public.resolve_login_email(p_username text)
returns text
language plpgsql
security definer
set search_path = public
as $$
declare
  v_user_id uuid;
  v_email text;
begin
  select id into v_user_id from public.profiles where username = p_username;
  if v_user_id is null then
    return null;
  end if;

  select email into v_email from auth.users where id = v_user_id;
  return v_email;
end;
$$;

revoke all on function public.resolve_login_email(text) from public;
grant execute on function public.resolve_login_email(text) to anon, authenticated, service_role;
```

- [ ] **Step 2: Validate the migration locally**

If the Supabase CLI is installed and linked to a local dev stack:

Run: `supabase start` then `supabase db reset`
Expected: output ends with the migration listed as applied and no SQL errors.

- [ ] **Step 3: Verify the objects were created**

Open Supabase Studio (local: `http://localhost:54323`, printed by `supabase start`) → SQL Editor → run:

```sql
select tablename from pg_tables where schemaname = 'public' order by tablename;
```

Expected result — exactly these 5 rows: `category_changes`, `mpesa_statements`, `profiles`, `recipients`, `transactions`.

- [ ] **Step 4: Apply against the real project (manual, human-confirmed step)**

This is the one step in this plan that touches shared, hard-to-reverse infrastructure — do this yourself rather than delegating it to an agent:
1. Open your Supabase project's SQL Editor in the dashboard.
2. Paste the contents of `supabase/migrations/20260711120000_init_schema.sql`.
3. Read it once, then run it.
4. Re-run the verification query from Step 3 against the real project to confirm.

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/20260711120000_init_schema.sql
git commit -m "feat: add initial Supabase schema, RLS policies, and login helper"
```

---

### Task 3: Auth service — sign_up

**Files:**
- Create: `auth_service.py`
- Test: `test_auth_service.py`

**Interfaces:**
- Consumes: `supabase_client.get_admin_client()`, `supabase_client.get_anon_client()` (Task 1).
- Produces: `auth_service.AuthSession` (dataclass: `user_id`, `username`, `access_token`, `refresh_token`), `auth_service.UsernameTakenError`, `auth_service.sign_up(username, email, phone, password, consent) -> AuthSession` — consumed by Task 5.

- [ ] **Step 1: Write the failing tests**

Create `test_auth_service.py`:

```python
import unittest
from unittest.mock import MagicMock, patch

import auth_service
from auth_service import AuthSession, UsernameTakenError


class SignUpTest(unittest.TestCase):
    def setUp(self):
        patcher_admin = patch('auth_service.get_admin_client')
        patcher_anon = patch('auth_service.get_anon_client')
        self.mock_get_admin = patcher_admin.start()
        self.mock_get_anon = patcher_anon.start()
        self.addCleanup(patcher_admin.stop)
        self.addCleanup(patcher_anon.stop)

        self.admin_client = MagicMock()
        self.anon_client = MagicMock()
        self.mock_get_admin.return_value = self.admin_client
        self.mock_get_anon.return_value = self.anon_client

    def test_sign_up_rejects_without_consent(self):
        with self.assertRaises(ValueError):
            auth_service.sign_up('mwangi_k', 'mwangi@example.com', '+254712345678', 'hunter22', consent=False)

    def test_sign_up_rejects_taken_username(self):
        self.admin_client.table.return_value.select.return_value.eq.return_value.execute.return_value = \
            MagicMock(data=[{'id': 'existing-id'}])

        with self.assertRaises(UsernameTakenError):
            auth_service.sign_up('mwangi_k', 'mwangi@example.com', '+254712345678', 'hunter22', consent=True)

    def test_sign_up_creates_user_profile_and_returns_session(self):
        self.admin_client.table.return_value.select.return_value.eq.return_value.execute.return_value = \
            MagicMock(data=[])

        created_user = MagicMock()
        created_user.user.id = 'new-user-id'
        self.admin_client.auth.admin.create_user.return_value = created_user

        signed_in = MagicMock()
        signed_in.session.access_token = 'access-token-123'
        signed_in.session.refresh_token = 'refresh-token-123'
        self.anon_client.auth.sign_in_with_password.return_value = signed_in

        result = auth_service.sign_up('mwangi_k', 'mwangi@example.com', '+254712345678', 'hunter22', consent=True)

        self.assertEqual(result, AuthSession(
            user_id='new-user-id',
            username='mwangi_k',
            access_token='access-token-123',
            refresh_token='refresh-token-123',
        ))
        self.admin_client.auth.admin.create_user.assert_called_once_with({
            "email": "mwangi@example.com",
            "password": "hunter22",
            "email_confirm": True,
        })
        insert_call_args = self.admin_client.table.return_value.insert.call_args[0][0]
        self.assertEqual(insert_call_args['id'], 'new-user-id')
        self.assertEqual(insert_call_args['username'], 'mwangi_k')
        self.assertEqual(insert_call_args['phone'], '+254712345678')
        self.assertIn('consent_accepted_at', insert_call_args)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest test_auth_service -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'auth_service'`

- [ ] **Step 3: Write the implementation**

Create `auth_service.py`:

```python
from dataclasses import dataclass
from datetime import datetime, timezone

from supabase_client import get_admin_client, get_anon_client


class UsernameTakenError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


@dataclass
class AuthSession:
    user_id: str
    username: str
    access_token: str
    refresh_token: str


def _username_exists(admin_client, username: str) -> bool:
    result = admin_client.table('profiles').select('id').eq('username', username).execute()
    return len(result.data) > 0


def sign_up(username: str, email: str, phone: str, password: str, consent: bool) -> AuthSession:
    if not consent:
        raise ValueError("consent must be accepted to sign up")

    admin_client = get_admin_client()

    if _username_exists(admin_client, username):
        raise UsernameTakenError(f"username '{username}' is already taken")

    created = admin_client.auth.admin.create_user({
        "email": email,
        "password": password,
        "email_confirm": True,
    })
    user_id = created.user.id

    admin_client.table('profiles').insert({
        "id": user_id,
        "username": username,
        "phone": phone,
        "consent_accepted_at": datetime.now(timezone.utc).isoformat(),
    }).execute()

    anon_client = get_anon_client()
    signed_in = anon_client.auth.sign_in_with_password({
        "email": email,
        "password": password,
    })

    return AuthSession(
        user_id=user_id,
        username=username,
        access_token=signed_in.session.access_token,
        refresh_token=signed_in.session.refresh_token,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest test_auth_service -v`
Expected: `OK` — 3 tests passed.

- [ ] **Step 5: Commit**

```bash
git add auth_service.py test_auth_service.py
git commit -m "feat: add sign_up to auth service"
```

---

### Task 4: Auth service — log_in

**Files:**
- Modify: `auth_service.py`
- Modify: `test_auth_service.py`

**Interfaces:**
- Consumes: Postgres function `resolve_login_email` (Task 2), `AuthSession` (Task 3).
- Produces: `auth_service.log_in(username, password) -> AuthSession`, `auth_service.InvalidCredentialsError` — both consumed by Task 6.

- [ ] **Step 1: Write the failing tests**

Add to `test_auth_service.py` (append after `SignUpTest`, before the `if __name__` block):

```python
from auth_service import InvalidCredentialsError


class LogInTest(unittest.TestCase):
    def setUp(self):
        patcher_admin = patch('auth_service.get_admin_client')
        patcher_anon = patch('auth_service.get_anon_client')
        self.mock_get_admin = patcher_admin.start()
        self.mock_get_anon = patcher_anon.start()
        self.addCleanup(patcher_admin.stop)
        self.addCleanup(patcher_anon.stop)

        self.admin_client = MagicMock()
        self.anon_client = MagicMock()
        self.mock_get_admin.return_value = self.admin_client
        self.mock_get_anon.return_value = self.anon_client

    def test_log_in_rejects_unknown_username(self):
        self.admin_client.rpc.return_value.execute.return_value = MagicMock(data=None)

        with self.assertRaises(InvalidCredentialsError):
            auth_service.log_in('nobody', 'whatever')

    def test_log_in_rejects_wrong_password(self):
        self.admin_client.rpc.return_value.execute.return_value = MagicMock(data='mwangi@example.com')
        self.anon_client.auth.sign_in_with_password.side_effect = Exception('invalid grant')

        with self.assertRaises(InvalidCredentialsError):
            auth_service.log_in('mwangi_k', 'wrong-password')

    def test_log_in_returns_session_on_success(self):
        self.admin_client.rpc.return_value.execute.return_value = MagicMock(data='mwangi@example.com')

        signed_in = MagicMock()
        signed_in.user.id = 'existing-user-id'
        signed_in.session.access_token = 'access-token-456'
        signed_in.session.refresh_token = 'refresh-token-456'
        self.anon_client.auth.sign_in_with_password.return_value = signed_in

        result = auth_service.log_in('mwangi_k', 'hunter22')

        self.assertEqual(result, AuthSession(
            user_id='existing-user-id',
            username='mwangi_k',
            access_token='access-token-456',
            refresh_token='refresh-token-456',
        ))
        self.admin_client.rpc.assert_called_once_with('resolve_login_email', {'p_username': 'mwangi_k'})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest test_auth_service -v`
Expected: FAIL — `AttributeError: module 'auth_service' has no attribute 'log_in'`

- [ ] **Step 3: Write the implementation**

Append to `auth_service.py`:

```python
def log_in(username: str, password: str) -> AuthSession:
    admin_client = get_admin_client()

    resolved = admin_client.rpc('resolve_login_email', {'p_username': username}).execute()
    email = resolved.data

    if not email:
        raise InvalidCredentialsError("invalid username or password")

    anon_client = get_anon_client()
    try:
        signed_in = anon_client.auth.sign_in_with_password({
            "email": email,
            "password": password,
        })
    except Exception as exc:
        raise InvalidCredentialsError("invalid username or password") from exc

    if not signed_in.session:
        raise InvalidCredentialsError("invalid username or password")

    return AuthSession(
        user_id=signed_in.user.id,
        username=username,
        access_token=signed_in.session.access_token,
        refresh_token=signed_in.session.refresh_token,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest test_auth_service -v`
Expected: `OK` — 6 tests passed.

- [ ] **Step 5: Commit**

```bash
git add auth_service.py test_auth_service.py
git commit -m "feat: add log_in to auth service"
```

---

### Task 5: Flask signup route

**Files:**
- Create: `auth_routes.py`
- Modify: `app.py`
- Test: `test_auth_routes.py`

**Interfaces:**
- Consumes: `auth_service.sign_up`, `auth_service.UsernameTakenError` (Task 3).
- Produces: `auth_routes.auth_bp` (Flask Blueprint) registered on `app`, route `/signup` (GET form, POST submit) — the blueprint is extended by Task 6.

- [ ] **Step 1: Write the failing tests**

Create `test_auth_routes.py`:

```python
import unittest
from unittest.mock import patch

from app import app
from auth_service import AuthSession, UsernameTakenError


class SignupRouteTest(unittest.TestCase):
    def setUp(self):
        app.testing = True
        app.secret_key = 'test-secret'
        self.client = app.test_client()

    def test_get_signup_returns_form(self):
        response = self.client.get('/signup')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Create your account', response.data)

    @patch('auth_routes.sign_up')
    def test_post_signup_success_sets_session_and_redirects(self, mock_sign_up):
        mock_sign_up.return_value = AuthSession(
            user_id='user-1', username='mwangi_k',
            access_token='token-a', refresh_token='token-b',
        )
        response = self.client.post('/signup', data={
            'username': 'mwangi_k',
            'email': 'mwangi@example.com',
            'phone': '+254712345678',
            'password': 'hunter22',
            'consent': 'on',
        })
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess['user_id'], 'user-1')
            self.assertEqual(sess['username'], 'mwangi_k')

    @patch('auth_routes.sign_up')
    def test_post_signup_taken_username_shows_error(self, mock_sign_up):
        mock_sign_up.side_effect = UsernameTakenError('taken')
        response = self.client.post('/signup', data={
            'username': 'mwangi_k',
            'email': 'mwangi@example.com',
            'phone': '+254712345678',
            'password': 'hunter22',
            'consent': 'on',
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'already taken', response.data)

    @patch('auth_routes.sign_up')
    def test_post_signup_without_consent_shows_error(self, mock_sign_up):
        mock_sign_up.side_effect = ValueError('consent must be accepted to sign up')
        response = self.client.post('/signup', data={
            'username': 'mwangi_k',
            'email': 'mwangi@example.com',
            'phone': '+254712345678',
            'password': 'hunter22',
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'accept the terms', response.data)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest test_auth_routes -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'auth_routes'`

- [ ] **Step 3: Write the implementation**

Create `auth_routes.py`:

```python
from flask import Blueprint, request, redirect, session, url_for

from auth_service import sign_up, log_in, UsernameTakenError, InvalidCredentialsError

auth_bp = Blueprint('auth', __name__)


def _signup_form_html(error=None):
    error_html = f'<p style="color:red">{error}</p>' if error else ''
    return f"""
    <html><body>
    <h1>Create your account</h1>
    {error_html}
    <form method="POST" action="/signup">
      <label>Username <input type="text" name="username" required></label><br>
      <label>Email <input type="email" name="email" required></label><br>
      <label>Phone <input type="tel" name="phone" required></label><br>
      <label>Password <input type="password" name="password" required></label><br>
      <label><input type="checkbox" name="consent" required> I agree to the Terms and how my financial data is used</label><br>
      <button type="submit">Create account</button>
    </form>
    </body></html>
    """


def _login_form_html(error=None):
    error_html = f'<p style="color:red">{error}</p>' if error else ''
    return f"""
    <html><body>
    <h1>Welcome back</h1>
    {error_html}
    <form method="POST" action="/login">
      <label>Username <input type="text" name="username" required></label><br>
      <label>Password <input type="password" name="password" required></label><br>
      <button type="submit">Log in</button>
    </form>
    </body></html>
    """


@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'GET':
        return _signup_form_html()

    username = request.form.get('username', '').strip()
    email = request.form.get('email', '').strip()
    phone = request.form.get('phone', '').strip()
    password = request.form.get('password', '')
    consent = request.form.get('consent') == 'on'

    try:
        auth_session = sign_up(username, email, phone, password, consent)
    except UsernameTakenError:
        return _signup_form_html(error='That username is already taken.'), 400
    except ValueError:
        return _signup_form_html(error='You must accept the terms to sign up.'), 400

    session['user_id'] = auth_session.user_id
    session['username'] = auth_session.username
    session['access_token'] = auth_session.access_token
    session['refresh_token'] = auth_session.refresh_token
    return redirect(url_for('home'))
```

Modify `app.py`: add `import os` to the top of the import block (line 1), and add blueprint registration right after `app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024` (currently line 17):

```python
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'dev-secret-key-change-me')

from auth_routes import auth_bp
app.register_blueprint(auth_bp)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest test_auth_routes -v`
Expected: `OK` — 4 tests passed.

- [ ] **Step 5: Run the full existing test suite to check nothing broke**

Run: `python -m unittest discover -p "test_*.py" -v`
Expected: all existing tests plus the new ones pass — no regressions in `test_api_flows.py`, `test_complete_flow.py`, `test_questions.py`, `test_reconstruction_and_balances.py`.

- [ ] **Step 6: Commit**

```bash
git add auth_routes.py app.py test_auth_routes.py
git commit -m "feat: add signup route"
```

---

### Task 6: Flask login and logout routes

**Files:**
- Modify: `auth_routes.py`
- Modify: `test_auth_routes.py`

**Interfaces:**
- Consumes: `auth_service.log_in`, `auth_service.InvalidCredentialsError` (Task 4).
- Produces: routes `/login` (GET form, POST submit) and `/logout` (POST) on `auth_bp`.

- [ ] **Step 1: Write the failing tests**

Append to `test_auth_routes.py` (before the `if __name__` block):

```python
from auth_service import InvalidCredentialsError


class LoginRouteTest(unittest.TestCase):
    def setUp(self):
        app.testing = True
        app.secret_key = 'test-secret'
        self.client = app.test_client()

    def test_get_login_returns_form(self):
        response = self.client.get('/login')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Welcome back', response.data)

    @patch('auth_routes.log_in')
    def test_post_login_success_sets_session_and_redirects(self, mock_log_in):
        mock_log_in.return_value = AuthSession(
            user_id='user-1', username='mwangi_k',
            access_token='token-a', refresh_token='token-b',
        )
        response = self.client.post('/login', data={'username': 'mwangi_k', 'password': 'hunter22'})
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess['user_id'], 'user-1')

    @patch('auth_routes.log_in')
    def test_post_login_invalid_credentials_shows_error(self, mock_log_in):
        mock_log_in.side_effect = InvalidCredentialsError('invalid username or password')
        response = self.client.post('/login', data={'username': 'mwangi_k', 'password': 'wrong'})
        self.assertEqual(response.status_code, 401)
        self.assertIn(b'Incorrect username or password', response.data)


class LogoutRouteTest(unittest.TestCase):
    def setUp(self):
        app.testing = True
        app.secret_key = 'test-secret'
        self.client = app.test_client()

    def test_logout_clears_session(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 'user-1'
        response = self.client.post('/logout')
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertNotIn('user_id', sess)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest test_auth_routes -v`
Expected: FAIL — 404s on `/login` and `/logout` (routes don't exist yet).

- [ ] **Step 3: Write the implementation**

Append to `auth_routes.py`:

```python
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return _login_form_html()

    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')

    try:
        auth_session = log_in(username, password)
    except InvalidCredentialsError:
        return _login_form_html(error='Incorrect username or password.'), 401

    session['user_id'] = auth_session.user_id
    session['username'] = auth_session.username
    session['access_token'] = auth_session.access_token
    session['refresh_token'] = auth_session.refresh_token
    return redirect(url_for('home'))


@auth_bp.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('home'))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest test_auth_routes -v`
Expected: `OK` — 7 tests passed.

- [ ] **Step 5: Run the full test suite one more time**

Run: `python -m unittest discover -p "test_*.py" -v`
Expected: all tests pass, no regressions.

- [ ] **Step 6: Commit**

```bash
git add auth_routes.py test_auth_routes.py
git commit -m "feat: add login and logout routes"
```

---

## What's next

This plan delivers the database schema, RLS, and a working (if plainly styled) username/password auth flow. Not covered here, each its own future plan per the phase 2 roadmap:
- Restyling `/signup` and `/login` to match the Kesho landing page design.
- Porting `parser.py`'s extraction logic to write into `transactions` and `mpesa_statements` server-side.
- The Kesho conversational AI, cash-crunch predictor, and WhatsApp/SMS alerts.
