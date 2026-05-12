# EXPLAIN ANALYZE — Queries de auditoria

Os planos abaixo foram gerados depois de uma carga fresh dos 200 payloads do benchmark do projeto. Os tempos podem variar um pouco conforme a máquina e a execução. No dataset fornecido, todas as queries ficaram abaixo de 1 segundo. O resumo executivo continua em `docs/explicacao_tecnica.md`.

## 1. Lag médio SMS por gateway

Referência: bloco 1 de `sql/audit_queries.sql`.

```sql
EXPLAIN ANALYZE
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
```

```text
-> Sort: o.gateway  (actual time=0.344..0.344 rows=2 loops=1)
    -> Table scan on <temporary>  (actual time=0.328..0.328 rows=2 loops=1)
        -> Aggregate using temporary table  (actual time=0.327..0.327 rows=2 loops=1)
            -> Nested loop inner join  (cost=6 rows=3.75) (actual time=0.0498..0.262 rows=50 loops=1)
                -> Nested loop inner join  (cost=4.69 rows=3.75) (actual time=0.0448..0.162 rows=50 loops=1)
                    -> Filter: ((ds.`channel` = 'SMS') and (ds.delivered_at is not null) and (ds.delivered_at >= <cache>((utc_timestamp() - interval 24 hour))))  (cost=3.37 rows=3.75) (actual time=0.0356..0.0934 rows=50 loops=1)
                        -> Index lookup on ds using idx_distribution_status_status_created (status='delivered')  (cost=3.37 rows=50) (actual time=0.0247..0.0672 rows=50 loops=1)
                    -> Single-row index lookup on o using PRIMARY (id=ds.order_id)  (cost=0.277 rows=1) (actual time=0.00116..0.00118 rows=1 loops=50)
                -> Single-row index lookup on le using uk_lead_events_order_event (order_id=ds.order_id, event='order.approved')  (cost=0.277 rows=1) (actual time=0.00184..0.00186 rows=1 loops=50)
```

O plano começa pelos status `delivered`, reduz para SMS entregue nas últimas 24h e depois busca o pedido e o evento aprovado de cada linha. A agregação por gateway acontece só no fim, em cima de 50 entregas.

## 2. Pending há mais de 5 minutos

Referência: bloco 2 de `sql/audit_queries.sql`.

### 2.1 Resumo dos pendentes

```sql
EXPLAIN ANALYZE
SELECT
    COUNT(*) AS total_pending_channels_over_5_min,
    COUNT(DISTINCT ds.order_id) AS total_orders_with_pending_over_5_min
FROM distribution_status ds
WHERE ds.status = 'pending'
  AND ds.created_at <= UTC_TIMESTAMP() - INTERVAL 5 MINUTE;
```

```text
-> Aggregate: count(0), count(distinct ds.order_id)  (cost=0.81 rows=1) (actual time=0.0125..0.0126 rows=1 loops=1)
    -> Index range scan on ds using idx_distribution_status_status_created over (status = 'pending' AND created_at <= '2026-05-12 18:08:47.000000'), with index condition: ((ds.`status` = 'pending') and (ds.created_at <= <cache>((utc_timestamp() - interval 5 minute))))  (cost=0.71 rows=1) (actual time=0.0116..0.0116 rows=0 loops=1)
```

O resumo usa diretamente o índice `(status, created_at)`. Nesta coleta não havia canais pendentes com mais de 5 minutos, então o range scan terminou sem retornar linhas.

### 2.2 Listagem dos pendentes

```sql
EXPLAIN ANALYZE
SELECT
    ds.order_id,
    ds.channel,
    TIMESTAMPDIFF(SECOND, ds.created_at, UTC_TIMESTAMP()) AS pending_age_seconds
FROM distribution_status ds
WHERE ds.status = 'pending'
  AND ds.created_at <= UTC_TIMESTAMP() - INTERVAL 5 MINUTE
ORDER BY pending_age_seconds DESC, ds.order_id, ds.channel;
```

```text
-> Sort: pending_age_seconds DESC, ds.order_id, ds.`channel`  (cost=0.71 rows=1) (actual time=0.0136..0.0136 rows=0 loops=1)
    -> Index range scan on ds using idx_distribution_status_status_created over (status = 'pending' AND created_at <= '2026-05-12 18:08:47.000000'), with index condition: ((ds.`status` = 'pending') and (ds.created_at <= <cache>((utc_timestamp() - interval 5 minute))))  (cost=0.71 rows=1) (actual time=0.0103..0.0103 rows=0 loops=1)
```

A listagem reaproveita o mesmo range scan e só adiciona a ordenação da saída. Como o filtro não encontrou pendências antigas, o sort também trabalhou sobre zero linhas.

## 3. Taxa de sucesso de SMS por produto/hora

Referência: bloco 3 de `sql/audit_queries.sql`.

```sql
EXPLAIN ANALYZE
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
```

```text
-> Sort: hour_bucket_utc DESC, o.product_name  (actual time=0.589..0.59 rows=12 loops=1)
    -> Table scan on <temporary>  (actual time=0.574..0.576 rows=12 loops=1)
        -> Aggregate using temporary table  (actual time=0.573..0.573 rows=12 loops=1)
            -> Nested loop inner join  (cost=23.2 rows=45) (actual time=0.038..0.356 rows=135 loops=1)
                -> Filter: (ds.created_at >= <cache>((utc_timestamp() - interval 6 hour)))  (cost=7.5 rows=45) (actual time=0.0269..0.184 rows=135 loops=1)
                    -> Index lookup on ds using idx_distribution_status_channel_status_delivered (channel='SMS')  (cost=7.5 rows=135) (actual time=0.0249..0.159 rows=135 loops=1)
                -> Single-row index lookup on o using PRIMARY (id=ds.order_id)  (cost=0.252 rows=1) (actual time=0.00113..0.00115 rows=1 loops=135)
```

O MySQL começa pelas linhas de `distribution_status` do canal SMS, aplica a janela de 6 horas e busca o pedido correspondente por chave primária. Depois monta a tabela temporária para agrupar por hora e produto.

## 4. DLQ por motivo

Referência: bloco 4 de `sql/audit_queries.sql`.

```sql
EXPLAIN ANALYZE
SELECT
    ldl.reason,
    COUNT(*) AS total_dlq_entries,
    MIN(ldl.created_at) AS first_seen_at,
    MAX(ldl.created_at) AS last_seen_at
FROM lead_dead_letter ldl
WHERE ldl.created_at >= UTC_TIMESTAMP() - INTERVAL 24 HOUR
GROUP BY ldl.reason
ORDER BY total_dlq_entries DESC, ldl.reason;
```

```text
-> Sort: total_dlq_entries DESC, ldl.reason  (actual time=0.0687..0.0688 rows=2 loops=1)
    -> Stream results  (cost=3.58 rows=2) (actual time=0.0425..0.0586 rows=2 loops=1)
        -> Group aggregate: count(0), min(ldl.created_at), max(ldl.created_at)  (cost=3.58 rows=2) (actual time=0.0336..0.0484 rows=2 loops=1)
            -> Filter: (ldl.created_at >= <cache>((utc_timestamp() - interval 24 hour)))  (cost=2.42 rows=11.7) (actual time=0.0188..0.0325 rows=35 loops=1)
                -> Covering index scan on ldl using idx_lead_dead_letter_reason_created  (cost=2.42 rows=35) (actual time=0.0107..0.0201 rows=35 loops=1)
```

Essa query roda só sobre o índice `(reason, created_at)`, sem precisar voltar à tabela. O agrupamento consolida as 35 entradas de DLQ em dois motivos.

## 5. Reconciliação approved vs SMS

Referência: bloco 5 de `sql/audit_queries.sql`.

```sql
EXPLAIN ANALYZE
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
```

```text
-> Sort: daily_reconciliation.event_day DESC  (cost=2.6..2.6 rows=0) (actual time=0.547..0.547 rows=1 loops=1)
    -> Table scan on daily_reconciliation  (cost=2.5..2.5 rows=0) (actual time=0.539..0.539 rows=1 loops=1)
        -> Materialize CTE daily_reconciliation  (cost=0..0 rows=0) (actual time=0.539..0.539 rows=1 loops=1)
            -> Table scan on <temporary>  (actual time=0.521..0.521 rows=1 loops=1)
                -> Aggregate using temporary table  (actual time=0.52..0.52 rows=1 loops=1)
                    -> Nested loop left join  (cost=61 rows=135) (actual time=0.0261..0.437 rows=135 loops=1)
                        -> Filter: ((le.`event` = 'order.approved') and (le.persisted_at >= <cache>((utc_date() - interval 6 day))))  (cost=13.8 rows=135) (actual time=0.0162..0.0974 rows=135 loops=1)
                            -> Covering index scan on le using idx_lead_events_event_persisted_order  (cost=13.8 rows=135) (actual time=0.0129..0.0507 rows=135 loops=1)
                        -> Single-row index lookup on ds using uk_distribution_order_channel (order_id=le.order_id, channel='SMS')  (cost=0.251 rows=1) (actual time=0.00237..0.00239 rows=1 loops=135)
```

O CTE parte dos eventos `order.approved` recentes usando o índice de `lead_events`. Para cada pedido, a query consulta no máximo uma linha SMS em `distribution_status`, agrega por dia e só depois calcula o gap final.
