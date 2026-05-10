from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, model_validator


class GrummerEncryptedEnvelope(BaseModel):
    iv: str
    ciphertext: str


class CustomerPayload(BaseModel):
    email: str
    first_name: str
    last_name: str
    phone: str
    country: str


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
