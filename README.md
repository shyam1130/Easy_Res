# Restaurant Table Ordering & Billing POS

A mobile-friendly FastAPI application for table ordering and billing in Nepal. Prices and receipts use NPR (`Rs.`); the optional VAT toggle applies 13%.

Waiters can select any empty or occupied table; empty tables start a new order, while occupied tables show the current bill for another round. After admin login, the floor overview lets admins select any table to view its active itemized bill, review settled bill history, and settle and close the current bill.

## Requirements

- Python 3.11+
- Dependencies from `requirements.txt`

## Run locally

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:ADMIN_EMAIL = "owner@example.com"
$env:ADMIN_PASSWORD = "set-a-private-password-at-least-12-characters"
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://localhost:8000` on the restaurant machine. This local development server is bound to the loopback interface and is not exposed to the LAN. The default local SQLite database is `restaurant_pos.db`. Set `DATABASE_URL` to a SQLAlchemy URL to use another database, for example `postgresql+psycopg://user:password@host/database`.

There are no built-in admin credentials. On a fresh database, set `ADMIN_EMAIL` and an `ADMIN_PASSWORD` of at least 12 characters before starting the app; startup fails if either is missing. These values are used only to create the initial admin account and are not written to the source files. Existing databases keep their current admin account; changing these environment variables does not reset an existing password. Passwords are stored as salted PBKDF2 hashes; sessions expire after 12 hours and are kept in process memory. The initial menu is seeded only when the menu table is empty.

## Production deployment

The `deploy/` directory contains example Caddy and systemd configuration for an Ubuntu 24.04 VPS. These templates are not live deployment credentials: replace `your-domain.example` with a registered domain after its DNS points to the VPS.

Do not expose the Uvicorn development server directly to the internet or a shared network. Caddy terminates TLS and redirects HTTP to HTTPS. Uvicorn listens only on loopback, trusts proxy headers only from that loopback proxy, and the app rejects non-HTTPS requests when `REQUIRE_HTTPS=true`.

```text
uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1
```

On the VPS, place the project at `/opt/easy-res`, create a `restaurant-pos` system user, and install the dependencies in `/opt/easy-res/.venv`. Create `/var/lib/easy-res` owned by that user for the database. Create `/etc/easy-res/restaurant.env` as a root-owned file with mode `600` containing `ADMIN_EMAIL`, a unique `ADMIN_PASSWORD` of at least 12 characters, `DATABASE_URL=sqlite:////var/lib/easy-res/restaurant_pos.db`, and `REQUIRE_HTTPS=true`. Never commit this environment file.

Install Caddy, copy `deploy/Caddyfile.example` to `/etc/caddy/Caddyfile`, replace the domain placeholder, and copy `deploy/restaurant-pos.service` to `/etc/systemd/system/restaurant-pos.service`. Then enable both services. Configure the VPS firewall to allow SSH (verify its actual port first), HTTP, and HTTPS only; do not expose port 8000. Caddy can issue a trusted certificate only after the domain resolves to this VPS and ports 80/443 are reachable. Use managed database backups and protect the database and service environment variables. These steps must be completed on the actual VPS; this workspace cannot register a domain or install services on it.

Admins and waiters sign in through the same email/password form. Admins can create waiter accounts with a display name, view bills, settle tables, manage waiter accounts, and update the menu. The session header shows "Admin" for admins and the waiter's name for waiters. Only waiters can add items to a table bill or adjust quantities; admins can settle and close bills.

## Main API

- `POST /api/auth/login`: sign in with email and password; returns a token and role.
- `GET /api/auth/me`, `POST /api/auth/logout`: inspect or end the current session.
- Send the returned token in `X-Auth-Token` for all other API calls.
- `GET /api/tables`, `GET /api/tables/{table_number}/order`: table status and current bill (admin or waiter).
- `GET /api/tables/{table_number}/history`: settled bills for a table (admin only).
- `GET /api/admin/bills/history`: settled bills from all tables (admin only).
- `GET /api/menu`: available menu items (admin or waiter).
- `POST /api/tables/{table_number}/items`, `PATCH /api/orders/{order_id}/vat`: waiter order operations.
- `PATCH /api/orders/items/{item_id}`: waiter quantity adjustments; zero removes the line.
- `POST /api/orders/{order_id}/close`, `GET /api/orders/{order_id}`: admin-only settlement and bill history.
- `GET/POST /api/admin/menu`, `PUT/DELETE /api/admin/menu/{item_id}`: admin menu management.
- `GET/POST /api/admin/waiters`, `PUT/DELETE /api/admin/waiters/{waiter_id}`: admin waiter-account management; creation requires a display name, email, and password.

Interactive API documentation is available at `/docs`.

## Tests

```powershell
python -m pytest
```
