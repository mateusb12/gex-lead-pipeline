CREATE INDEX idx_raw_payloads_gateway_received
    ON raw_payloads (gateway, received_at);

CREATE INDEX idx_lead_dead_letter_reason_created
    ON lead_dead_letter (reason, created_at);

CREATE INDEX idx_distribution_status_status_created
    ON distribution_status (status, created_at);

CREATE INDEX idx_distribution_status_channel_status_delivered
    ON distribution_status (channel, status, delivered_at, order_id);
