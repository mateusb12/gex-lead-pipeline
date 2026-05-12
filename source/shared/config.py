from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_env: str = "local"

    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "gex"
    mysql_password: str = "gex"
    mysql_database: str = "gex_pipeline"

    rabbitmq_host: str = "localhost"
    rabbitmq_port: int = 5672

    grummer_secret_hex: str | None = None

    sms_webhook_url: str | None = None

    @property
    def database_url(self) -> str:
        host = f"{self.mysql_host}:{self.mysql_port}"
        return f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}@{host}/{self.mysql_database}"

    @property
    def is_debug_env(self) -> bool:
        return self.app_env in {"local", "dev", "debug"}


settings = Settings()
