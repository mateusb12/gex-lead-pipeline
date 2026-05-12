from datetime import datetime, timezone
from pathlib import Path

from source.features.leads import repository
from source.features.webhooks.schemas import SalesEventPayload


LEAD_RECEIVED_MESSAGE = {
    "correlation_id": "test-correlation-id",
    "raw_payload_id": 123,
    "gateway": "lous",
    "transaction_id": "ORD-REPOSITORY-001",
    "transaction_time": "2026-05-11T15:00:00+00:00",
    "event": "order.approved",
    "customer": {
        "email": "repository@example.com",
        "first_name": "Repository",
        "last_name": "Customer",
        "phone": "+18005551234",
        "phone_is_valid": True,
        "country": "US",
    },
    "product": {
        "id": "PROD-001",
        "name": "Fit Burn",
        "niche": "weight_loss",
    },
    "quantity": 1,
    "payment": {
        "amount_usd": "99.90",
        "method": "credit_card",
        "status": "approved",
    },
}


class FakeTransactionConnection:
    def __init__(self):
        self.statements = []

    def execute(self, statement, parameters=None):
        self.statements.append((statement, parameters))
        return None


class FakeBeginContext:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, exc_type, exc, traceback):
        return False


class FakeBeginEngine:
    def __init__(self):
        self.connection = FakeTransactionConnection()

    def begin(self):
        return FakeBeginContext(self.connection)


class FakeMappingsResult:
    def one(self):
        return {
            "lead_id": 11,
            "order_id": 22,
            "lead_event_id": 33,
        }


class FakeProcedureResult:
    def mappings(self):
        return FakeMappingsResult()


class FakeProcedureConnection:
    def __init__(self):
        self.isolation_level = None
        self.executed = []

    def execution_options(self, *, isolation_level):
        self.isolation_level = isolation_level
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, statement, parameters):
        self.executed.append((statement, parameters))
        return FakeProcedureResult()


class FakeProcedureEngine:
    def __init__(self):
        self.connection = FakeProcedureConnection()

    def connect(self):
        return self.connection


def test_persist_lead_received_message_preserva_contrato_e_status(monkeypatch):
    fake_engine = FakeBeginEngine()

    monkeypatch.setattr(repository, "get_engine", lambda: fake_engine)
    monkeypatch.setattr(repository, "_call_sp_insert_lead", lambda **kwargs: (11, 22, 33))

    result = repository.persist_lead_received_message(LEAD_RECEIVED_MESSAGE)

    assert result == {
        "lead_id": 11,
        "order_id": 22,
        "event_id": 33,
        "gateway": "lous",
        "transaction_id": "ORD-REPOSITORY-001",
        "event": "order.approved",
        "gateway_to_db_lag_seconds": result["gateway_to_db_lag_seconds"],
        "distribution_channels": ["SMS", "EMAIL", "CALL_CENTER", "WHATSAPP"],
    }
    assert result["gateway_to_db_lag_seconds"] >= 0
    assert len(fake_engine.connection.statements) == 4


def test_call_sp_insert_lead_le_resultset_da_procedure(monkeypatch):
    fake_engine = FakeProcedureEngine()
    sales_event = SalesEventPayload.model_validate(LEAD_RECEIVED_MESSAGE)

    monkeypatch.setattr(repository, "get_engine", lambda: fake_engine)

    result = repository._call_sp_insert_lead(
        sales_event=sales_event,
        gateway="lous",
        correlation_id="test-correlation-id",
        transaction_time=datetime(2026, 5, 11, 15, 0, tzinfo=timezone.utc),
        persisted_at=datetime(2026, 5, 12, 15, 0, tzinfo=timezone.utc),
        gateway_to_db_lag_seconds=86400,
    )

    assert result == (11, 22, 33)
    assert fake_engine.connection.isolation_level == "AUTOCOMMIT"

    _, parameters = fake_engine.connection.executed[0]
    assert parameters["gateway"] == "lous"
    assert parameters["transaction_id"] == "ORD-REPOSITORY-001"
    assert parameters["event"] == "order.approved"
    assert parameters["transaction_time"].tzinfo is None
    assert parameters["persisted_at"].tzinfo is None


def test_sql_da_procedure_declara_upserts_e_transacao():
    sql = (Path(__file__).resolve().parents[1] / "sql" / "003_stored_procs.sql").read_text()

    assert "CREATE PROCEDURE sp_insert_lead" in sql
    assert "START TRANSACTION;" in sql
    assert "COMMIT;" in sql
    assert "ROLLBACK;" in sql
    assert "RESIGNAL;" in sql
    assert sql.count("ON DUPLICATE KEY UPDATE") == 3
    assert sql.count("LAST_INSERT_ID(id)") == 3
