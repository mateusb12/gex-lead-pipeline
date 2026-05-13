-- 1. Lag médio entre transaction_time do gateway e delivered_at em SMS,
-- agrupado por gateway, nas últimas 24h.

SELECT
    o.gateway,
    ROUND(
        AVG(TIMESTAMPDIFF(SECOND, le.transaction_time, ds.delivered_at)),
        2
    ) AS avg_gateway_to_sms_lag_seconds,
    COUNT(*) AS delivered_sms_count
FROM distribution_status ds
JOIN orders o
    ON o.id = ds.order_id
JOIN lead_events le
    ON le.order_id = o.id
WHERE ds.channel = 'SMS'
  AND ds.status = 'delivered'
  AND ds.delivered_at IS NOT NULL
  AND ds.delivered_at >= UTC_TIMESTAMP() - INTERVAL 24 HOUR
  AND le.event = 'order.approved'
GROUP BY o.gateway
ORDER BY o.gateway;

-- 2. Pendências por canal em distribution_status há mais de 5 minutos.
-- Cada linha pendente pertence a um order_id + channel; o total por pedido aparece em coluna separada.

SELECT
    COUNT(*) AS total_pending_channels_over_5_min,
    COUNT(DISTINCT ds.order_id) AS total_orders_with_pending_over_5_min
FROM distribution_status ds
WHERE ds.status = 'pending'
  AND ds.created_at <= UTC_TIMESTAMP() - INTERVAL 5 MINUTE;

SELECT
    ds.order_id,
    ds.channel,
    TIMESTAMPDIFF(SECOND, ds.created_at, UTC_TIMESTAMP()) AS pending_age_seconds
FROM distribution_status ds
WHERE ds.status = 'pending'
  AND ds.created_at <= UTC_TIMESTAMP() - INTERVAL 5 MINUTE
ORDER BY pending_age_seconds DESC, ds.order_id, ds.channel;

-- 3. Taxa de sucesso de SMS por produto, por hora, nas últimas 6h.
-- A hora usada é a criação do status de distribuição, para incluir delivered e pending no denominador.

SELECT
    DATE_FORMAT(ds.created_at, '%Y-%m-%d %H:00:00') AS hour_bucket_utc,
    o.product_id,
    o.product_name,
    COUNT(*) AS total_sms,
    SUM(CASE WHEN ds.status = 'delivered' THEN 1 ELSE 0 END) AS delivered_sms,
    ROUND(
        100 * SUM(CASE WHEN ds.status = 'delivered' THEN 1 ELSE 0 END) / COUNT(*),
        2
    ) AS sms_success_rate_percent
FROM distribution_status ds
JOIN orders o
    ON o.id = ds.order_id
WHERE ds.channel = 'SMS'
  AND ds.created_at >= UTC_TIMESTAMP() - INTERVAL 6 HOUR
GROUP BY
    hour_bucket_utc,
    o.product_id,
    o.product_name
ORDER BY
    hour_bucket_utc DESC,
    o.product_name;

-- 4. Leads/entradas em DLQ por motivo, nas últimas 24h.

SELECT
    ldl.reason,
    COUNT(*) AS total_dlq_entries,
    MIN(ldl.created_at) AS first_seen_at,
    MAX(ldl.created_at) AS last_seen_at
FROM lead_dead_letter ldl
WHERE ldl.created_at >= UTC_TIMESTAMP() - INTERVAL 24 HOUR
GROUP BY ldl.reason
ORDER BY total_dlq_entries DESC, ldl.reason;

-- 5. Reconciliação: aprovados em lead_events vs delivered em SMS,
-- por dia, nos últimos 7 dias.
-- Usa persisted_at como data de reconciliação para comparar o mesmo cohort aprovado.

WITH daily_reconciliation AS (
    SELECT
        DATE(le.persisted_at) AS event_day,
        COUNT(*) AS approved_leads,
        SUM(CASE WHEN ds.status = 'delivered' THEN 1 ELSE 0 END) AS sms_delivered
    FROM lead_events le
    LEFT JOIN distribution_status ds
        ON ds.order_id = le.order_id
       AND ds.channel = 'SMS'
    WHERE le.event = 'order.approved'
      AND le.persisted_at >= UTC_DATE() - INTERVAL 6 DAY
    GROUP BY DATE(le.persisted_at)
)
SELECT
    event_day,
    approved_leads,
    sms_delivered,
    approved_leads - sms_delivered AS absolute_gap,
    ROUND(
        100 * (approved_leads - sms_delivered) / NULLIF(approved_leads, 0),
        2
    ) AS gap_percent
FROM daily_reconciliation
ORDER BY event_day DESC;
