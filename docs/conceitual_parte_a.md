# Conceitual — Parte A: Resolução de incidente

## Cenário

Na segunda de manhã, o PO informa que o gateway registrou **US$ 1.3M em vendas aprovadas**, com **1.587 transações** no dashboard de sexta-feira. No nosso sistema, existem apenas **421 registros em `lead_events` com `event = 'order.approved'`** no mesmo período. Além disso, o call center está há 4 horas sem leads.

A primeira leitura do problema é montar o funil da esteira. Não faz sentido reiniciar serviços ou reprocessar dados no escuro. No fluxo implementado, `lead_events` é gravado pelo **Lead Worker**, depois que o receiver valida o payload e publica a mensagem na fila `lead.received`.

O caminho relevante é:

```text
gateway
  -> receiver HTTP
  -> raw_payloads
  -> decrypt/schema/normalização/idempotência
  -> lead.received
  -> Lead Worker
  -> leads / orders / lead_events
  -> distribution_status
  -> filas de distribuição
```

Se `lead_events` está baixo, o problema pode estar no Lead Worker. Mas também pode estar antes dele: o webhook pode não ter chegado, pode ter falhado no decrypt/schema, pode não ter sido publicado em `lead.received` ou pode estar parado na fila.

## Primeira ação

Antes de mexer em produção, eu faria três coisas:

1. **Congelar a janela de investigação**: confirmar com o PO/gateway qual foi exatamente o período usado no dashboard, incluindo timezone, gateway, critério de “approved” e se o número é baseado em `transaction_time` ou em horário de processamento do gateway.
2. **Não reiniciar nem reprocessar nada ainda**: reiniciar worker/API ou reenfileirar payloads sem diagnóstico pode apagar evidências, duplicar leads ou piorar o incidente.
3. **Montar o funil por etapa**: comparar os 1.587 eventos aprovados do gateway com os checkpoints internos: `raw_payloads`, `lead_dead_letter`, fila `lead.received`, `lead_events` e `distribution_status`.

A janela principal deve usar `transaction_time`, porque ele representa o horário real da compra. `raw_payloads.received_at` ajuda a saber quando o webhook chegou no nosso sistema, mas pode não bater com o período de vendas mostrado no dashboard do gateway.

## Hipóteses iniciais ranqueadas

### 1. Receiver falhando antes ou durante a persistência em `raw_payloads`

Essa é a hipótese mais forte se `raw_payloads` também tiver algo perto de 421–430 registros para a janela investigada. `raw_payloads` é o primeiro checkpoint persistente do sistema. Ele é gravado antes de decrypt, schema, idempotência e fila.

Se o gateway diz que houve 1.587 vendas aprovadas, mas só 430 payloads chegaram ao bruto, o problema está no caminho:

```text
gateway -> rede/DNS/load balancer/API gateway -> receiver -> insert em raw_payloads
```

Possíveis causas: timeout no receiver, erro de conexão com MySQL no insert inicial, rota errada, deploy quebrado, problema de infraestrutura, bloqueio no API gateway ou instabilidade no endpoint.

### 2. Gateway não enviou tudo ou enviou para endpoint errado

Se o nosso `raw_payloads` estiver baixo e os logs do receiver/load balancer também não mostrarem as chamadas ausentes, é provável que parte dos webhooks nunca tenha chegado até nós.

Nesse caso, eu pediria ao gateway uma amostra dos `transaction_id` ausentes, timestamps, status das tentativas de entrega, URL usada, HTTP status recebido e logs de retry.

### 3. Janela/timezone ou critério de comparação errado

Essa hipótese é barata de validar e pode evitar um falso incidente. O gateway pode estar contando por `transaction_time` em um timezone, enquanto nossa query pode estar usando `received_at`, UTC ou outro período.

Também pode haver diferença entre “venda aprovada” no dashboard e o nosso filtro `event = 'order.approved' AND payment.status = 'approved'`.

### 4. Falha em massa em decrypt/schema antes da publicação em `lead.received`

Se `raw_payloads` estiver próximo de 1.587, mas `lead_events` estiver em 421, eu verificaria quantos payloads foram para `lead_dead_letter` com `reason = 'decrypt_failed'` ou `reason = 'schema_failed'`.

Essa hipótese vem antes de culpar o Lead Worker. Decrypt/schema acontecem antes da publicação em `lead.received`. Se o payload morre nessa etapa, ele nunca chega ao worker e nunca vira `lead_events`.

### 5. Lead Worker travado ou falhando ao persistir `lead_events`

Essa hipótese fica forte quando `raw_payloads` está alto, DLQs de decrypt/schema estão baixas e a fila `lead.received` tem mensagens acumuladas ou sem consumo.

Nesse caso, o receiver provavelmente fez seu papel. O Lead Worker não está consumindo ou não está conseguindo persistir `leads`, `orders` e `lead_events`.

## Queries SQL de diagnóstico

### 1. Contagem do bruto recebido

A primeira query valida se os webhooks chegaram ao nosso sistema. Eu usaria `transaction_time` extraído do payload quando possível, porque ele representa o horário da venda.

Exemplo para payloads já decriptados ou payloads abertos:

```sql
SELECT
    gateway,
    COUNT(*) AS total_raw
FROM raw_payloads
WHERE COALESCE(
    JSON_UNQUOTE(JSON_EXTRACT(body_decrypted, '$.transaction_time')),
    JSON_UNQUOTE(JSON_EXTRACT(body_original, '$.transaction_time'))
) >= '2026-05-08T00:00:00+00:00'
  AND COALESCE(
    JSON_UNQUOTE(JSON_EXTRACT(body_decrypted, '$.transaction_time')),
    JSON_UNQUOTE(JSON_EXTRACT(body_original, '$.transaction_time'))
) < '2026-05-09T00:00:00+00:00'
GROUP BY gateway;
```

Se esse número estiver muito abaixo de 1.587, eu priorizo receiver/infra/gateway antes de investigar worker.

### 2. Contagem de DLQ por motivo

```sql
SELECT
    reason,
    source,
    COUNT(*) AS total
FROM lead_dead_letter
WHERE created_at >= '2026-05-08 00:00:00'
  AND created_at < '2026-05-09 00:00:00'
GROUP BY reason, source
ORDER BY total DESC;
```

Essa query mostra se os payloads chegaram, mas foram classificados como falha de decrypt, schema, consumer ou distribuição.

### 3. Contagem do que virou evento aprovado

```sql
SELECT
    o.gateway,
    COUNT(*) AS approved_events
FROM lead_events le
JOIN orders o ON o.id = le.order_id
WHERE le.event = 'order.approved'
  AND le.transaction_time >= '2026-05-08 00:00:00'
  AND le.transaction_time < '2026-05-09 00:00:00'
GROUP BY o.gateway;
```

Essa query confirma o número reportado pelo PO dentro do nosso modelo relacional.

### 4. Reconciliação entre bruto, DLQ e `lead_events`

```sql
SELECT
    'raw_payloads' AS etapa,
    COUNT(*) AS total
FROM raw_payloads
WHERE received_at >= '2026-05-08 00:00:00'
  AND received_at < '2026-05-09 00:00:00'

UNION ALL

SELECT
    'dead_letter' AS etapa,
    COUNT(*) AS total
FROM lead_dead_letter
WHERE created_at >= '2026-05-08 00:00:00'
  AND created_at < '2026-05-09 00:00:00'

UNION ALL

SELECT
    'lead_events_approved' AS etapa,
    COUNT(*) AS total
FROM lead_events
WHERE event = 'order.approved'
  AND transaction_time >= '2026-05-08 00:00:00'
  AND transaction_time < '2026-05-09 00:00:00';
```

Aqui eu aceito usar `received_at/created_at` como visão operacional rápida. A reconciliação final com o gateway precisa considerar `transaction_time`.

## Comandos RabbitMQ

Eu olharia as filas para saber se a mensagem foi publicada e ficou parada, ou se o problema ocorreu antes da fila.

```bash
rabbitmqctl list_queues name messages_ready messages_unacknowledged consumers
```

Também consultaria especificamente as filas relevantes:

```bash
rabbitmqctl list_queues name messages_ready messages_unacknowledged consumers   | grep -E 'lead.received|lead.dead|dist.callcenter|dist.sms|dist.dead'
```

Interpretação:

```text
lead.received com muitas messages_ready e consumers = 0
  -> worker parado ou não conectado

lead.received com muitas messages_unacknowledged
  -> worker pegou mensagens, mas travou/processa muito lento

lead.dead.schema_failed ou lead.dead.decrypt_failed alta
  -> problema antes do worker

dist.callcenter alta
  -> lead_events pode estar ok, mas distribuição para call center parou

filas vazias + raw_payloads baixo
  -> problema antes da fila: gateway/infra/receiver/raw insert
```

## Como diferenciar os cenários pedidos

### (a) Gateway nunca enviou

Sinais:

```text
raw_payloads baixo
logs HTTP/load balancer sem as requests
sem correlation_id para os transaction_id ausentes
DLQs baixas
filas baixas
```

Ação: pedir ao gateway os logs de entrega dos `transaction_id` ausentes, URL usada, HTTP status, payloads de exemplo e histórico de retry.

### (b) Webhook chegou, mas decrypt falhou

Sinais:

```text
raw_payloads alto
body_original salvo
body_decrypted nulo
raw_payloads.error_reason começando com decrypt_failed
lead_dead_letter com reason = decrypt_failed
fila lead.dead.decrypt_failed com mensagens
```

Ação: verificar se houve mudança de secret, IV/ciphertext inválido, rotação de chave, header `X-GR-Encrypted` ausente ou formato alterado pelo gateway.

### (c) Lead foi publicado na fila, mas o consumer travou

Sinais:

```text
raw_payloads alto
DLQs de decrypt/schema baixas
lead.received com messages_ready ou messages_unacknowledged altas
logs do Lead Worker com erro/retry/consumer_failed
lead_events baixo
```

Ação: checar logs do worker por `correlation_id`, estado do container/pod, conexão com MySQL, locks, exceptions e volume de mensagens na fila.

### (d) Consumer publicou, mas o distribuidor não consumiu

Sinais:

```text
lead_events alto
distribution_status criado
fila dist.callcenter ou dist.sms acumulada
status pending antigo em distribution_status
call center sem leads mesmo com lead_events ok
```

Ação: investigar o distribuidor/canal específico, não o receiver. Para o sintoma deste incidente, isso explicaria o call center sem leads. Mas não explicaria sozinho `lead_events = 421`.

## Plano de reprocessamento sem duplicar

Eu não reprocessaria os 1.166 faltantes antes de classificar onde eles pararam.

### Caso 1: o payload existe em `raw_payloads`, mas não virou `lead_events`

Primeiro eu montaria uma lista de candidatos a reprocessamento:

```sql
SELECT
    rp.id AS raw_payload_id,
    rp.gateway,
    COALESCE(rp.body_decrypted, rp.body_original) AS payload
FROM raw_payloads rp
LEFT JOIN orders o
    ON o.gateway = rp.gateway
   AND o.transaction_id = COALESCE(
        JSON_UNQUOTE(JSON_EXTRACT(rp.body_decrypted, '$.transaction_id')),
        JSON_UNQUOTE(JSON_EXTRACT(rp.body_original, '$.transaction_id'))
   )
LEFT JOIN lead_events le
    ON le.order_id = o.id
   AND le.event = 'order.approved'
WHERE COALESCE(
    JSON_UNQUOTE(JSON_EXTRACT(rp.body_decrypted, '$.event')),
    JSON_UNQUOTE(JSON_EXTRACT(rp.body_original, '$.event'))
) = 'order.approved'
  AND COALESCE(
    JSON_UNQUOTE(JSON_EXTRACT(rp.body_decrypted, '$.payment.status')),
    JSON_UNQUOTE(JSON_EXTRACT(rp.body_original, '$.payment.status'))
) = 'approved'
  AND le.id IS NULL;
```

Depois, reenfileiraria esses payloads em `lead.received` com o mesmo `transaction_id`, `event`, `gateway` e `raw_payload_id`.

A proteção contra duplicidade fica em dois níveis:

```text
webhook_idempotency_keys: gateway + transaction_id + event
lead_events: order_id + event
```

Além disso, o consumer usa upsert para `leads/orders/lead_events`. Reprocessar uma mensagem que já entrou não deve gerar duplicidade.

### Caso 2: o gateway realmente não enviou os 1.166

Eu pediria ao gateway um replay controlado apenas dos `transaction_id` ausentes. Outra opção seria importar um arquivo de reconciliação para uma fila/tabela de reprocessamento.

Antes de publicar, eu faria anti-join contra o que já existe:

```sql
SELECT missing.transaction_id
FROM gateway_reconciliation_missing missing
LEFT JOIN orders o
    ON o.gateway = missing.gateway
   AND o.transaction_id = missing.transaction_id
LEFT JOIN lead_events le
    ON le.order_id = o.id
   AND le.event = 'order.approved'
WHERE le.id IS NULL;
```

A estratégia de fila seria publicar apenas os ausentes em uma fila de replay, por exemplo `lead.replay`, ou diretamente em `lead.received` com um campo de auditoria:

```json
{
  "replay": true,
  "replay_reason": "incident_2026_05_12_missing_gateway_approved"
}
```

O processamento continuaria idempotente. Se algum dos 421 já existentes for reenviado por engano, a constraint segura.

## Medidas preventivas

1. **Alertas de funil por etapa**

Criar métricas e alertas para:

```text
webhooks recebidos por gateway
payloads aprovados validados
mensagens publicadas em lead.received
lead_events criados
DLQ por reason
idade da mensagem mais antiga em lead.received
pending antigo em distribution_status
```

O alerta importante não é só “erro alto”. Também importa detectar “queda brusca de volume” e “gap entre raw_payloads approved e lead_events”.

2. **Reconciliação automática com o gateway**

Criar um job periódico de reconciliação por `transaction_id`, `gateway`, `event` e `transaction_time`.

Esse job compararia o relatório do gateway com:

```text
raw_payloads
orders
lead_events
lead_dead_letter
distribution_status
```

Se houver diferença acima de um limite, abriria alerta antes do call center ficar 4 horas sem leads.

3. **Outbox/replay seguro e rastreável**

Usar uma estratégia de outbox ou tabela de replay para registrar publicações pendentes e permitir reprocessamento auditável.

O objetivo é evitar perda silenciosa entre banco e RabbitMQ. Se o receiver salvar o bruto, mas falhar ao publicar em `lead.received`, deve existir um registro pendente para replay automático.

Também manteria `correlation_id` de ponta a ponta e logs estruturados para conseguir rastrear qualquer `transaction_id` desde o receiver até o distribuidor.
