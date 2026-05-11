from sqlalchemy import BigInteger, CHAR, JSON, Column, ForeignKey, Integer, MetaData, Numeric, String, Table, Text, UniqueConstraint
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

leads = Table(
    "leads",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("email", String(255), nullable=False),
    Column("first_name", String(120), nullable=False),
    Column("last_name", String(120), nullable=True),
    Column("phone", String(32), nullable=True),
    Column("country", CHAR(2), nullable=True),
    Column("created_at", TIMESTAMP(fsp=6), nullable=False),
    UniqueConstraint("email", name="uk_leads_email"),
)

orders = Table(
    "orders",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("lead_id", BigInteger, ForeignKey("leads.id"), nullable=False),
    Column("gateway", String(32), nullable=False),
    Column("transaction_id", String(120), nullable=False),
    Column("product_id", String(120), nullable=True),
    Column("product_name", String(255), nullable=True),
    Column("product_niche", String(120), nullable=True),
    Column("quantity", Integer, nullable=True),
    Column("amount_usd", Numeric(12, 2), nullable=True),
    Column("payment_method", String(64), nullable=True),
    Column("payment_status", String(64), nullable=True),
    Column("created_at", TIMESTAMP(fsp=6), nullable=False),
    UniqueConstraint("gateway", "transaction_id", name="uk_orders_gateway_transaction"),
)

lead_events = Table(
    "lead_events",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("order_id", BigInteger, ForeignKey("orders.id"), nullable=False),
    Column("correlation_id", CHAR(36), nullable=False),
    Column("event", String(120), nullable=False),
    Column("transaction_time", TIMESTAMP(fsp=6), nullable=False),
    Column("persisted_at", TIMESTAMP(fsp=6), nullable=False),
    Column("gateway_to_db_lag_seconds", Integer, nullable=True),
    UniqueConstraint("order_id", "event", name="uk_lead_events_order_event"),
)

distribution_status = Table(
    "distribution_status",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("order_id", BigInteger, ForeignKey("orders.id"), nullable=False),
    Column("channel", String(32), nullable=False),
    Column("status", String(32), nullable=False),
    Column("created_at", TIMESTAMP(fsp=6), nullable=False),
    Column("delivered_at", TIMESTAMP(fsp=6), nullable=True),
    Column("db_to_channel_lag_seconds", Integer, nullable=True),
    UniqueConstraint("order_id", "channel", name="uk_distribution_order_channel"),
)

lead_dead_letter = Table(
    "lead_dead_letter",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("source", String(120), nullable=False),
    Column("reason", String(120), nullable=False),
    Column("payload", JSON(none_as_null=True), nullable=True),
    Column("error_detail", Text, nullable=True),
    Column("created_at", TIMESTAMP(fsp=6), nullable=False),
)
