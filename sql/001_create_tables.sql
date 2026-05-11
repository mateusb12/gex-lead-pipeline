CREATE TABLE IF NOT EXISTS raw_payloads (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    correlation_id CHAR(36) NOT NULL,
    gateway VARCHAR(32) NOT NULL,
    received_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    headers JSON NOT NULL,
    body_original JSON NOT NULL,
    body_decrypted JSON NULL,
    error_reason TEXT NULL
);

CREATE TABLE IF NOT EXISTS webhook_idempotency_keys (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    gateway VARCHAR(32) NOT NULL,
    transaction_id VARCHAR(120) NOT NULL,
    event VARCHAR(120) NOT NULL,
    raw_payload_id BIGINT NOT NULL,
    correlation_id CHAR(36) NOT NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY uk_webhook_idempotency_gateway_transaction_event (gateway, transaction_id, event),
    CONSTRAINT fk_webhook_idempotency_raw_payload
        FOREIGN KEY (raw_payload_id) REFERENCES raw_payloads(id)
);

CREATE TABLE IF NOT EXISTS leads (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(255) NOT NULL,
    first_name VARCHAR(120) NOT NULL,
    last_name VARCHAR(120) NULL,
    phone VARCHAR(32) NULL,
    country CHAR(2) NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY uk_leads_email (email)
);

CREATE TABLE IF NOT EXISTS orders (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    lead_id BIGINT NOT NULL,
    gateway VARCHAR(32) NOT NULL,
    transaction_id VARCHAR(120) NOT NULL,
    product_id VARCHAR(120) NULL,
    product_name VARCHAR(255) NULL,
    product_niche VARCHAR(120) NULL,
    quantity INT NULL,
    amount_usd DECIMAL(12,2) NULL,
    payment_method VARCHAR(64) NULL,
    payment_status VARCHAR(64) NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY uk_orders_gateway_transaction (gateway, transaction_id),
    CONSTRAINT fk_orders_leads FOREIGN KEY (lead_id) REFERENCES leads(id)
);

CREATE TABLE IF NOT EXISTS lead_events (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    order_id BIGINT NOT NULL,
    correlation_id CHAR(36) NOT NULL,
    event VARCHAR(120) NOT NULL,
    transaction_time TIMESTAMP(6) NOT NULL,
    persisted_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    gateway_to_db_lag_seconds INT NULL,
    UNIQUE KEY uk_lead_events_order_event (order_id, event),
    CONSTRAINT fk_lead_events_orders FOREIGN KEY (order_id) REFERENCES orders(id)
);

CREATE TABLE IF NOT EXISTS distribution_status (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    order_id BIGINT NOT NULL,
    channel VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    delivered_at TIMESTAMP(6) NULL,
    db_to_channel_lag_seconds INT NULL,
    UNIQUE KEY uk_distribution_order_channel (order_id, channel),
    CONSTRAINT fk_distribution_orders FOREIGN KEY (order_id) REFERENCES orders(id)
);

CREATE TABLE IF NOT EXISTS lead_dead_letter (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    source VARCHAR(120) NOT NULL,
    reason VARCHAR(120) NOT NULL,
    payload JSON NULL,
    error_detail TEXT NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
);
