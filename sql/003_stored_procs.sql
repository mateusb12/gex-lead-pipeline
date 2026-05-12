DELIMITER //

DROP PROCEDURE IF EXISTS sp_insert_lead//

CREATE PROCEDURE sp_insert_lead(
    IN p_email VARCHAR(255),
    IN p_first_name VARCHAR(120),
    IN p_last_name VARCHAR(120),
    IN p_phone VARCHAR(32),
    IN p_country CHAR(2),
    IN p_gateway VARCHAR(32),
    IN p_transaction_id VARCHAR(120),
    IN p_product_id VARCHAR(120),
    IN p_product_name VARCHAR(255),
    IN p_product_niche VARCHAR(120),
    IN p_quantity INT,
    IN p_amount_usd DECIMAL(12, 2),
    IN p_payment_method VARCHAR(64),
    IN p_payment_status VARCHAR(64),
    IN p_correlation_id CHAR(36),
    IN p_event VARCHAR(120),
    IN p_transaction_time TIMESTAMP(6),
    IN p_persisted_at TIMESTAMP(6),
    IN p_gateway_to_db_lag_seconds INT
)
BEGIN
    DECLARE v_lead_id BIGINT;
    DECLARE v_order_id BIGINT;
    DECLARE v_lead_event_id BIGINT;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    START TRANSACTION;

    INSERT INTO leads (
        email,
        first_name,
        last_name,
        phone,
        country
    )
    VALUES (
        p_email,
        p_first_name,
        p_last_name,
        p_phone,
        p_country
    )
    ON DUPLICATE KEY UPDATE
        id = LAST_INSERT_ID(id),
        first_name = p_first_name,
        last_name = p_last_name,
        phone = p_phone,
        country = p_country;

    SET v_lead_id = LAST_INSERT_ID();

    INSERT INTO orders (
        lead_id,
        gateway,
        transaction_id,
        product_id,
        product_name,
        product_niche,
        quantity,
        amount_usd,
        payment_method,
        payment_status
    )
    VALUES (
        v_lead_id,
        p_gateway,
        p_transaction_id,
        p_product_id,
        p_product_name,
        p_product_niche,
        p_quantity,
        p_amount_usd,
        p_payment_method,
        p_payment_status
    )
    ON DUPLICATE KEY UPDATE
        id = LAST_INSERT_ID(id),
        lead_id = v_lead_id,
        product_id = p_product_id,
        product_name = p_product_name,
        product_niche = p_product_niche,
        quantity = p_quantity,
        amount_usd = p_amount_usd,
        payment_method = p_payment_method,
        payment_status = p_payment_status;

    SET v_order_id = LAST_INSERT_ID();

    INSERT INTO lead_events (
        order_id,
        correlation_id,
        event,
        transaction_time,
        persisted_at,
        gateway_to_db_lag_seconds
    )
    VALUES (
        v_order_id,
        p_correlation_id,
        p_event,
        p_transaction_time,
        p_persisted_at,
        p_gateway_to_db_lag_seconds
    )
    ON DUPLICATE KEY UPDATE
        id = LAST_INSERT_ID(id),
        correlation_id = p_correlation_id,
        transaction_time = p_transaction_time,
        persisted_at = p_persisted_at,
        gateway_to_db_lag_seconds = p_gateway_to_db_lag_seconds;

    SET v_lead_event_id = LAST_INSERT_ID();

    COMMIT;

    SELECT
        v_lead_id AS lead_id,
        v_order_id AS order_id,
        v_lead_event_id AS lead_event_id;
END//

DELIMITER ;
