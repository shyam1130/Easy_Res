from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import MenuItem, OrderItem, TableOrder

MONEY = Decimal("0.01")
VAT_RATE = Decimal("0.13")


def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def recalculate_order(order: TableOrder) -> None:
    order.subtotal = money(sum((item.line_total for item in order.items), Decimal("0")))
    order.vat_amount = (
        money(order.subtotal * order.vat_rate)
        if order.vat_rate is not None
        else Decimal("0.00")
    )
    order.total_amount = money(order.subtotal + order.vat_amount)


def get_open_order(db: Session, table_number: int) -> TableOrder | None:
    return db.scalar(
        select(TableOrder)
        .where(TableOrder.table_number == table_number, TableOrder.status == "OPEN")
        .options(selectinload(TableOrder.items))
    )


def get_order(db: Session, order_id: int) -> TableOrder | None:
    return db.scalar(
        select(TableOrder)
        .where(TableOrder.id == order_id)
        .options(selectinload(TableOrder.items))
    )


def get_or_create_open_order(db: Session, table_number: int) -> TableOrder:
    order = get_open_order(db, table_number)
    if order is None:
        order = TableOrder(table_number=table_number, status="OPEN")
        db.add(order)
        db.flush()
    return order


def add_items(order: TableOrder, rows: list[tuple[MenuItem, int]]) -> None:
    for menu_item, quantity in rows:
        order.items.append(
            OrderItem(
                menu_item=menu_item,
                item_name=menu_item.name,
                unit_price=menu_item.price,
                quantity=quantity,
            )
        )
    recalculate_order(order)


def update_quantity(order: TableOrder, item_id: int, quantity: int) -> bool:
    line = next((item for item in order.items if item.id == item_id), None)
    if line is None:
        return False
    if quantity == 0:
        order.items.remove(line)
    else:
        line.quantity = quantity
    recalculate_order(order)
    return True


def set_vat(order: TableOrder, enabled: bool) -> None:
    order.vat_rate = VAT_RATE if enabled else None
    recalculate_order(order)


def close_order(order: TableOrder) -> None:
    recalculate_order(order)
    order.status = "CLOSED"
    order.closed_at = datetime.now(timezone.utc)
