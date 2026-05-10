from sqlalchemy import BigInteger, CHAR, JSON, Column, MetaData, String, Table, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import TIMESTAMP

metadata = MetaData()

raw_payloads = Table(
    "raw_payloads",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("correlation_id", CHAR(36), nullable=False),
    Column("gateway", String(32), nullable=False),
    Column("received_at", TIMESTAMP(fsp=6), nullable=False),
    Column("headers", JSON(none_as_null=True), nullable=False),
    Column("body_original", JSON(none_as_null=True), nullable=False),
    Column("body_decrypted", JSON(none_as_null=True), nullable=True),
    Column("error_reason", Text, nullable=True),
)

webhook_idempotency_keys = Table(
    "webhook_idempotency_keys",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("gateway", String(32), nullable=False),
    Column("transaction_id", String(120), nullable=False),
    Column("event", String(120), nullable=False),
    Column("raw_payload_id", BigInteger, nullable=False),
    Column("correlation_id", CHAR(36), nullable=False),
    Column("created_at", TIMESTAMP(fsp=6), nullable=False),
    UniqueConstraint(
        "gateway",
        "transaction_id",
        "event",
        name="uk_webhook_idempotency_gateway_transaction_event",
    ),
)

