from decimal import Decimal
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints


MenuName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
MenuCategory = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
]
PositiveQuantity = Annotated[int, Field(gt=0, le=999)]
Price = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)]
DisplayName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]


class MenuItemCreate(BaseModel):
    name: MenuName
    category: MenuCategory
    price: Price
    is_available: bool = True


class MenuItemUpdate(MenuItemCreate):
    pass


class MenuItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str
    price: Decimal
    is_available: bool


class LoginRequest(BaseModel):
    email: EmailStr
    password: Annotated[str, StringConstraints(min_length=1, max_length=128)]


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    name: str | None
    role: Literal["admin", "waiter"]
    is_active: bool
    created_at: datetime


class LoginResponse(BaseModel):
    token: str
    user: UserRead


class WaiterCreate(BaseModel):
    name: DisplayName
    email: EmailStr
    password: Annotated[str, StringConstraints(min_length=8, max_length=128)]


class WaiterUpdate(BaseModel):
    name: DisplayName | None = None
    email: EmailStr | None = None
    password: Annotated[str, StringConstraints(min_length=8, max_length=128)] | None = None
    is_active: bool | None = None


class OrderLineCreate(BaseModel):
    menu_item_id: int = Field(gt=0)
    quantity: PositiveQuantity


class AddItemsRequest(BaseModel):
    items: Annotated[list[OrderLineCreate], Field(min_length=1, max_length=100)]


class QuantityUpdate(BaseModel):
    quantity: Annotated[int, Field(ge=0, le=999)]


class VatUpdate(BaseModel):
    enabled: bool


class OrderItemRead(BaseModel):
    id: int
    menu_item_id: int | None
    item_name: str
    unit_price: Decimal
    quantity: int
    line_total: Decimal


class OrderRead(BaseModel):
    id: int
    table_number: int
    status: Literal["OPEN", "CLOSED"]
    vat_rate: Decimal | None
    items: list[OrderItemRead]
    subtotal: Decimal
    vat_amount: Decimal
    total_amount: Decimal
    opened_at: str
    closed_at: str | None


class TableStatusRead(BaseModel):
    table_number: int
    status: Literal["EMPTY", "OCCUPIED"]
    order_id: int | None
    total_amount: Decimal
