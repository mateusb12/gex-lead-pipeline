# GEX Lead Pipeline

Esse projeto é uma solução para o teste técnico Backend PL da GEX.

A ideia do projeto foi construir uma esteira de integração para webhooks de gateways: receber eventos, persistir o payload bruto, validar schemas, tratar payloads criptografados, aplicar idempotência, preparar o roteamento para filas e deixar a base pronta para processamento assíncrono de leads.

A implementação prioriza rastreabilidade e segurança operacional. Cada payload recebido fica registrado em `raw_payloads`, cada request recebe um `correlation_id`, os gateways `lous` e `grummer` são tratados conforme seus formatos, e os fluxos de sucesso, descarte, erro de schema, falha de decrypt e duplicidade são separados para facilitar auditoria, reprocessamento e investigação de incidentes.

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
- Decriptar payloads do gateway `grummer` usando AES-256-CBC com PKCS7
- Persistir `body_decrypted` quando o decrypt do Grummer é bem-sucedido
- Marcar falhas de decrypt em `raw_payloads.error_reason`
- Validar payloads de venda após decrypt
- Normalizar campos críticos do cliente, como e-mail, telefone, nome e país
- Aplicar idempotência no receiver por `gateway + transaction_id + event`
- Separar payloads entre `validated`, `discarded`, `schema_failed`, `decrypt_failed` e `duplicate`
- Registrar logs estruturados com `correlation_id` e identificador anonimizado do cliente
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
      decryption.py

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
    structured_logging.py

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
Se o problema está no processamento de leads, fica em `features/leads`.  
Se o problema está na distribuição SMS, fica em `features/distribution`.

O que é compartilhado, como configuração, conexão com banco, tabelas do SQLAlchemy Core e logging estruturado, fica em `shared`.

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

Esse payload é salvo em `raw_payloads`, mas cai como `schema_failed`, porque não possui os campos esperados de uma venda.

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
    "iv": "base64-iv",
    "ciphertext": "base64-ciphertext"
  }'
```

O gateway `grummer` envia payloads criptografados. O receiver valida o envelope `iv/ciphertext`, executa decrypt AES-256-CBC com PKCS7, salva o payload bruto em `body_original` e, quando o decrypt é bem-sucedido, salva o conteúdo decriptado em `body_decrypted`.

Se o envelope estiver inválido, o payload é marcado como `schema_failed`.  
Se o envelope estiver válido, mas o decrypt falhar, o payload é marcado como `decrypt_failed`.

Depois do decrypt, o conteúdo decriptado segue pelo mesmo schema de venda usado no fluxo do gateway `lous`.

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

O objetivo dessa rota não é mascarar falhas. Ela serve para comparar o estado atual da implementação contra os payloads reais do desafio, validar os totais por gateway e status, e facilitar a investigação de casos como schema inválido, decrypt corrompido, payload descartado ou evento duplicado.

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

O receiver fica em `features/webhooks`, o processamento de leads fica em `features/leads` e o distribuidor SMS fica em `features/distribution`.

Isso evita espalhar arquivos relacionados em pastas genéricas como `routers`, `services`, `repositories` e `schemas` no projeto inteiro. Quando algo quebrar em webhook, os arquivos principais daquele fluxo estão próximos.

---

### Router, service e repository

A separação principal ficou assim:

- o router lida com HTTP
- o service decide a esteira de processamento
- o repository concentra o acesso a dados com SQLAlchemy Core
- o shared/db cria a conexão com o banco

O router propositalmente não carrega regra de negócio demais. Ele recebe a request, valida o gateway no path, lê o JSON e chama o service.

O service decide se o payload é `lous` ou `grummer`, executa decrypt quando necessário, valida schema, normaliza campos críticos, aplica idempotência e define se o evento está pronto para seguir para a fila de leads.

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

A regra prática adotada foi:

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

### Decrypt do Grummer

O gateway `grummer` envia o payload de venda dentro de um envelope criptografado com `iv` e `ciphertext`.

A implementação de decrypt fica dentro de `features/webhooks/decryption.py`, porque decrypt não foi tratado como uma feature de negócio isolada. Ele é uma etapa específica do receiver para um gateway de entrada.

O fluxo do Grummer é:

- validar o header `X-GR-Encrypted: true`
- validar o envelope `iv/ciphertext`
- carregar a chave via `GRUMMER_SECRET_HEX` ou `assets/grummer_secret.txt`
- decriptar usando AES-256-CBC com PKCS7
- salvar o plaintext em `body_decrypted`
- validar o conteúdo decriptado com o mesmo schema de venda usado pelo Lous

Falhas de envelope são tratadas como `schema_failed`.  
Falhas de decrypt são tratadas como `decrypt_failed`.

Essa separação ajuda a diferenciar payload malformado de payload criptografado, porém corrompido ou impossível de abrir com a chave esperada.

---

### Validação por schema

Usei Pydantic para validar os formatos principais de entrada.

Hoje existem dois formatos importantes:

- `lous`: payload de venda aberto em JSON
- `grummer`: envelope criptografado contendo `iv` e `ciphertext`

O payload de venda é validado com um schema próprio. O envelope criptografado do `grummer` também é validado antes da etapa de decrypt.

Depois do decrypt, o conteúdo decriptado do Grummer passa pelo mesmo schema de venda usado no fluxo do Lous. Isso evita manter duas regras diferentes para o mesmo evento de negócio.

Além da validação estrutural, alguns campos críticos são normalizados antes do payload seguir para a próxima etapa da esteira.

Hoje o receiver normaliza:

- e-mail com trim, lowercase e validação básica de formato
- telefone removendo caracteres inválidos e sinalizando `phone_is_valid`
- `first_name` vazio usando `"Customer"` como fallback
- `last_name` com trim
- país em uppercase

E-mail inválido bloqueia o payload como `schema_failed`, porque compromete a identificação do lead.  
Telefone inválido não bloqueia o lead, mas é sinalizado com `phone_is_valid = false`, permitindo que canais como SMS decidam depois se devem ou não tentar contato.

---

### Idempotência

A idempotência do receiver é baseada em `gateway + transaction_id + event`.

A ideia é permitir que um mesmo pedido tenha eventos legítimos diferentes ao longo do tempo, sem permitir que o mesmo evento seja processado mais de uma vez.

Exemplo:

```text
lous + ORD-001 + order.approved  -> primeira vez entra
lous + ORD-001 + order.approved  -> segunda vez vira duplicate
lous + ORD-001 + order.refunded  -> evento diferente pode entrar
grummer + ORD-001 + order.approved -> outro gateway não colide com Lous
```

Essa regra é protegida no banco por uma constraint única em `webhook_idempotency_keys`.

A escolha de usar constraint no banco, em vez de apenas consultar antes de inserir, foi proposital. O banco é a melhor camada para proteger contra race condition quando dois webhooks iguais chegam quase ao mesmo tempo.

Mesmo quando o webhook é duplicado, o payload bruto continua sendo persistido em `raw_payloads`. O que não acontece é a republicação para a próxima etapa da esteira.

---

### Logs estruturados

O receiver emite logs estruturados em JSON para facilitar investigação.

Os logs incluem:

- `correlation_id`
- gateway
- status do processamento
- pipeline
- evento de negócio
- latência em milissegundos
- `raw_payload_id`
- identificador anonimizado do cliente

E-mail e telefone não são logados em texto puro.  
Quando um identificador do cliente precisa aparecer no log, ele é anonimizado com hash.

A intenção é manter rastreabilidade operacional sem expor dados sensíveis desnecessariamente.

---

### Roteamento das esteiras

O endpoint público continua sendo o mesmo pedido no desafio:

```text
POST /webhooks/{gateway}
```

Internamente, o service separa as esteiras:

- payload `lous` aprovado, válido e não duplicado fica pronto para publicação em `lead.received`
- payload `grummer` com envelope válido é decriptado e depois validado como evento de venda
- payload com schema inválido é marcado como `schema_failed`
- payload com falha de decrypt é marcado como `decrypt_failed`
- payload com status diferente de `approved` é marcado como `discarded`
- payload repetido por `gateway + transaction_id + event` é marcado como `duplicate`

Neste momento, o receiver já decide se o evento deve seguir para a fila através de `should_publish_to_lead_queue`. A próxima etapa do projeto é transformar essa decisão em publicação real no RabbitMQ.

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

Por enquanto, os workers ainda são stubs. Eles existem para deixar a topologia local parecida com o fluxo final do teste, mas a regra real de consumo, persistência, retry, DLQ e distribuição será implementada na próxima etapa.

A próxima implementação será:

- publicar webhooks validados na fila `lead.received`
- consumir `lead.received` no worker de leads
- persistir `leads`, `orders`, `lead_events` e `distribution_status`
- publicar mensagens nas filas de distribuição por canal
- implementar o distribuidor SMS com webhook.site

---

## Próxima etapa: processamento assíncrono

Com o receiver estabilizado, a próxima etapa do projeto é implementar o fluxo assíncrono a partir da fila `lead.received`.

O fluxo planejado é:

```text
POST /webhooks/{gateway}
  -> raw_payloads
  -> validação/decrypt/normalização/idempotência
  -> lead.received
  -> leads worker
  -> leads / orders / lead_events / distribution_status
  -> dist.sms / dist.email / dist.callcenter / dist.whatsapp
```

A fila `lead.received` representa o contrato interno entre o receiver e o worker de leads. Apenas payloads aprovados, válidos e não duplicados devem ser publicados nela.

O worker de leads será responsável por transformar o evento validado em entidades persistidas no banco e preparar a distribuição para os canais downstream.

---

## Status atual

### Etapa 1 — Receiver de webhooks

Implementado:

- API FastAPI
- MySQL no Docker
- RabbitMQ no Docker
- Estrutura por feature
- Conexão com banco via SQLAlchemy Core
- Persistência de payload bruto em `raw_payloads`
- Decrypt AES-256-CBC real do Grummer
- Validação de schemas para Lous e Grummer decriptado
- Normalização de e-mail, telefone, nome e país
- Idempotência por `gateway + transaction_id + event`
- Logs estruturados com `correlation_id`
- Identificador anonimizado do cliente nos logs
- Debug de payloads recebidos
- Replay local dos payloads reais do desafio via benchmark debug
- Testes automatizados do receiver

### Etapa 2 — Processamento assíncrono e distribuição

Em andamento / próximos passos:

- publicação real na fila `lead.received`
- DLQs reais para decrypt/schema/consumer
- consumer real de leads
- persistência em `leads`, `orders`, `lead_events` e `distribution_status`
- criação das mensagens para `dist.sms`, `dist.email`, `dist.callcenter` e `dist.whatsapp`
- retry e backoff exponencial
- DLQs reais para falhas de consumer e distribuição
- distribuidor SMS real com webhook.site
- queries de auditoria em `audit_queries.sql`
- documentação conceitual do incidente e decisões de arquitetura