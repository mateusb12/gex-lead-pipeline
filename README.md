# GEX Lead Pipeline

Solução para o teste técnico Backend PL da GEX.

A ideia é simular uma esteira de integração que recebe webhooks de gateways, valida payloads, persiste dados brutos, publica eventos em filas, processa leads e distribui para canais.

## Stack

- Python
- FastAPI
- MySQL
- RabbitMQ
- Docker Compose
- Pytest
- Ruff

## Estrutura

Código da aplicação:

    source/

Entrada HTTP principal:

    source/main.py

Arquitetura principal:

    source/features/
    source/shared/

Features:

    source/features/webhooks/
    source/features/leads/
    source/features/distribution/

Compartilhado:

    source/shared/

## Como rodar

Subir tudo:

    docker compose up --build

API:

    http://localhost:8000

Health check:

    curl http://localhost:8000/health

Webhook stub:

    curl -X POST http://localhost:8000/webhooks/lous \
      -H "Content-Type: application/json" \
      -d '{"hello":"world"}'

RabbitMQ Management:

    http://localhost:15672

Credenciais RabbitMQ:

    user: guest
    password: guest

## Testes

Instalar dependências locais:

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -e ".[dev]"

Rodar testes:

    pytest

Rodar lint:

    ruff check .

## Status atual

Primeiro esqueleto do projeto:

- API FastAPI
- MySQL no Docker
- RabbitMQ no Docker
- Worker stub
- SMS distributor stub
- SQL inicial
- Teste mínimo de health check
