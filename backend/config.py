import os

# ==================================================
# Application configuration
# ==================================================


class DatabaseConfig:
    """MySQL database connection configuration."""

    HOST = os.getenv('DB_HOST', 'localhost')
    PORT = int(os.getenv('DB_PORT', '3306'))
    USER = os.getenv('DB_USER', 'root')
    PASSWORD = os.getenv('DB_PASSWORD', '')
    DATABASE = os.getenv('DB_NAME', 'takeaway_ordering_system')
    CHARSET = os.getenv('DB_CHARSET', 'utf8mb4')


class AppConfig:
    """Flask runtime configuration."""

    SECRET_KEY = os.getenv('APP_SECRET_KEY', 'dev-secret-key-change-me')
    DEBUG = os.getenv('APP_DEBUG', 'true').lower() == 'true'
    HOST = os.getenv('APP_HOST', '127.0.0.1')
    PORT = int(os.getenv('APP_PORT', '5000'))


def _apply_local_overrides():
    """Allow ignored backend/config_local.py to override deployed secrets."""
    try:
        from backend.config_local import AppConfig as LocalAppConfig
        from backend.config_local import DatabaseConfig as LocalDatabaseConfig
    except ImportError:
        return

    for name in ('HOST', 'PORT', 'USER', 'PASSWORD', 'DATABASE', 'CHARSET'):
        if hasattr(LocalDatabaseConfig, name):
            setattr(DatabaseConfig, name, getattr(LocalDatabaseConfig, name))

    for name in ('SECRET_KEY', 'DEBUG', 'HOST', 'PORT'):
        if hasattr(LocalAppConfig, name):
            setattr(AppConfig, name, getattr(LocalAppConfig, name))


_apply_local_overrides()
