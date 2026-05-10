from sqlalchemy.engine import Engine

from source.shared.db import get_engine


def test_get_engine_builds_mysql_engine():
    engine = get_engine()

    assert isinstance(engine, Engine)
    assert engine.url.get_backend_name() == "mysql"
    assert engine.url.get_driver_name() == "pymysql"
