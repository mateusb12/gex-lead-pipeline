import re
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, field_validator, model_validator

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class GrummerEncryptedEnvelope(BaseModel):
    iv: str
    ciphertext: str


class CustomerPayload(BaseModel):
    email: str
    first_name: str = "Customer"
    last_name: str
    phone: str
    country: str
    phone_is_valid: bool = True

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: Any) -> str:
        return str(value).strip().lower()

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        if not EMAIL_PATTERN.match(value):
            raise ValueError("invalid email format")

        return value

    @field_validator("first_name", mode="before")
    @classmethod
    def normalize_first_name(cls, value: Any) -> str:
        if value is None:
            return "Customer"

        normalized = str(value).strip()

        if not normalized:
            return "Customer"

        return normalized

    @field_validator("last_name", mode="before")
    @classmethod
    def normalize_last_name(cls, value: Any) -> str:
        return str(value).strip()

    @field_validator("country", mode="before")
    @classmethod
    def normalize_country(cls, value: Any) -> str:
        return str(value).strip().upper()

    @model_validator(mode="after")
    def normalize_phone(self) -> "CustomerPayload":
        normalized_phone, is_valid = normalize_phone_number(self.phone)
        self.phone = normalized_phone
        self.phone_is_valid = is_valid

        return self


class ProductPayload(BaseModel):
    id: str
    name: str
    niche: str


class PaymentPayload(BaseModel):
    amount_usd: Decimal
    method: str
    status: Literal["approved", "declined", "pending", "refunded"]


class SalesEventPayload(BaseModel):
    transaction_id: str
    transaction_time: datetime
    event: str
    customer: CustomerPayload
    product: ProductPayload
    quantity: int
    payment: PaymentPayload

    @model_validator(mode="before")
    @classmethod
    def normalize_quantity_location(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        if data.get("quantity") is not None:
            return data

        product = data.get("product")

        if not isinstance(product, dict):
            return data

        product_quantity = product.get("quantity")

        if product_quantity is None:
            return data

        return {
            **data,
            "quantity": product_quantity,
        }


def normalize_phone_number(value: Any) -> tuple[str, bool]:
    raw_phone = str(value).strip()
    has_leading_plus = raw_phone.startswith("+")

    digits = re.sub(r"\D", "", raw_phone)

    if not digits:
        return "", False

    normalized_phone = f"+{digits}" if has_leading_plus or len(digits) >= 8 else digits
    is_valid = 8 <= len(digits) <= 15

    return normalized_phone, is_valid
