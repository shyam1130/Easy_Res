# Restaurant Table Ordering & Billing POS

A mobile-friendly FastAPI application for table ordering and billing in Nepal. Prices and receipts use NPR (`Rs.`); the optional VAT toggle applies 13%.

Waiters can select any empty or occupied table; empty tables start a new order, while occupied tables show the current bill for another round. After admin login, the floor overview lets admins select any table to view and edit its active itemized bill, review settled bill history, and settle and close the current bill.

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
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` on the restaurant machine, or use its LAN address from a device on the same Wi-Fi. The default local SQLite database is `restaurant_pos.db`. Set `DATABASE_URL` to a SQLAlchemy URL to use another database, for example `postgresql+psycopg://user:password@host/database`.

There are no built-in admin credentials. On a fresh database, set `ADMIN_EMAIL` and an `ADMIN_PASSWORD` of at least 12 characters before starting the app; startup fails if either is missing. These values are used only to create the initial admin account and are not written to the source files. Existing databases keep their current admin account; changing these environment variables does not reset an existing password. Passwords are stored as salted PBKDF2 hashes; sessions expire after 12 hours and are kept in process memory. For production on a shared network, deploy behind HTTPS and use managed database backups. The initial menu is seeded only when the menu table is empty.

Admins and waiters sign in through the same email/password form. Admins can view bills, settle tables, manage waiter accounts, and update the menu. Waiters can take orders and adjust table bills but cannot manage accounts, prices, or settlement.

## Main API

- `POST /api/auth/login`: sign in with email and password; returns a token and role.
- `GET /api/auth/me`, `POST /api/auth/logout`: inspect or end the current session.
- Send the returned token in `X-Auth-Token` for all other API calls.
- `GET /api/tables`, `GET /api/tables/{table_number}/order`: table status and current bill (admin or waiter).
- `GET /api/tables/{table_number}/history`: settled bills for a table (admin only).
- `GET /api/admin/bills/history`: settled bills from all tables (admin only).
- `GET /api/menu`: available menu items (admin or waiter).
- `POST /api/tables/{table_number}/items`, `PATCH /api/orders/{order_id}/vat`: waiter order operations.
- `PATCH /api/orders/items/{item_id}`: waiter or admin quantity adjustments; zero removes the line.
- `POST /api/orders/{order_id}/close`, `GET /api/orders/{order_id}`: admin-only settlement and bill history.
- `GET/POST /api/admin/menu`, `PUT/DELETE /api/admin/menu/{item_id}`: admin menu management.
- `GET/POST /api/admin/waiters`, `PUT/DELETE /api/admin/waiters/{waiter_id}`: admin waiter-account management.

Interactive API documentation is available at `/docs`.

## Tests

```powershell
python -m pytest
```
