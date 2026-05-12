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
