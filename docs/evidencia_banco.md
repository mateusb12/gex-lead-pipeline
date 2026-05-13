# Evidência textual do banco

Esta evidência foi gerada em **2026-05-12 23:50:18 -03** a partir do MySQL local em execução no ambiente `docker compose`.

Ela registra comandos e saídas reais de terminal. Não é screenshot nem print literal de interface gráfica.

## Estado dos containers

Comando executado:

```bash
docker compose ps
```

Saída observada:

```text
NAME                  IMAGE                               COMMAND                  SERVICE           CREATED       STATUS                 PORTS
gex-api               gex-lead-pipeline-api               "uvicorn source.main…"   api               8 hours ago   Up 8 hours             0.0.0.0:8000->8000/tcp, [::]:8000->8000/tcp
gex-mysql             mysql:8.4                           "docker-entrypoint.s…"   mysql             8 hours ago   Up 8 hours (healthy)   0.0.0.0:3306->3306/tcp, [::]:3306->3306/tcp, 33060/tcp
gex-rabbitmq          rabbitmq:3-management               "docker-entrypoint.s…"   rabbitmq          8 hours ago   Up 8 hours (healthy)   4369/tcp, 5671/tcp, 0.0.0.0:5672->5672/tcp, [::]:5672->5672/tcp, 15671/tcp, 15691-15692/tcp, 25672/tcp, 0.0.0.0:15672->15672/tcp, [::]:15672->15672/tcp
gex-sms-distributor   gex-lead-pipeline-sms-distributor   "watchfiles 'python …"   sms-distributor   8 hours ago   Up 8 hours
gex-worker            gex-lead-pipeline-worker            "watchfiles 'python …"   worker            8 hours ago   Up 8 hours
```

## Contagens e DLQ por motivo

Comando executado:

```bash
docker exec gex-mysql mysql -ugex -pgex gex_pipeline -e "SELECT COUNT(*) AS raw_payloads FROM raw_payloads; SELECT COUNT(*) AS leads FROM leads; SELECT COUNT(*) AS orders_count FROM orders; SELECT COUNT(*) AS lead_events FROM lead_events; SELECT COUNT(*) AS distribution_status FROM distribution_status; SELECT reason, COUNT(*) AS total FROM lead_dead_letter GROUP BY reason ORDER BY reason;"
```

Saída observada:

```text
mysql: [Warning] Using a password on the command line interface can be insecure.
raw_payloads
200
leads
125
orders_count
135
lead_events
135
distribution_status
540
reason  total
decrypt_failed  15
schema_failed   20
sms_delivery_failed 85
```

## Amostras de `orders`, `lead_events` e `distribution_status`

Comando executado:

```bash
docker exec gex-mysql mysql -ugex -pgex gex_pipeline -e "SELECT id, gateway, transaction_id, product_name, payment_status FROM orders ORDER BY id LIMIT 5; SELECT id, order_id, event, gateway_to_db_lag_seconds FROM lead_events ORDER BY id LIMIT 5; SELECT order_id, channel, status, delivered_at, db_to_channel_lag_seconds FROM distribution_status ORDER BY order_id, channel LIMIT 12;"
```

Saída observada:

```text
mysql: [Warning] Using a password on the command line interface can be insecure.
id  gateway  transaction_id  product_name      payment_status
1   lous     ORD-2026-010015  Slim Pro          approved
2   lous     ORD-2026-010007  Brain Boost       approved
3   grummer  ORD-2026-010068  Fit Burn          approved
4   lous     ORD-2026-010028  Derma Essential   approved
5   grummer  ORD-2026-010050  Heart Calm        approved
id  order_id  event           gateway_to_db_lag_seconds
1   1         order.approved  936759
2   2         order.approved  814539
3   3         order.approved  990733
4   4         order.approved  670352
5   5         order.approved  767449
order_id  channel      status     delivered_at                 db_to_channel_lag_seconds
1         CALL_CENTER  pending    NULL                         NULL
1         EMAIL        pending    NULL                         NULL
1         SMS          delivered  2026-05-12 18:36:40.495841   1
1         WHATSAPP     pending    NULL                         NULL
2         CALL_CENTER  pending    NULL                         NULL
2         EMAIL        pending    NULL                         NULL
2         SMS          delivered  2026-05-12 18:36:40.991002   1
2         WHATSAPP     pending    NULL                         NULL
3         CALL_CENTER  pending    NULL                         NULL
3         EMAIL        pending    NULL                         NULL
3         SMS          delivered  2026-05-12 18:36:41.427480   2
3         WHATSAPP     pending    NULL                         NULL
```
