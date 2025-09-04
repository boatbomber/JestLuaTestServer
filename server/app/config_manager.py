"""Centralized configuration management with environment-specific overrides"""

import os
from typing import Literal

from pydantic_settings import BaseSettings


class BaseConfig(BaseSettings):
    """Base configuration with common settings"""

    host: str = "127.0.0.1"
    port: int = 8325
    test_timeout: int = 30
    chunk_size: int = 8192
    log_level: str = "INFO"

    # Authentication
    enable_auth: bool = True

    # Rate limiting
    max_requests_per_minute: int = 10
    max_rbxm_size: int = 50 * 1024 * 1024  # 50MB

    # Graceful shutdown
    shutdown_timeout: int = 30

    # CORS settings
    cors_origins: list[str] = ["*"]

    class Config:
        env_prefix = "JEST_TEST_SERVER_"
        case_sensitive = False


class DevelopmentConfig(BaseConfig):
    """Development-specific configuration"""

    log_level: str = "DEBUG"
    # Allow all origins in development
    cors_origins: list[str] = ["*"]
    # More lenient rate limiting in dev
    max_requests_per_minute: int = 60


class ProductionConfig(BaseConfig):
    """Production-specific configuration"""

    log_level: str = "INFO"
    # Restrict CORS in production
    cors_origins: list[str] = ["http://localhost:*"]
    # Stricter rate limiting in production
    max_requests_per_minute: int = 10
    # Longer timeouts for production stability
    test_timeout: int = 60
    shutdown_timeout: int = 60


class TestingConfig(BaseConfig):
    """Test-specific configuration"""

    log_level: str = "DEBUG"
    cors_origins: list[str] = ["*"]
    test_timeout: int = 5
    shutdown_timeout: int = 5
    # Use different port for tests to avoid conflicts
    port: int = 8326
    # Disable auth for testing
    enable_auth: bool = False


def get_config(
    env: Literal["development", "production", "test"] | None = None,
) -> BaseConfig:
    """Get configuration based on environment"""
    if env is None:
        env = os.getenv("JEST_TEST_SERVER_ENV", "development").lower()

    configs = {
        "development": DevelopmentConfig,
        "production": ProductionConfig,
        "test": TestingConfig,
    }

    config_class = configs.get(env, DevelopmentConfig)
    return config_class()


# Export singleton instance
config = get_config()
