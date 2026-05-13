# Conceitual — Parte A: Resolução de incidente

## Diagnóstico inicial

O gateway reporta **1.587 vendas aprovadas** na sexta-feira, mas o sistema tem apenas **421 `lead_events` com `event = 'order.approved'`** e o call center está sem leads há 4 horas. Eu não começaria reiniciando serviço nem reprocessando no desespero. Antes disso, congelaria a janela exata da comparação: timezone, gateway, critério de “approved” e se o recorte usa `transaction_time` ou horário de processamento.

Essa distinção importa. `transaction_time` representa quando a venda aconteceu; `received_at` mostra quando o nosso receiver recebeu algo. Se cada lado estiver olhando um relógio diferente, dá para transformar atraso operacional em falso buraco de vendas.

O funil a reconciliar é:

```text
gateway -> receiver -> raw_payloads -> decrypt/schema/idempotência
-> lead.received -> Lead Worker -> lead_events/distribution_status -> canal
```

![Entrada do receiver](./pictures/01-receiver-entrada.png)

Esse é o primeiro trecho que eu isolaria: se o bruto não chegou em raw_payloads, o problema está antes de worker, DLQ ou distribuição.

`raw_payloads` é o primeiro checkpoint persistente da esteira. Já `lead_events` só aparece depois que o Lead Worker consome a fila, resolve o pedido e grava o evento. Então `lead_events` baixo não autoriza culpar o worker de saída; o problema pode ter morrido bem antes dele.

## Cinco hipóteses ranqueadas

1. **O receiver ou a infra falhou antes/durante `raw_payloads`**. Se o bruto recebido também estiver perto de 421, o gap nasceu antes da fila. Nesse caso eu olho endpoint, API gateway, rede e insert inicial em banco antes de gastar tempo com consumer.
2. **O gateway nunca enviou tudo ou enviou para endpoint incorreto**. Essa hipótese fica forte quando faltam requests nos logs HTTP, não existe `correlation_id` e `raw_payloads` também não mostra os ausentes. A validação depende de logs do gateway e de replay controlado dos `transaction_id` faltantes.
3. **A comparação usa janela, timezone ou filtro diferente**. É uma hipótese chata, mas barata e plausível. Um dashboard contando por `transaction_time` pode não bater com uma query interna por `received_at`, e “approved” no dashboard também pode não significar exatamente `event = 'order.approved'`.
4. **Falha em massa de `decrypt_failed` ou `schema_failed`**. Se `raw_payloads` estiver alto, mas `lead_events` continuar em 421, eu abro `lead_dead_letter` antes de culpar o worker. Decrypt e schema acontecem antes da publicação em `lead.received`; se morrer ali, nunca houve chance de virar lead.

![Validação, decrypt e DLQ](./pictures/02-validacao-decrypt-dlq.png)

Se a massa está em raw_payloads mas morre em decrypt/schema, o Lead Worker nem chegou a participar do incidente.

5. **Worker ou distribuição travados**. `lead.received` acumulada explica `lead_events` baixo. Já filas de canal ou `distribution_status` pendente explicam call center sem leads quando o evento de negócio foi criado, mas a entrega posterior não andou.

## Dados, queries e RabbitMQ

Eu compararia poucos checkpoints fortes, sempre prendendo a mesma janela temporal:

```sql
SELECT
    COUNT(*) AS total_raw,
    MIN(received_at) AS first_received_at,
    MAX(received_at) AS last_received_at
FROM raw_payloads
WHERE received_at >= '2026-05-08 00:00:00'
  AND received_at < '2026-05-09 00:00:00';
```

Essa primeira leitura não fecha a reconciliação final com o gateway, mas diz se a massa de webhooks sequer entrou no sistema. Para comparar venda com venda, eu volto a `transaction_time`; para entender chegada operacional, `received_at` é a métrica certa.

```sql
SELECT reason, source, COUNT(*) AS total
FROM lead_dead_letter
WHERE created_at >= '2026-05-08 00:00:00'
  AND created_at < '2026-05-09 00:00:00'
GROUP BY reason, source
ORDER BY total DESC;
```

```sql
SELECT o.gateway, COUNT(*) AS approved_events
FROM lead_events le
JOIN orders o ON o.id = le.order_id
WHERE le.event = 'order.approved'
  AND le.transaction_time >= '2026-05-08 00:00:00'
  AND le.transaction_time < '2026-05-09 00:00:00'
GROUP BY o.gateway;
```

```sql
SELECT
    COUNT(*) AS pending_channels,
    COUNT(DISTINCT order_id) AS pending_orders
FROM distribution_status
WHERE status = 'pending'
  AND created_at <= UTC_TIMESTAMP() - INTERVAL 5 MINUTE;
```

No RabbitMQ:

```bash
rabbitmqctl list_queues name messages_ready messages_unacknowledged consumers
```

Leitura esperada:

```text
lead.received ready alta + consumers = 0 -> consumer parado
lead.received unacked alta -> consumer travado/lento
lead.dead.decrypt_failed ou lead.dead.schema_failed alta -> falha antes do worker
dist.callcenter/dist.sms alta -> distribuição travada
```

Se as filas estiverem baixas e `raw_payloads` também, eu volto para gateway/receiver. Se `raw_payloads` estiver alto e `lead_dead_letter` concentrar `decrypt_failed` ou `schema_failed`, o worker ainda nem entrou na história. Essa leitura evita investigar a etapa errada por pressão do incidente.

![Fila lead.received e Lead Worker](./pictures/04-rabbit-lead-worker.png)

Quando lead.received acumula, a investigação muda de receiver para consumo, persistência e retry do Lead Worker.

## Como diferenciar os quatro cenários

| Cenário | Sinais | Ação imediata |
|---|---|---|
| Gateway nunca enviou | `raw_payloads` baixo, logs HTTP sem as requests, DLQ baixa | pedir logs/replay dos `transaction_id` ausentes |
| Webhook chegou, mas decrypt falhou | bruto salvo, `body_decrypted` nulo, `decrypt_failed` em DLQ | validar secret, IV/ciphertext, header e mudança de contrato |
| `lead.received` acumulada / consumer travado | bruto alto, DLQ de entrada baixa, fila pronta ou unacked alta, `lead_events` baixo | inspecionar worker, conexão com MySQL, exceções e retry |
| Distribuidor/canal travado | `lead_events` alto, `distribution_status` pending antigo, fila do canal acumulada | investigar o canal específico; isso explica ausência no call center, não o gap de `lead_events` |

## Reprocessamento sem duplicar os 421

Eu classificaria os 1.166 faltantes antes de publicar qualquer replay.

- **Gateway nunca enviou**: solicitar replay controlado apenas dos `transaction_id` ausentes, reconciliados por `gateway + transaction_id + event`.
- **`decrypt_failed`**: corrigir segredo/formato e reprocessar somente os itens identificados pela DLQ/lote auditável que voltarem a ser decriptáveis.
- **`schema_failed`**: separar erro de contrato real de payload inválido; corrigir mapeamento quando houve mudança válida ou pedir novo envio ao gateway. Só republicar payload parseável e elegível.
- **`lead.received` acumulada / consumer travado**: recuperar o consumer e deixar a fila drenar; reenfileirar apenas mensagens comprovadamente perdidas, não tudo.
- **Distribuidor/canal travado**: reprocessar a fila do canal ou os pendentes do canal, sem recriar `lead_events`.

A proteção contra duplicidade continua a mesma:

```text
webhook_idempotency_keys: gateway + transaction_id + event
lead_events: order_id + event
distribution_status: order_id + channel
```

Para o replay dos ausentes, eu materializaria uma reconciliação do gateway e filtraria apenas o que ainda não tem `order.approved` persistido:

```sql
SELECT missing.gateway, missing.transaction_id
FROM gateway_reconciliation_missing missing
LEFT JOIN orders o
    ON o.gateway = missing.gateway
   AND o.transaction_id = missing.transaction_id
LEFT JOIN lead_events le
    ON le.order_id = o.id
   AND le.event = 'order.approved'
WHERE le.id IS NULL;
```

Eu publicaria apenas esse resultado em uma fila de replay dedicada ou em `lead.received` com metadado `replay = true`. Se qualquer um dos 421 já processados entrar por engano, constraints e upserts seguram os efeitos duplicados. O filtro usa o que importa para o incidente: `gateway + transaction_id + event` na origem e `lead_events(order_id, event)` como prova de que o efeito já existe.

Para `decrypt_failed`, eu não faria replay cego. Primeiro corrigiria secret, IV/ciphertext, header ou formato; depois reprocessaria a DLQ ou um lote auditável e verificaria que o payload voltou a abrir. Para `schema_failed`, a lógica é parecida: classificar se houve mudança válida de contrato ou payload realmente inválido, ajustar o mapeamento quando couber e só republicar o que estiver parseável e elegível.

## Três medidas preventivas

1. **Alertas de funil**: volumes por etapa, DLQ por motivo, idade de `lead.received`, consumo por fila e pending antigo por canal. Não basta alertar erro alto; queda brusca de volume também denuncia perda silenciosa.
2. **Reconciliação automática com o gateway**: comparar `transaction_id`, `gateway`, `event` e `transaction_time` contra `raw_payloads`, `lead_events` e DLQ. O incidente ideal é detectado por job e alerta, não pelo call center depois de quatro horas.
3. **Replay auditável/outbox**: registrar publicações pendentes entre banco e RabbitMQ para reenvio seguro, mantendo `correlation_id` ponta a ponta. Se o bruto foi salvo e a publicação falhou, o sistema precisa saber exatamente o que ficou para trás.
