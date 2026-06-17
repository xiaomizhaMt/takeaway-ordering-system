class DatabaseConfig:
    HOST = 'localhost'
    PORT = 3306
    USER = 'root'
    PASSWORD = 'your_mysql_password'
    DATABASE = 'takeaway_ordering_system'
    CHARSET = 'utf8mb4'


class AppConfig:
    SECRET_KEY = 'change-me'
    DEBUG = True
    HOST = '127.0.0.1'
    PORT = 5000
