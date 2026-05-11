# Explicação técnica — GEX Lead Pipeline

<p align="center">
  <img src="./architecture.png" alt="Arquitetura do GEX Lead Pipeline" width="900">
</p>

## 1. Visão geral

Este projeto implementa uma esteira backend para receber webhooks de gateways de pagamento e preparar esses eventos para processamento assíncrono.

O fluxo começa em `POST /webhooks/{gateway}`. A API 
- recebe o payload
- salva o bruto em `raw_payloads`
- trata o formato específico de cada gateway
- valida o schema
- normaliza campos críticos
- aplica idempotência

A ideia principal foi priorizar rastreabilidade. Mesmo quando um payload falha no decrypt, vem com schema inválido, é descartado ou é duplicado, ele continua registrado no banco para auditoria e investigação.

Nesta etapa, o receiver já está preparado para separar os casos que devem seguir para a fila `lead.received` dos casos que devem ser descartados ou tratados como erro.

---

## 2. Fluxo implementado

O endpoint principal é:

```text
POST /webhooks/{gateway}
```

Gateways aceitos:

```text
lous
grummer
```

O gateway `lous` envia o payload aberto em JSON.

O gateway `grummer` envia um envelope criptografado com `iv` e `ciphertext`. Quando o header `X-GR-Encrypted: true` está presente, o sistema tenta abrir o payload usando AES-256-CBC com PKCS7.

Depois disso, o fluxo segue esta ordem:

```text
receber webhook
  -> gerar correlation_id
  -> salvar payload bruto
  -> tratar gateway
  -> decriptar quando necessário
  -> validar schema
  -> normalizar dados críticos
  -> aplicar idempotência
  -> classificar resultado
```

Os status principais usados no receiver são:

| Status | Quando acontece |
|---|---|
| `validated` | Payload válido, aprovado e não duplicado |
| `discarded` | Payload válido, mas com status diferente de approved |
| `schema_failed` | Payload fora do schema esperado |
| `decrypt_failed` | Payload Grummer com falha de decrypt |
| `duplicate` | Mesmo gateway, transaction_id e event já recebido |

---

## 3. Decisões técnicas

### Python e FastAPI

Usei Python porque o desafio envolve bastante manipulação de JSON, validação de payload, scripts auxiliares e integração com banco/fila.

Usei FastAPI porque ele é simples de subir localmente, combina bem com Pydantic e deixa o fluxo HTTP fácil de entender.

A ideia não foi criar uma arquitetura grande demais antes da regra principal funcionar. O foco foi deixar o receiver claro, testável e fácil de defender.

### Organização por feature

A estrutura foi organizada por feature:

```text
features/webhooks
features/debug
features/leads
features/distribution
shared
```

Escolhi esse formato porque os arquivos relacionados ao mesmo fluxo ficam próximos.

Quando o problema está no recebimento de webhook, o caminho principal está em `features/webhooks`. Quando for processamento assíncrono, o caminho fica em `features/leads` e `features/distribution`.

### SQLAlchemy Core

Usei SQLAlchemy Core em vez de ORM completo.

A ideia foi evitar SQL string espalhada no código da aplicação, mas sem esconder demais o comportamento do banco.

Neste teste, o banco é parte importante da solução: idempotência, constraints, índices, auditoria e queries SQL. Por isso, preferi manter uma abordagem mais próxima do modelo relacional.

Na prática:

```text
SQLAlchemy Core -> código da aplicação
SQL puro        -> scripts em sql/
```

### Payload bruto

Todo webhook recebido é salvo em `raw_payloads`.

Isso vale inclusive para payload inválido, duplicado, descartado ou com falha de decrypt.

Essa decisão é importante porque permite responder perguntas como:

- o gateway enviou ou não enviou?
- o payload chegou na API?
- falhou no decrypt?
- falhou no schema?
- foi duplicado?
- foi descartado por status?

Sem esse registro bruto, a investigação de incidente fica muito mais fraca.

### Idempotência

A chave de idempotência usada no receiver é:

```text
gateway + transaction_id + event
```

Usei também o `gateway` para evitar colisão entre gateways diferentes que possam usar o mesmo identificador de pedido.

A proteção fica no banco por constraint única, e não apenas por uma consulta antes do insert. Isso é importante porque dois webhooks iguais podem chegar quase ao mesmo tempo. Nesse caso, a constraint do banco é quem garante a proteção contra race condition.

### Logs estruturados

Os logs usam JSON e carregam o `correlation_id` gerado no início da request.

Também evitei logar e-mail e telefone em texto puro. Quando preciso identificar o cliente no log, uso um identificador anonimizado.

A intenção é ter rastreabilidade sem expor dado sensível desnecessariamente.

---

## 4. Premissas adotadas

Algumas decisões foram assumidas para deixar o fluxo mais previsível:

- apenas `grummer` e `lous` são gateways aceitos;
- payload Grummer deve vir com `iv` e `ciphertext` em base64;
- a chave do Grummer vem de `GRUMMER_SECRET_HEX` ou de `assets/grummer_secret.txt`;
- payload com e-mail inválido fica separado como erro de schema;
- telefone inválido não bloqueia o lead, apenas é sinalizado;
- `first_name` vazio recebe o fallback `"Customer"`;
- status diferente de `approved` é descartado do fluxo principal, mas permanece em `raw_payloads`;
- payload duplicado retorna sucesso operacional, mas não deve ser republicado.

---

## 5. Índices e modelagem

Os scripts SQL ficam em `sql/`.

A modelagem foi pensada para separar:

- payload bruto recebido;
- chave de idempotência;
- lead normalizado;
- pedido;
- evento operacional;
- status de distribuição;
- dead letter.

Índices principais:

| Índice | Motivo |
|---|---|
| `raw_payloads(gateway, received_at)` | facilita auditoria por gateway e período |
| `webhook_idempotency_keys(gateway, transaction_id, event)` | garante idempotência e protege contra duplicidade |
| `leads(email)` | evita cliente duplicado por e-mail |
| `orders(gateway, transaction_id)` | localiza o pedido original por gateway |
| `lead_events(order_id, event)` | impede repetir o mesmo evento operacional |
| `distribution_status(channel, status, updated_at)` | ajuda consultas de pendências por canal |
| `lead_dead_letter(origin, created_at)` | ajuda auditoria de falhas por origem e período |

A justificativa principal é deixar rápidas as consultas que o desafio pede: auditoria por período, pendências antigas, sucesso por canal, DLQs e reconciliação entre eventos aprovados e entregas.

---

## 6. RabbitMQ e workers

O Docker Compose já sobe RabbitMQ junto com a API e os workers.

A intenção da topologia é:

```text
lead.received
  -> worker de leads
  -> dist.sms
  -> distribuidor SMS
```

Além disso, o desenho prevê DLQs para separar falhas de decrypt, schema, consumer e distribuição.

Nesta etapa, o receiver já classifica corretamente o que deve seguir para fila e o que deve ser separado. A etapa seguinte é conectar essa decisão à publicação real e ao consumo completo pelos workers.

---

## 7. Webhook.site

A URL do webhook.site usada no distribuidor SMS deve ser preenchida aqui antes da entrega:

```text
TODO: colar URL do webhook.site
```

---

## 8. Como validar localmente

Subir a aplicação:

```bash
docker compose up -d --build
```

Rodar testes:

```bash
pytest
```

Rodar lint:

```bash
ruff check .
```

Testar health check:

```bash
curl http://localhost:8000/health
```

Rodar benchmark local em modo dry-run:

```bash
curl -s -X POST "http://localhost:8000/debug/benchmark/replay?dry_run=true&limit=10" | jq
```

Rodar benchmark persistindo no banco:

```bash
curl -s -X POST "http://localhost:8000/debug/benchmark/replay?limit=200" | jq
```

---

## 9. Limitações atuais

O receiver de webhooks está implementado com persistência bruta, decrypt, schema, normalização, idempotência e logs estruturados.

A parte assíncrona ainda está em evolução. Os próximos pontos são:

- publicar de fato na fila `lead.received`;
- implementar o consumer real de leads;
- persistir `leads`, `orders`, `lead_events` e `distribution_status`;
- implementar retry, backoff e DLQs reais;
- implementar o distribuidor SMS usando webhook.site;
- finalizar as queries de auditoria e os EXPLAINs.

A prioridade foi estabilizar primeiro a entrada da esteira, porque ela é a base para o restante do fluxo.