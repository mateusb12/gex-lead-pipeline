# GEX Lead Pipeline

Esse projeto é uma solução para o teste técnico Backend PL da GEX.

A ideia do projeto foi construir uma esteira simples, mas rastreável: receber webhooks de gateways, persistir o payload bruto, validar o formato de entrada, preparar o roteamento para filas e deixar a base pronta para processamento assíncrono de leads.

O foco inicial foi priorizar o receiver, a persistência do bruto e a organização do fluxo, porque esses pontos são a base para decrypt, idempotência, DLQ, workers e auditoria SQL.

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
```

A organização foi feita por feature porque os arquivos relacionados ao mesmo fluxo ficam próximos.

Se o problema está no recebimento de webhooks, o caminho natural fica em `features/webhooks`.  
Se o problema está no processamento futuro de leads, fica em `features/leads`.  
Se o problema está na distribuição SMS, fica em `features/distribution`.

O que é compartilhado, como configuração e conexão com banco, fica em `shared`.

---

## Como executar

### Subir a aplicação

Primeira execução, ou depois de mudar dependências:

```bash
docker compose up -d --build
```

Uso normal durante desenvolvimento:

```bash
docker compose up -d
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
      "niche": "weight_loss",
      "quantity": 1
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

O router não deveria carregar regra de negócio demais. Ele recebe a request, valida o gateway no path, lê o JSON e chama o service.

O service decide se o payload é `lous`, `grummer`, schema válido, schema inválido ou decrypt stubado.

O repository concentra as operações de banco usando SQLAlchemy Core, evitando SQL string espalhada na aplicação para operações comuns de insert, select e update.

---

### SQLAlchemy Core sem ORM completo

Optei por usar SQLAlchemy Core no código da aplicação, sem migrar para ORM completo.

A motivação foi equilibrar dois pontos: 
- eu não queria espalhar SQL string manual pelos repositories
- mas, ao mesmo tempo, eu também não queria esconder demais o comportamento do banco atrás de uma camada de ORM mais abstrata do que o problema pede.

Neste desafio, o banco é parte importante da avaliação: modelagem, constraints, índices, idempotência, queries de auditoria e EXPLAIN. Por isso, faz sentido manter as operações de persistência próximas do modelo relacional e fáceis de inspecionar.

Na aplicação, as operações comuns usam `Table`, `insert()`, `select()` e `update()` do SQLAlchemy Core. Isso deixa o código mais refatorável do que strings SQL soltas, sem transformar o fluxo em uma camada de entidades ORM que não agrega muito neste momento.

Os scripts SQL continuam separados em `sql/`, porque fazem parte da entrega do teste e precisam ser avaliados diretamente: criação de tabelas, índices, queries de auditoria e, se aplicável, stored procedure.

A regra prática adotada foi:

- SQLAlchemy Core para código de aplicação
- SQL puro nos arquivos `sql/`
- `text()` apenas quando fizer sentido, como no ping simples de conexão com o banco

Essa escolha mantém o acesso ao banco explícito, mas evita que os repositories virem um conjunto de strings SQL difíceis de refatorar.

---

### Persistência do payload bruto

A primeira regra implementada foi salvar o payload bruto em `raw_payloads`.

Essa decisão foi proposital porque o payload bruto é a base de auditoria do sistema. Mesmo se o decrypt falhar, o schema estiver inválido ou o processamento posterior quebrar, ainda existe um registro do que chegou, quando chegou, de qual gateway veio e qual `correlation_id` foi gerado.

Isso também ajuda no cenário de incidente descrito no desafio, porque permite diferenciar se o gateway nunca enviou, se o webhook chegou mas falhou depois, ou se o problema ocorreu em uma etapa posterior da esteira.

---

### Validação por schema

Usei Pydantic para validar os formatos principais de entrada.

Hoje existem dois formatos importantes:

- `lous`: payload de venda aberto em JSON
- `grummer`: envelope criptografado contendo `iv` e `ciphertext`

O payload de venda é validado com um schema próprio. O envelope criptografado do `grummer` também é validado antes da futura etapa de decrypt.

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

Neste momento, a publicação em RabbitMQ ainda não foi implementada. A resposta já indica qual seria a próxima esteira, mas o envio real para fila fica para a próxima etapa.

---

### Rota de debug

Adicionei `GET /debug/raw-payloads` para facilitar inspeção local.

Essa rota não representa uma API de produto. Ela existe para desenvolvimento, Postman e Loom, permitindo mostrar rapidamente que o payload recebido foi salvo em `raw_payloads`.

Em produção, esse tipo de rota deveria ser protegido, removido ou substituído por uma interface interna com autenticação.

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
- Validação inicial de schemas
- Roteamento inicial de esteiras
- Debug de payloads recebidos
- Workers stub com reload local
- Testes automatizados básicos

Ainda falta:

- decrypt AES-256-CBC real do Grummer
- normalização de e-mail, telefone e nome
- idempotência por `transaction_id + event`
- publicação na fila `lead.received`
- consumer real de leads
- retry e DLQ
- distribuidor SMS real com webhook.site
- queries de auditoria em `audit_queries.sql`
- documentação conceitual do incidente e decisões de arquitetura