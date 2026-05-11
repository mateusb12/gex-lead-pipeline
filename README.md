# GEX Lead Pipeline

Esse projeto é uma solução para o teste técnico Backend PL da GEX.

A ideia do projeto foi construir uma esteira de integração para webhooks de gateways: receber eventos, persistir o payload bruto, validar schemas, tratar payloads criptografados, preparar o roteamento para filas e deixar a base pronta para processamento assíncrono de leads.

A implementação prioriza rastreabilidade e segurança operacional. Cada payload recebido fica registrado em `raw_payloads`, cada request recebe um `correlation_id`, os gateways `lous` e `grummer` são tratados conforme seus formatos, e os fluxos de sucesso, descarte, erro de schema, falha de decrypt e distribuição são separados para facilitar auditoria, reprocessamento e investigação de incidentes.

## Stack utilizada

- Python
- FastAPI
- Pydantic
- MySQL
- RabbitMQ
- SQLAlchemy Core
- Docker Compose
- Pytest
- Ruff

---

## Funcionalidades atuais

- Receber webhooks em `POST /webhooks/{gateway}`
- Aceitar gateways `lous` e `grummer`
- Persistir todo payload recebido em `raw_payloads`
- Gerar `correlation_id` por request
- Validar payload aberto do gateway `lous`
- Validar envelope criptografado do gateway `grummer`
- Separar payload válido, inválido e criptografado em esteiras diferentes
- Marcar erros de schema em `raw_payloads.error_reason`
- Simular decrypt do `grummer` com stub temporário
- Listar payloads recebidos por uma rota de debug
- Rodar replay local dos payloads do desafio via rota de benchmark em debug
- Limpar automaticamente cargas anteriores do benchmark para evitar lixo no banco local
- Subir API, MySQL, RabbitMQ e workers via Docker Compose
- Rodar testes automatizados do receiver e da conexão com banco

---

## Estrutura do projeto

```text
source/
  main.py

  features/
    webhooks/
      router.py
      service.py
      repository.py
      schemas.py

    debug/
      router.py
      service.py
      repository.py
      benchmark.py

    leads/
      worker.py

    distribution/
      sms_worker.py

  shared/
    config.py
    db.py
    tables.py

sql/
  001_create_tables.sql
  002_indexes.sql
  audit_queries.sql

tests/

assets/
  .gitkeep
```

A organização foi feita por feature porque os arquivos relacionados ao mesmo fluxo ficam próximos.

Se o problema está no recebimento de webhooks, o caminho natural fica em `features/webhooks`.  
Se o problema está no processamento futuro de leads, fica em `features/leads`.  
Se o problema está na distribuição SMS, fica em `features/distribution`.

O que é compartilhado, como configuração, conexão com banco e tabelas do SQLAlchemy Core, fica em `shared`.

---

## Arquivos locais do desafio

Os arquivos anexos do teste técnico não são versionados no repositório por serem materiais do processo seletivo.

Para rodar a carga local com os dados reais do desafio, coloque os arquivos recebidos em `assets/`:

```text
assets/
  webhook_payloads.json
  grummer_secret.txt
  expected_summary.xlsx
  expected_summary_meta.json
```

Esses arquivos são usados apenas como entrada local para validar a esteira contra o benchmark fornecido no teste.

O decrypt do Grummer usa `GRUMMER_SECRET_HEX` quando definido; caso contrário, lê `assets/grummer_secret.txt`. Não há chave criptográfica default no código.

A pasta `assets/` fica fora do contexto do Repomix e fora do Git, evitando expor payloads, gabaritos ou secrets do processo seletivo.

---

## Como executar

### Subir a aplicação

Primeira execução em banco limpo, ou depois de mudar dependências:

```bash
docker compose up -d --build
```

Uso normal durante desenvolvimento, quando o schema do banco não mudou:

```bash
docker compose up -d
```

Quando houver mudança nos scripts SQL e o volume local do MySQL já existir, recrie o banco do zero para reaplicar `sql/001_create_tables.sql` e `sql/002_indexes.sql`:

```bash
docker compose down -v
docker compose up -d --build
```

A API fica disponível em:

```text
http://localhost:8000
```

---

## Endpoints principais

### Health check

```http
GET /health
```

Exemplo:

```bash
curl http://localhost:8000/health
```

---

### Receber webhook do gateway Lous

```http
POST /webhooks/lous
```

Exemplo simples:

```bash
curl -X POST http://localhost:8000/webhooks/lous \
  -H "Content-Type: application/json" \
  -d '{"hello":"world"}'
```

Esse payload é salvo em `raw_payloads`, mas cai como `schema_failed`, porque ainda não possui os campos esperados de uma venda.

Exemplo de payload válido:

```bash
curl -X POST http://localhost:8000/webhooks/lous \
  -H "Content-Type: application/json" \
  -d '{
    "transaction_id": "ORD-TEST-001",
    "transaction_time": "2026-05-10T17:49:30.715553+00:00",
    "event": "order.approved",
    "customer": {
      "email": "test@example.com",
      "first_name": "Test",
      "last_name": "Customer",
      "phone": "+18005551234",
      "country": "US"
    },
    "product": {
      "id": "PROD-001",
      "name": "Fit Burn",
      "niche": "weight_loss"
    },
    "quantity": 1,
    "payment": {
      "status": "approved",
      "amount_usd": 99.90,
      "method": "credit_card"
    }
  }'
```

---

### Receber webhook do gateway Grummer

```http
POST /webhooks/grummer
```

Exemplo:

```bash
curl -X POST http://localhost:8000/webhooks/grummer \
  -H "Content-Type: application/json" \
  -H "X-GR-Encrypted: true" \
  -d '{
    "iv": "base64-iv-placeholder",
    "ciphertext": "base64-ciphertext-placeholder"
  }'
```

Hoje o decrypt real ainda não foi implementado. O projeto valida o envelope `iv/ciphertext`, salva o payload bruto e registra um `body_decrypted` temporário indicando que a etapa de decrypt ainda está stubada.

---

### Debug de payloads recebidos

```http
GET /debug/raw-payloads?limit=10
```

Exemplo:

```bash
curl http://localhost:8000/debug/raw-payloads?limit=10
```

Essa rota existe apenas para facilitar desenvolvimento, Postman e Loom.  
Ela ajuda a visualizar se os webhooks foram persistidos corretamente em `raw_payloads`.

---

### Benchmark local dos payloads do desafio

```http
POST /debug/benchmark/replay
```

Essa rota existe para desenvolvimento local. Ela lê `assets/webhook_payloads.json` e reenvia os payloads pelo mesmo fluxo usado pelo receiver real.

Exemplo sem persistir nada no banco:

```bash
curl -s -X POST "http://localhost:8000/debug/benchmark/replay?dry_run=true&limit=10" | jq
```

Exemplo executando a carga real limitada:

```bash
curl -s -X POST "http://localhost:8000/debug/benchmark/replay?limit=200" | jq
```

Por padrão, antes de rodar uma nova carga real, o benchmark remove os registros antigos criados pelo próprio benchmark em `raw_payloads`. Isso evita acumular lixo no banco durante testes repetidos.

Para não limpar a carga anterior, use:

```bash
curl -s -X POST "http://localhost:8000/debug/benchmark/replay?limit=200&cleanup_previous=false" | jq
```

O objetivo dessa rota não é mascarar falhas. Ela serve para comparar o estado atual da implementação contra os payloads reais do desafio e deixar visível o que ainda falta, como decrypt real, ajustes de schema, normalização e idempotência.

---

## RabbitMQ Management

```text
http://localhost:15672
```

Credenciais locais:

```text
user: guest
password: guest
```

---

## Testes

Instalar dependências locais:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Rodar testes:

```bash
pytest
```

Rodar lint:

```bash
ruff check .
```

---

## Decisões técnicas

### Python e FastAPI

Escolhi Python por produtividade e clareza para lidar com JSON, validação, scripts auxiliares e integração com filas.

Usei FastAPI porque ele é leve, simples de subir localmente e combina bem com Pydantic para validação de payloads. Para este teste, a prioridade é deixar o fluxo fácil de entender e defender, não criar uma estrutura pesada demais antes da regra principal estar funcionando.

---

### Organização por feature

Escolhi organizar por feature porque o fluxo do problema é naturalmente dividido por áreas.

O receiver fica em `features/webhooks`, o processamento futuro de leads fica em `features/leads` e o distribuidor SMS fica em `features/distribution`.

Isso evita espalhar arquivos relacionados em pastas genéricas como `routers`, `services`, `repositories` e `schemas` no projeto inteiro. Quando algo quebrar em webhook, os arquivos principais daquele fluxo estão próximos.

---

### Router, service e repository

A separação principal ficou assim:

- o router lida com HTTP
- o service decide a esteira de processamento
- o repository concentra o acesso a dados com SQLAlchemy Core
- o shared/db cria a conexão com o banco

O router propositalmente não carrega regra de negócio demais. Ele recebe a request, valida o gateway no path, lê o JSON e chama o service.

O service decide se o payload é `lous`, `grummer`, schema válido, schema inválido ou decrypt stubado.

O repository concentra as operações de banco usando SQLAlchemy Core, evitando SQL string espalhada na aplicação para operações comuns de `insert`, `select` e `update`.

---

### SQLAlchemy Core sem ORM completo

Optei por usar SQLAlchemy Core no código da aplicação, sem migrar para ORM completo.

A motivação foi equilibrar dois pontos:

- eu não queria espalhar SQL string manual pelos repositories
- mas, ao mesmo tempo, eu também não queria esconder demais o comportamento do banco atrás de uma camada de ORM mais abstrata do que o problema pede

Neste desafio, o banco é parte importante da avaliação: modelagem, constraints, índices, idempotência, queries de auditoria e EXPLAIN. Por isso, faz sentido manter as operações de persistência próximas do modelo relacional.

Na aplicação, as operações comuns usam `Table`, `insert()`, `select()` e `update()` do SQLAlchemy Core. Isso deixa o código mais refatorável do que strings SQL soltas, sem a parte ruim de transformar o fluxo em uma camada de entidades ORM que não agrega muito neste momento.

Os scripts SQL continuam separados em `sql/`, porque fazem parte da entrega do teste e precisam ser avaliados diretamente: criação de tabelas, índices, queries de auditoria e, se aplicável, stored procedure.

A regra prática que eu quis adotar acabou sendo:

- SQLAlchemy Core para código de aplicação
- SQL puro nos arquivos `sql/`
- `text()` apenas quando fizer sentido, como no ping simples de conexão com o banco

Essa escolha mantém o acesso ao banco de forma explícita, ao passo em que evita que os repositories virem um conjunto de strings SQL difíceis de refatorar.

---

### Persistência do payload bruto

A primeira regra implementada foi salvar o payload bruto em `raw_payloads`.

Essa decisão foi proposital porque **o payload bruto é a base de auditoria do sistema**. Mesmo se o decrypt falhar, se o schema estiver inválido ou se o processamento posterior quebrar, ainda existe um registro do que chegou, quando chegou, de qual gateway veio e qual `correlation_id` foi gerado.

Isso também ajuda no cenário de incidente descrito no desafio, porque permite diferenciar se o gateway nunca enviou, se o webhook chegou mas falhou depois, ou se o problema ocorreu em uma etapa posterior da esteira.

---

### Validação por schema

Usei Pydantic para validar os formatos principais de entrada.

Hoje existem dois formatos importantes:

- `lous`: payload de venda aberto em JSON
- `grummer`: envelope criptografado contendo `iv` e `ciphertext`

O payload de venda é validado com um schema próprio. O envelope criptografado do `grummer` também é validado antes da etapa de decrypt.

A validação ainda não é a normalização final de negócio. Ela apenas confirma se a estrutura mínima esperada chegou. Normalizações como e-mail lowercase, telefone em E.164 e nome padrão serão implementadas em uma etapa posterior.

---

### Roteamento das esteiras

O endpoint público continua sendo o mesmo pedido no desafio:

```text
POST /webhooks/{gateway}
```

Internamente, o service separa as esteiras:

- `lous` válido e aprovado segue para a futura fila `lead.received`
- `lous` inválido é marcado como `schema_failed`
- `grummer` com envelope válido segue para a futura etapa de decrypt real
- `grummer` com envelope inválido é marcado como `schema_failed`

A idempotência do receiver é baseada em `gateway + transaction_id + event`. A ideia é permitir que um mesmo pedido evolua ao longo do tempo, por exemplo de `order.approved` para `order.refunded`, sem permitir que o mesmo evento seja processado duas vezes. 

Na prática: `lous + ORD-001 + order.approved` entra na primeira vez; se chegar novamente com a mesma combinação, vira `duplicate` e não deve ser republicado. Neste momento, a publicação em RabbitMQ ainda não foi implementada. A resposta já indica qual seria a próxima esteira, mas o envio real para fila fica para a próxima etapa.

---

### Rota de debug

Adicionei `GET /debug/raw-payloads` para facilitar inspeção local.

Essa rota não representa uma API de produto. Ela existe para desenvolvimento, Postman e Loom, permitindo mostrar rapidamente que o payload recebido foi salvo em `raw_payloads`.

Em produção, esse tipo de rota deveria ser protegido, removido ou substituído por uma interface interna com autenticação.

---

### Benchmark local com os anexos do desafio

Adicionei `POST /debug/benchmark/replay` para rodar localmente os payloads fornecidos no teste técnico contra o fluxo real da aplicação.

A ideia é usar o próprio benchmark do desafio como ferramenta de diagnóstico, em vez de depender apenas de payloads manuais criados durante o desenvolvimento.

A rota suporta `dry_run=true`, que apenas lê e classifica os payloads sem persistir no banco. Quando roda sem `dry_run`, os registros criados recebem um marcador interno de benchmark nos headers salvos em `raw_payloads`. Antes de uma nova execução, a rota remove os registros antigos criados pelo próprio benchmark, evitando acúmulo de lixo no banco local.

Os arquivos reais ficam em `assets/`, mas não são versionados porque fazem parte do material do processo seletivo e incluem payloads, gabaritos e secret de teste.

---

### RabbitMQ e workers

O Docker Compose já sobe RabbitMQ, um worker de leads e um worker de distribuição SMS.

Por enquanto, os workers ainda são stubs. Eles existem para deixar a topologia local parecida com o fluxo final do teste, mas a regra de consumo, retry, DLQ e distribuição real será implementada nas próximas etapas.

---

## Status atual

Implementado:

- API FastAPI
- MySQL no Docker
- RabbitMQ no Docker
- Estrutura por feature
- Conexão com banco via SQLAlchemy Core
- Persistência em `raw_payloads`
- Decrypt AES-256-CBC real do Grummer
- Validação de schemas para Lous e Grummer decriptado
- Normalização de e-mail, telefone, nome e país
- Idempotência inicial por `gateway + transaction_id + event`
- Logs estruturados com `correlation_id` e identificador anonimizado do cliente
- Roteamento inicial de esteiras
- Debug de payloads recebidos
- Replay local dos payloads reais do desafio via benchmark debug
- Workers stub com reload local
- Testes automatizados básicos

Ainda falta:

- publicação real na fila `lead.received`
- DLQs reais para decrypt/schema/consumer
- consumer real de leads
- persistência em `leads`, `orders`, `lead_events` e `distribution_status`
- retry e backoff exponencial
- distribuidor SMS real com webhook.site
- queries de auditoria em `audit_queries.sql`
- documentação conceitual do incidente e decisões de arquitetura