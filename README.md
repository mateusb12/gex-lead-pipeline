# GEX Lead Pipeline

Esse projeto é a solução do teste técnico Backend PL da GEX.

A aplicação implementa uma esteira para receber webhooks de gateways, validar payloads, tratar decrypt quando necessário, aplicar idempotência, persistir dados em MySQL, publicar mensagens no RabbitMQ, processar leads em worker e simular a distribuição por SMS.

## Entregáveis

### Código-fonte

```text
source/
  main.py

  features/
    webhooks/       # receiver HTTP, decrypt, validação, idempotência e roteamento
    leads/          # worker que consome lead.received e persiste leads/orders/lead_events
    distribution/   # distribuidor SMS mock usando webhook.site
    debug/          # rotas auxiliares para desenvolvimento e replay do benchmark

  shared/           # config, conexão DB, RabbitMQ, tabelas e logging
```

### Scripts SQL

```text
sql/
  001_create_tables.sql   # criação das tabelas
  002_indexes.sql         # índices usados pelas queries de auditoria
  003_stored_procs.sql    # bônus: sp_insert_lead(...)
  audit_queries.sql       # queries de auditoria pedidas no desafio
```

### Documentação

```text
docs/
  explicacao_tecnica.md       # visão geral do fluxo, decisões, índices e validação
  audit_explains.md           # outputs completos dos EXPLAIN ANALYZE
  conceitual_parte_a.md       # resolução do incidente
  conceitual_parte_b.md       # decisões de arquitetura
  architecture.png            # diagrama geral da arquitetura

docs/pictures/
  01-receiver-entrada.png
  02-validacao-decrypt-dlq.png
  03-idempotencia-roteamento.png
  04-rabbit-lead-worker.png
```

### Diagrama de arquitetura

<p align="center">
  <img src="docs/architecture.png" alt="Diagrama geral da arquitetura" width="900">
</p>

### Artefatos de entrega

- `docs/explicacao_tecnica.md`
- `docs/audit_explains.md`
- `docs/conceitual_parte_a.md`
- `docs/conceitual_parte_b.md`
- `docs/architecture.png`
- `docs/evidencia_banco.md`, evidência textual com saídas reais do MySQL local
- `docs/evidencia_banco.png`, print do banco com registros inseridos
- Loom: não versionado neste repositório

### Testes

```text
tests/
```

A suíte cobre receiver, decrypt, schema, normalização, idempotência, workers, retry/DLQ, config, health check e integração com os serviços internos mockados.

## Fluxo implementado

```text
POST /webhooks/{gateway}
  -> raw_payloads
  -> decrypt/schema/normalização/idempotência
  -> lead.received
  -> Lead Worker
  -> leads / orders / lead_events / distribution_status
  -> dist.sms / dist.email / dist.callcenter / dist.whatsapp
  -> SMS Worker
  -> webhook.site
  -> distribution_status = delivered
```

Regras principais:

| Caso | Resultado |
|---|---|
| Payload válido, `event = order.approved` e `payment.status = approved` | publica em `lead.received` |
| Decrypt falhou | publica em `lead.dead.decrypt_failed` |
| Schema inválido | publica em `lead.dead.schema_failed` |
| Status diferente de `approved` | descarta do fluxo principal, mas mantém em `raw_payloads` |
| Webhook duplicado | retorna `duplicate` sem republicar |

A idempotência no receiver usa:

```text
gateway + transaction_id + event
```

A gravação de `leads`, `orders` e `lead_events` é feita pela stored procedure `sp_insert_lead(...)`, em transação no MySQL.

## Como rodar

### 1. Preparar os arquivos do desafio

Os arquivos recebidos no teste não ficam versionados no Git. Como o repositório pode ser público, preferi não incluir os anexos do processo seletivo diretamente no código.

Você precisa colocar os anexos em `assets/`:

```text
assets/
  webhook_payloads.json
  grummer_secret.txt
  expected_summary.csv
```

O decrypt do gateway `grummer` usa `GRUMMER_SECRET_HEX` quando definido nas variáveis de ambiente. Se não estiver definido, o código lê `assets/grummer_secret.txt`.

`expected_summary.csv` é usado como referência de validação do resultado agregado do desafio.

### 2. Configurar webhook.site

O distribuidor SMS usa a variável `SMS_WEBHOOK_URL`.

Durante o desenvolvimento, eu usei uma URL do webhook.site para validar o POST real do SMS Worker. Essa URL é útil como referência, mas não deve ser tratada como dependência fixa da correção, porque URLs gratuitas do webhook.site podem expirar, perder retenção ou parar de aceitar novas requests depois de certo limite.

Para validar localmente, gere uma URL nova em https://webhook.site e coloque no `.env`:

```bash
cp .env.example .env
```

Configure:

```env
SMS_WEBHOOK_URL=https://webhook.site/sua-url-aqui
APP_ENV=production
```

Em modo de desenvolvimento, também é possível usar:

```env
APP_ENV=dev
SMS_WEBHOOK_URL=
```

Nesse modo, se `SMS_WEBHOOK_URL` estiver vazia, o worker de SMS tenta gerar uma URL dinâmica automaticamente para facilitar testes locais.

### 3. Configuração obrigatória e fail-fast

Algumas configurações são validadas no startup para evitar uma execução aparentemente saudável, mas quebrada no meio do replay.

Em `APP_ENV=production`:

- a API exige `GRUMMER_SECRET_HEX` ou `assets/grummer_secret.txt` válido;
- o `sms-distributor` exige `SMS_WEBHOOK_URL`;
- se alguma dessas configurações estiver faltando, o serviço responsável falha cedo com erro claro.

Isso é intencional. O objetivo é avisar rapidamente que falta um anexo/configuração necessária, em vez de deixar o erro aparecer só depois durante o processamento.

Para diagnosticar:

```bash
docker compose ps
docker logs gex-api
docker logs gex-sms-distributor
```

Se quiser rodar localmente sem URL fixa do webhook.site, use:

```env
APP_ENV=dev
SMS_WEBHOOK_URL=
```

Nesse modo, o worker de SMS tenta gerar uma URL dinâmica automaticamente.

### 4. Subir tudo

Primeira execução, ou quando mudar dependência/schema:

```bash
docker compose up -d --build
```

Se os scripts SQL mudarem e o volume do MySQL já existir, recrie o banco:

```bash
docker compose down -v
docker compose up -d --build
```

Serviços principais:

```text
API:       http://localhost:8000
RabbitMQ: http://localhost:15672
```

Credenciais locais do RabbitMQ:

```text
user: guest
pass: guest
```

### 5. Verificar health check

```bash
curl http://localhost:8000/health
```

Resposta esperada:

```json
{"status":"ok"}
```

## Como rodar o benchmark do desafio

Com a aplicação de pé e `assets/webhook_payloads.json` disponível:

```bash
curl -s -X POST "http://localhost:8000/debug/benchmark/replay?limit=200" | jq
```

Para fazer apenas leitura/classificação sem persistir:

```bash
curl -s -X POST "http://localhost:8000/debug/benchmark/replay?dry_run=true&limit=200" | jq
```

Para ver payloads recebidos:

```bash
curl -s "http://localhost:8000/debug/raw-payloads?limit=10" | jq
```

## Como testar

Instale as dependências locais:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Rode os testes:

```bash
pytest
```

Rode o lint:

```bash
ruff check .
```

## Comandos úteis

Ver logs da API:

```bash
docker logs -f gex-api
```

Ver logs do worker de leads:

```bash
docker logs -f gex-worker
```

Ver logs do distribuidor SMS:

```bash
docker logs -f gex-sms-distributor
```

Ver filas no RabbitMQ:

```bash
docker exec -it gex-rabbitmq rabbitmqctl list_queues name messages_ready messages_unacknowledged consumers
```

Acessar MySQL:

```bash
docker exec -it gex-mysql mysql -ugex -pgex gex_pipeline
```

Exemplo de contagem rápida:

```sql
SELECT COUNT(*) FROM raw_payloads;
SELECT COUNT(*) FROM leads;
SELECT COUNT(*) FROM orders;
SELECT COUNT(*) FROM lead_events;
SELECT COUNT(*) FROM distribution_status;
SELECT reason, COUNT(*) FROM lead_dead_letter GROUP BY reason;
```

## Validação final esperada

Depois de subir tudo e rodar o replay dos 200 payloads, a esteira deve preencher:

```text
raw_payloads
leads
orders
lead_events
distribution_status
lead_dead_letter
```

O SMS Worker consome `dist.sms`, tenta enviar para o webhook.site, simula falhas, aplica retry e, em sucesso, marca a linha SMS em `distribution_status` como `delivered`.

As queries de auditoria estão em:

```text
sql/audit_queries.sql
```

Os planos de execução estão documentados em:

```text
docs/audit_explains.md
```

## Observações

- `EMAIL`, `CALL_CENTER` e `WHATSAPP` recebem mensagens nas filas, mas só o canal `SMS` tem distribuidor implementado, conforme permitido no desafio.
- Rotas `/debug/*` existem para desenvolvimento e replay local.
- E-mail e telefone não são logados em texto puro. Os logs usam `correlation_id` e identificador anonimizado do cliente.
- Os arquivos reais do desafio em `assets/` não são versionados.
