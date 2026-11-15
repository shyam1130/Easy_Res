import base64
import hashlib
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.crud import add_items, close_order, get_open_order, get_order, get_or_create_open_order, set_vat, update_quantity
from app.database import Base, build_engine, make_session_factory
from app.models import MenuItem, OrderItem, TableOrder, User
from app.schemas import (
    AddItemsRequest,
    LoginRequest,
    LoginResponse,
    MenuItemCreate,
    MenuItemRead,
    MenuItemUpdate,
    OrderRead,
    QuantityUpdate,
    TableStatusRead,
    VatUpdate,
    UserRead,
    WaiterCreate,
    WaiterUpdate,
)

ROOT = Path(__file__).resolve().parent
SEED_MENU = (
    ("Chicken Momo", "Momo", "180.00"),
    ("Buff Momo", "Momo", "160.00"),
    ("Veg Momo", "Momo", "130.00"),
    ("Chicken Chowmein", "Noodles", "170.00"),
    ("Veg Chowmein", "Noodles", "140.00"),
    ("Chicken Thakali Set", "Main Course", "450.00"),
    ("Veg Thakali Set", "Main Course", "350.00"),
    ("Chicken Sekuwa", "Main Course", "320.00"),
    ("Masala Tea", "Beverages", "40.00"),
    ("Fresh Lemon Soda", "Beverages", "100.00"),
)


def serialize_order(order: TableOrder) -> dict:
    opened_at = order.opened_at
    closed_at = order.closed_at
    if opened_at.tzinfo is None:
        opened_at = opened_at.replace(tzinfo=timezone.utc)
    if closed_at is not None and closed_at.tzinfo is None:
        closed_at = closed_at.replace(tzinfo=timezone.utc)
    return {
        "id": order.id,
        "table_number": order.table_number,
        "status": order.status,
        "vat_rate": order.vat_rate,
        "items": [
            {
                "id": item.id,
                "menu_item_id": item.menu_item_id,
                "item_name": item.item_name,
                "unit_price": item.unit_price,
                "quantity": item.quantity,
                "line_total": item.line_total,
            }
            for item in order.items
        ],
        "subtotal": order.subtotal,
        "vat_amount": order.vat_amount,
        "total_amount": order.total_amount,
        "opened_at": opened_at.isoformat(),
        "closed_at": closed_at.isoformat() if closed_at else None,
    }


PASSWORD_ITERATIONS = 310_000
PASSWORD_SCHEME = "pbkdf2_sha256"


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )
    return "$".join(
        (
            PASSWORD_SCHEME,
            str(PASSWORD_ITERATIONS),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        )
    )


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, iterations, encoded_salt, encoded_digest = stored_hash.split("$")
        if scheme != PASSWORD_SCHEME:
            return False
        expected = base64.b64decode(encoded_digest, validate=True)
        salt = base64.b64decode(encoded_salt, validate=True)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(iterations)
        )
        return secrets.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def create_app(
    database_url: str | None = None,
    admin_email: str | None = None,
    admin_password: str | None = None,
) -> FastAPI:
    engine = build_engine(database_url)
    session_factory = make_session_factory(engine)
    configured_admin_email = normalize_email(
        admin_email if admin_email is not None else os.getenv("ADMIN_EMAIL", "")
    )
    configured_admin_password = (
        admin_password
        if admin_password is not None
        else os.getenv("ADMIN_PASSWORD", "")
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        Base.metadata.create_all(engine)
        with session_factory() as db:
            if db.scalar(select(MenuItem.id).limit(1)) is None:
                db.add_all(
                    [
                        MenuItem(
                            name=name,
                            category=category,
                            price=price,
                            is_available=True,
                        )
                        for name, category, price in SEED_MENU
                    ]
                )
            has_admin = db.scalar(
                select(User.id).where(User.role == "admin").limit(1)
            )
            if has_admin is None:
                if not configured_admin_email or not configured_admin_password:
                    raise RuntimeError(
                        "Set ADMIN_EMAIL and ADMIN_PASSWORD before first startup; "
                        "default admin credentials are disabled."
                    )
                if len(configured_admin_password) < 12:
                    raise RuntimeError(
                        "ADMIN_PASSWORD must be at least 12 characters."
                    )
                db.add(
                    User(
                        email=configured_admin_email,
                        password_hash=hash_password(configured_admin_password),
                        role="admin",
                        is_active=True,
                    )
                )
            db.commit()
        yield
        engine.dispose()

    app = FastAPI(title="Restaurant POS", version="1.0.0", lifespan=lifespan)
    app.state.session_factory = session_factory
    app.state.sessions = {}
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

    def db_dependency():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    def authenticated_user(
        request: Request,
        x_auth_token: str | None = Header(default=None),
        db: Session = Depends(db_dependency),
    ) -> User:
        session = request.app.state.sessions.get(x_auth_token or "")
        if session is None or session["expires_at"] <= datetime.now(timezone.utc):
            request.app.state.sessions.pop(x_auth_token or "", None)
            raise HTTPException(status_code=401, detail="Login required")
        user = db.get(User, session["user_id"])
        if user is None or not user.is_active:
            request.app.state.sessions.pop(x_auth_token or "", None)
            raise HTTPException(status_code=401, detail="Account is inactive")
        return user

    def require_roles(*roles: str):
        def dependency(user: User = Depends(authenticated_user)) -> User:
            if user.role not in roles:
                raise HTTPException(status_code=403, detail="Insufficient permissions")
            return user

        return dependency

    admin_only = require_roles("admin")
    waiter_only = require_roles("waiter")
    authenticated = require_roles("admin", "waiter")
    order_editor = require_roles("admin", "waiter")

    def validate_table_number(table_number: int) -> None:
        if table_number < 1 or table_number > 15:
            raise HTTPException(status_code=404, detail="Table not found")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(ROOT / "templates" / "index.html")

    @app.post("/api/auth/login", response_model=LoginResponse)
    def login(payload: LoginRequest, request: Request, db: Session = Depends(db_dependency)):
        email = normalize_email(str(payload.email))
        user = db.scalar(select(User).where(User.email == email))
        if (
            user is None
            or not user.is_active
            or not verify_password(payload.password, user.password_hash)
        ):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        token = secrets.token_urlsafe(32)
        request.app.state.sessions[token] = {
            "user_id": user.id,
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=12),
        }
        return {"token": token, "user": user}

    @app.get("/api/auth/me", response_model=UserRead)
    def read_current_user(user: User = Depends(authenticated)):
        return user

    @app.post(
        "/api/auth/logout",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(authenticated)],
    )
    def logout(
        request: Request,
        x_auth_token: str | None = Header(default=None),
    ):
        request.app.state.sessions.pop(x_auth_token or "", None)

    @app.get(
        "/api/menu",
        response_model=list[MenuItemRead],
        dependencies=[Depends(authenticated)],
    )
    def list_available_menu(db: Session = Depends(db_dependency)):
        return list(
            db.scalars(
                select(MenuItem)
                .where(MenuItem.is_deleted.is_(False), MenuItem.is_available.is_(True))
                .order_by(MenuItem.category, MenuItem.name)
            )
        )

    @app.get(
        "/api/admin/menu",
        response_model=list[MenuItemRead],
        dependencies=[Depends(admin_only)],
    )
    def admin_list_menu(db: Session = Depends(db_dependency)):
        return list(
            db.scalars(
                select(MenuItem)
                .where(MenuItem.is_deleted.is_(False))
                .order_by(MenuItem.category, MenuItem.name)
            )
        )

    @app.post(
        "/api/admin/menu",
        response_model=MenuItemRead,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(admin_only)],
    )
    def create_menu_item(payload: MenuItemCreate, db: Session = Depends(db_dependency)):
        item = MenuItem(**payload.model_dump())
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    @app.put(
        "/api/admin/menu/{item_id}",
        response_model=MenuItemRead,
        dependencies=[Depends(admin_only)],
    )
    def update_menu_item(
        item_id: int, payload: MenuItemUpdate, db: Session = Depends(db_dependency)
    ):
        item = db.scalar(
            select(MenuItem).where(
                MenuItem.id == item_id, MenuItem.is_deleted.is_(False)
            )
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Menu item not found")
        for key, value in payload.model_dump().items():
            setattr(item, key, value)
        db.commit()
        db.refresh(item)
        return item

    @app.delete(
        "/api/admin/menu/{item_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(admin_only)],
    )
    def delete_menu_item(item_id: int, db: Session = Depends(db_dependency)):
        item = db.scalar(
            select(MenuItem).where(
                MenuItem.id == item_id, MenuItem.is_deleted.is_(False)
            )
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Menu item not found")
        item.is_deleted = True
        item.is_available = False
        db.commit()

    @app.get(
        "/api/admin/waiters",
        response_model=list[UserRead],
        dependencies=[Depends(admin_only)],
    )
    def list_waiters(db: Session = Depends(db_dependency)):
        return list(
            db.scalars(
                select(User)
                .where(User.role == "waiter")
                .order_by(User.email)
            )
        )

    @app.post(
        "/api/admin/waiters",
        response_model=UserRead,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(admin_only)],
    )
    def create_waiter(payload: WaiterCreate, db: Session = Depends(db_dependency)):
        email = normalize_email(str(payload.email))
        if db.scalar(select(User.id).where(User.email == email)) is not None:
            raise HTTPException(status_code=409, detail="Email is already registered")
        waiter = User(
            email=email,
            password_hash=hash_password(payload.password),
            role="waiter",
            is_active=True,
        )
        db.add(waiter)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                status_code=409, detail="Email is already registered"
            ) from exc
        db.refresh(waiter)
        return waiter

    @app.put(
        "/api/admin/waiters/{waiter_id}",
        response_model=UserRead,
        dependencies=[Depends(admin_only)],
    )
    def update_waiter(
        waiter_id: int, payload: WaiterUpdate, db: Session = Depends(db_dependency)
    ):
        waiter = db.scalar(
            select(User).where(User.id == waiter_id, User.role == "waiter")
        )
        if waiter is None:
            raise HTTPException(status_code=404, detail="Waiter not found")
        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            raise HTTPException(status_code=422, detail="No waiter changes provided")
        if "email" in updates:
            if updates["email"] is None:
                raise HTTPException(status_code=422, detail="Email cannot be empty")
            waiter.email = normalize_email(str(updates["email"]))
        if "password" in updates:
            if updates["password"] is None:
                raise HTTPException(status_code=422, detail="Password cannot be empty")
            waiter.password_hash = hash_password(updates["password"])
        if "is_active" in updates:
            if updates["is_active"] is None:
                raise HTTPException(status_code=422, detail="Active status is required")
            waiter.is_active = updates["is_active"]
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                status_code=409, detail="Email is already registered"
            ) from exc
        db.refresh(waiter)
        return waiter

    @app.delete(
        "/api/admin/waiters/{waiter_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(admin_only)],
    )
    def deactivate_waiter(waiter_id: int, db: Session = Depends(db_dependency)):
        waiter = db.scalar(
            select(User).where(User.id == waiter_id, User.role == "waiter")
        )
        if waiter is None:
            raise HTTPException(status_code=404, detail="Waiter not found")
        waiter.is_active = False
        db.commit()

    @app.get(
        "/api/tables",
        response_model=list[TableStatusRead],
        dependencies=[Depends(authenticated)],
    )
    def list_tables(db: Session = Depends(db_dependency)):
        open_orders = {
            order.table_number: order
            for order in db.scalars(
                select(TableOrder).where(TableOrder.status == "OPEN")
            )
        }
        return [
            {
                "table_number": number,
                "status": "OCCUPIED" if number in open_orders else "EMPTY",
                "order_id": open_orders[number].id if number in open_orders else None,
                "total_amount": (
                    open_orders[number].total_amount
                    if number in open_orders
                    else 0
                ),
            }
            for number in range(1, 16)
        ]

    @app.get(
        "/api/tables/{table_number}/order",
        response_model=OrderRead | None,
        dependencies=[Depends(authenticated)],
    )
    def read_table_order(table_number: int, db: Session = Depends(db_dependency)):
        validate_table_number(table_number)
        order = get_open_order(db, table_number)
        return serialize_order(order) if order else None

    @app.get(
        "/api/tables/{table_number}/history",
        response_model=list[OrderRead],
        dependencies=[Depends(admin_only)],
    )
    def read_table_history(table_number: int, db: Session = Depends(db_dependency)):
        validate_table_number(table_number)
        orders = db.scalars(
            select(TableOrder)
            .where(
                TableOrder.table_number == table_number,
                TableOrder.status == "CLOSED",
            )
            .options(selectinload(TableOrder.items))
            .order_by(TableOrder.closed_at.desc(), TableOrder.id.desc())
        )
        return [serialize_order(order) for order in orders]

    @app.get(
        "/api/admin/bills/history",
        response_model=list[OrderRead],
        dependencies=[Depends(admin_only)],
    )
    def read_all_bill_history(db: Session = Depends(db_dependency)):
        orders = db.scalars(
            select(TableOrder)
            .where(TableOrder.status == "CLOSED")
            .options(selectinload(TableOrder.items))
            .order_by(TableOrder.closed_at.desc(), TableOrder.id.desc())
        )
        return [serialize_order(order) for order in orders]

    @app.post(
        "/api/tables/{table_number}/items",
        response_model=OrderRead,
        dependencies=[Depends(waiter_only)],
    )
    def append_items(
        table_number: int,
        payload: AddItemsRequest,
        db: Session = Depends(db_dependency),
    ):
        validate_table_number(table_number)
        item_ids = {row.menu_item_id for row in payload.items}
        menu_items = {
            item.id: item
            for item in db.scalars(
                select(MenuItem).where(
                    MenuItem.id.in_(item_ids),
                    MenuItem.is_deleted.is_(False),
                    MenuItem.is_available.is_(True),
                )
            )
        }
        if len(menu_items) != len(item_ids):
            raise HTTPException(
                status_code=409, detail="One or more items are unavailable"
            )
        order = get_or_create_open_order(db, table_number)
        add_items(
            order,
            [(menu_items[row.menu_item_id], row.quantity) for row in payload.items],
        )
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                status_code=409, detail="Table order changed; refresh and try again"
            ) from exc
        db.refresh(order)
        return serialize_order(order)

    @app.patch(
        "/api/orders/items/{item_id}",
        response_model=OrderRead,
        dependencies=[Depends(order_editor)],
    )
    def change_order_quantity(
        item_id: int,
        payload: QuantityUpdate,
        db: Session = Depends(db_dependency),
    ):
        line = db.get(OrderItem, item_id)
        if line is None:
            raise HTTPException(status_code=404, detail="Order item not found")
        order = get_order(db, line.order_id)
        if order is None or order.status != "OPEN":
            raise HTTPException(status_code=409, detail="Order is not open")
        if not update_quantity(order, item_id, payload.quantity):
            raise HTTPException(status_code=404, detail="Order item not found")
        db.commit()
        db.refresh(order)
        return serialize_order(order)

    @app.patch(
        "/api/orders/{order_id}/vat",
        response_model=OrderRead,
        dependencies=[Depends(waiter_only)],
    )
    def change_vat(
        order_id: int, payload: VatUpdate, db: Session = Depends(db_dependency)
    ):
        order = get_order(db, order_id)
        if order is None:
            raise HTTPException(status_code=404, detail="Order not found")
        if order.status != "OPEN":
            raise HTTPException(status_code=409, detail="Order is not open")
        set_vat(order, payload.enabled)
        db.commit()
        db.refresh(order)
        return serialize_order(order)

    @app.post(
        "/api/orders/{order_id}/close",
        response_model=OrderRead,
        dependencies=[Depends(admin_only)],
    )
    def settle_order(order_id: int, db: Session = Depends(db_dependency)):
        order = get_order(db, order_id)
        if order is None:
            raise HTTPException(status_code=404, detail="Order not found")
        if order.status != "OPEN":
            raise HTTPException(status_code=409, detail="Order is already closed")
        close_order(order)
        db.commit()
        db.refresh(order)
        return serialize_order(order)

    @app.get(
        "/api/orders/{order_id}",
        response_model=OrderRead,
        dependencies=[Depends(admin_only)],
    )
    def read_order_history(order_id: int, db: Session = Depends(db_dependency)):
        order = get_order(db, order_id)
        if order is None:
            raise HTTPException(status_code=404, detail="Order not found")
        return serialize_order(order)

    return app


app = create_app()
