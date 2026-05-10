from sqlalchemy.engine import Engine

from source.shared.db import get_engine


def test_criar_engine_mysql_com_driver_pymysql():
    engine = get_engine()

    assert isinstance(engine, Engine)
    assert engine.url.get_backend_name() == "mysql"
    assert engine.url.get_driver_name() == "pymysql"
