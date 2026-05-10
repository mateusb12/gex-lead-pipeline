from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


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
