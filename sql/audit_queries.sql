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

-- 2. Leads/canais em pending há mais de 5 minutos.
-- Primeiro mostra o total; depois lista order_id, canal e idade do pendente.

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
