import pytest
from fastapi.testclient import TestClient

from app.main import create_app

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "test-only-admin-password"


def make_client(tmp_path):
    app = create_app(
        f"sqlite:///{tmp_path / 'test.db'}",
        admin_email=ADMIN_EMAIL,
        admin_password=ADMIN_PASSWORD,
    )
    client = TestClient(app)
    client.__enter__()
    return client


def admin_headers(client):
    response = client.post(
        "/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200
    return {"X-Auth-Token": response.json()["token"]}


def waiter_headers(client):
    headers = admin_headers(client)
    created = client.post(
        "/api/admin/waiters",
        headers=headers,
        json={"email": "waiter@example.com", "password": "waiter@123"},
    )
    assert created.status_code == 201
    response = client.post(
        "/api/auth/login",
        json={"email": "waiter@example.com", "password": "waiter@123"},
    )
    assert response.status_code == 200
    return {"X-Auth-Token": response.json()["token"]}


def test_first_start_requires_admin_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    app = create_app(f"sqlite:///{tmp_path / 'unconfigured.db'}")

    with pytest.raises(RuntimeError, match="Set ADMIN_EMAIL and ADMIN_PASSWORD"):
        with TestClient(app):
            pass


def test_first_start_rejects_short_admin_password(tmp_path):
    app = create_app(
        f"sqlite:///{tmp_path / 'weak-password.db'}",
        admin_email=ADMIN_EMAIL,
        admin_password="short",
    )

    with pytest.raises(RuntimeError, match="at least 12 characters"):
        with TestClient(app):
            pass


def test_first_start_uses_environment_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_EMAIL)
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PASSWORD)
    app = create_app(f"sqlite:///{tmp_path / 'environment-configured.db'}")

    with TestClient(app) as client:
        response = client.post(
            "/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        )
        assert response.status_code == 200


def test_existing_admin_database_starts_without_bootstrap_credentials(
    tmp_path, monkeypatch
):
    database_url = f"sqlite:///{tmp_path / 'existing-admin.db'}"
    with TestClient(create_app(
        database_url,
        admin_email=ADMIN_EMAIL,
        admin_password=ADMIN_PASSWORD,
    )):
        pass

    monkeypatch.delenv("ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    with TestClient(create_app(database_url)) as client:
        response = client.post(
            "/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        )
        assert response.status_code == 200


def test_price_snapshot_zero_quantity_and_archive(tmp_path):
    with make_client(tmp_path) as client:
        admin = admin_headers(client)
        waiter = waiter_headers(client)
        menu = client.get("/api/menu", headers=waiter).json()
        menu_item = menu[0]
        original_price = menu_item["price"]

        added = client.post(
            "/api/tables/1/items",
            json={"items": [{"menu_item_id": menu_item["id"], "quantity": 2}]},
            headers=waiter,
        )
        assert added.status_code == 200
        line = added.json()["items"][0]
        assert line["unit_price"] == original_price

        increased = client.patch(
            f"/api/orders/items/{line['id']}",
            json={"quantity": 3},
            headers=admin,
        )
        assert increased.status_code == 200
        assert increased.json()["items"][0]["quantity"] == 3

        updated = client.put(
            f"/api/admin/menu/{menu_item['id']}",
            headers=admin,
            json={
                "name": menu_item["name"],
                "category": menu_item["category"],
                "price": "999.00",
                "is_available": True,
            },
        )
        assert updated.status_code == 200

        current = client.get("/api/tables/1/order", headers=waiter).json()
        assert current["items"][0]["unit_price"] == original_price
        assert current["subtotal"] == f"{float(original_price) * 3:.2f}"

        close_url = f"/api/orders/{current['id']}/close"
        assert client.post(close_url, headers=waiter).status_code == 403
        closed = client.post(close_url, headers=admin)
        assert closed.status_code == 200
        assert closed.json()["status"] == "CLOSED"
        assert closed.json()["items"][0]["unit_price"] == original_price
        assert client.get("/api/tables/1/order", headers=waiter).json() is None
        history = client.get("/api/tables/1/history", headers=admin)
        assert history.status_code == 200
        assert history.json()[0]["id"] == closed.json()["id"]
        assert history.json()[0]["items"][0]["quantity"] == 3
        assert client.get("/api/tables/1/history", headers=waiter).status_code == 403
        all_history = client.get("/api/admin/bills/history", headers=admin)
        assert all_history.status_code == 200
        assert closed.json()["id"] in [bill["id"] for bill in all_history.json()]
        assert client.get("/api/admin/bills/history", headers=waiter).status_code == 403

        reopened = client.post(
            "/api/tables/1/items",
            json={"items": [{"menu_item_id": menu_item["id"], "quantity": 1}]},
            headers=waiter,
        ).json()
        assert reopened["id"] != closed.json()["id"]
        reopened_line = reopened["items"][0]
        assert reopened_line["unit_price"] == "999.00"
        removed = client.patch(
            f"/api/orders/items/{reopened_line['id']}",
            json={"quantity": 0},
            headers=waiter,
        )
        assert removed.status_code == 200
        assert removed.json()["items"] == []
        assert removed.json()["subtotal"] == "0.00"
        assert client.get("/api/tables/1/order", headers=waiter).json()["status"] == "OPEN"


def test_table_isolation_vat_and_admin_protection(tmp_path):
    with make_client(tmp_path) as client:
        waiter = waiter_headers(client)
        menu_item = client.get("/api/menu", headers=waiter).json()[0]
        assert client.get("/api/admin/menu", headers=waiter).status_code == 403

        order = client.post(
            "/api/tables/3/items",
            json={"items": [{"menu_item_id": menu_item["id"], "quantity": 1}]},
            headers=waiter,
        ).json()
        vat_order = client.patch(
            f"/api/orders/{order['id']}/vat",
            json={"enabled": True},
            headers=waiter,
        ).json()
        assert vat_order["vat_rate"] == "0.1300"
        assert vat_order["vat_amount"] == f"{round(float(menu_item['price']) * 0.13, 2):.2f}"

        second_round = client.post(
            "/api/tables/3/items",
            json={"items": [{"menu_item_id": menu_item["id"], "quantity": 1}]},
            headers=waiter,
        )
        assert second_round.status_code == 200
        assert len(second_round.json()["items"]) == 2
        tables = client.get("/api/tables", headers=waiter).json()
        assert tables[2]["status"] == "OCCUPIED"
        assert tables[1]["status"] == "EMPTY"
        invalid_table = client.post(
            "/api/tables/16/items",
            json={"items": [{"menu_item_id": menu_item["id"], "quantity": 1}]},
            headers=waiter,
        )
        assert invalid_table.status_code == 404


def test_soft_delete_hides_menu_but_preserves_order_history(tmp_path):
    with make_client(tmp_path) as client:
        admin = admin_headers(client)
        waiter = waiter_headers(client)
        item = client.get("/api/menu", headers=waiter).json()[0]
        order = client.post(
            "/api/tables/2/items",
            json={"items": [{"menu_item_id": item["id"], "quantity": 1}]},
            headers=waiter,
        ).json()

        response = client.delete(f"/api/admin/menu/{item['id']}", headers=admin)
        assert response.status_code == 204
        assert all(
            row["id"] != item["id"]
            for row in client.get("/api/menu", headers=waiter).json()
        )
        saved = client.get(f"/api/orders/{order['id']}", headers=admin).json()
        assert saved["items"][0]["item_name"] == item["name"]
        assert saved["items"][0]["unit_price"] == item["price"]


def test_email_login_roles_and_waiter_account_management(tmp_path):
    with make_client(tmp_path) as client:
        assert client.post(
            "/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": "wrong-password"},
        ).status_code == 401

        admin = admin_headers(client)
        waiter_response = client.post(
            "/api/admin/waiters",
            headers=admin,
            json={"email": "New.Waiter@example.com", "password": "waiter@123"},
        )
        assert waiter_response.status_code == 201
        waiter = waiter_response.json()
        assert waiter["email"] == "new.waiter@example.com"
        assert "password_hash" not in waiter
        assert client.post(
            "/api/admin/waiters",
            headers=admin,
            json={"email": "NEW.WAITER@example.com", "password": "otherpass@123"},
        ).status_code == 409

        login = client.post(
            "/api/auth/login",
            json={"email": "NEW.WAITER@example.com", "password": "waiter@123"},
        )
        assert login.status_code == 200
        waiter_token = {"X-Auth-Token": login.json()["token"]}
        assert login.json()["user"]["role"] == "waiter"
        assert client.get("/api/admin/waiters", headers=waiter_token).status_code == 403
        assert client.get("/api/tables", headers=waiter_token).status_code == 200

        updated = client.put(
            f"/api/admin/waiters/{waiter['id']}",
            headers=admin,
            json={"password": "newpass@123"},
        )
        assert updated.status_code == 200
        assert client.post(
            "/api/auth/login",
            json={"email": "new.waiter@example.com", "password": "waiter@123"},
        ).status_code == 401
        assert client.post(
            "/api/auth/login",
            json={"email": "new.waiter@example.com", "password": "newpass@123"},
        ).status_code == 200

        assert client.delete(
            f"/api/admin/waiters/{waiter['id']}", headers=admin
        ).status_code == 204
        assert client.get("/api/tables", headers=waiter_token).status_code == 401
