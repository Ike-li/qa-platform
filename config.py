import os

from dotenv import load_dotenv

load_dotenv()


class BaseConfig:
    """Base configuration shared across all environments."""

    SECRET_KEY = os.environ.get("SECRET_KEY", "")
    FERNET_KEY = os.environ.get("FERNET_KEY", "")

    if not SECRET_KEY or SECRET_KEY == "change-me":
        raise ValueError(
            "SECRET_KEY must be set via environment variable. "
            "Generate with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    if not FERNET_KEY:
        raise ValueError(
            "FERNET_KEY must be set via environment variable. "
            "Generate with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )

    # SQLAlchemy
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "mysql+pymysql://qauser:qapass@mysql:3306/qaplatform",
    )

    # Celery
    CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
    CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1")
    CELERY_ACCEPT_CONTENT = ["json"]
    CELERY_TASK_SERIALIZER = "json"
    CELERY_RESULT_SERIALIZER = "json"
    CELERY_TIMEZONE = "UTC"
    CELERY_ENABLE_UTC = True

    # Allure
    ALLURE_REPORTS_DIR = os.getenv("ALLURE_REPORTS_DIR", "/app/allure-reports")
    ALLURE_RESULTS_DIR = os.getenv("ALLURE_RESULTS_DIR", "/app/allure-results")

    # Execution paths
    EXECUTION_VENV_DIR = os.getenv("EXECUTION_VENV_DIR", "/data/venvs")
    EXECUTION_RESULTS_DIR = os.getenv("EXECUTION_RESULTS_DIR", "/data/execution_results")
    REPO_DIR = os.getenv("REPO_DIR", "/data/repos")


class DevConfig(BaseConfig):
    """Development configuration."""

    DEBUG = True
    SQLALCHEMY_ECHO = True


class TestConfig(BaseConfig):
    """Testing configuration."""

    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "TEST_DATABASE_URL",
        "mysql+pymysql://qauser:qapass@mysql:3306/qaplatform_test",
    )
    WTF_CSRF_ENABLED = False


class ProdConfig(BaseConfig):
    """Production configuration."""

    DEBUG = False
    SQLALCHEMY_ECHO = False


config_by_name = {
    "development": DevConfig,
    "testing": TestConfig,
    "production": ProdConfig,
}
