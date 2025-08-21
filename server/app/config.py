from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 8325

    test_timeout: int = 30

    chunk_size: int = 8192

    log_level: str = "INFO"

    class Config:
        env_prefix = "JEST_TEST_SERVER_"
        env_file = ".env"


settings = Settings()
