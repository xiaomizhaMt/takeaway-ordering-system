# ==================================================
# 外卖订餐管理系统 - Flask 应用入口
# ==================================================
import os
from datetime import datetime, timezone, timedelta
from flask import Flask, send_from_directory
from flask.json.provider import DefaultJSONProvider
from flask_cors import CORS
from backend.config import AppConfig


class CustomJSONProvider(DefaultJSONProvider):
    """统一处理接口响应中的 datetime 序列化。

    Flask 默认会把没有时区的 datetime 输出为不带偏移量的字符串，前端
    `new Date()` 在部分浏览器中会按 UTC 解析，导致展示时间偏移。这里在
    输出前补上本机时区，让前后端看到的业务时间一致。
    """

    def default(self, obj):
        if isinstance(obj, datetime):
            if obj.tzinfo is None:
                # 将数据库中的无时区时间补成本机时区，再输出 ISO 字符串。
                local_tz = datetime.now(timezone.utc).astimezone().tzinfo
                obj = obj.replace(tzinfo=local_tz)
            return obj.isoformat()
        return super().default(obj)


def create_app():
    app = Flask(__name__, static_folder=None)
    app.secret_key = AppConfig.SECRET_KEY

    # 所有接口统一使用自定义 JSON 编码器，避免 datetime 时区显示偏移。
    app.json = CustomJSONProvider(app)

    # Session 用于兼容旧页面逻辑；多账号并发主要依赖前端按角色保存的 token。
    app.config.update(
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_PERMANENT=True,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=24),
        SESSION_COOKIE_SECURE=False,      # 开发环境使用 HTTP，生产 HTTPS 可改为 True。
    )

    CORS(app, supports_credentials=True)

    # 每次请求结束后关闭当前上下文的数据库连接。
    from backend.db.db_helper import close_db
    app.teardown_appcontext(close_db)

    # 注册各角色接口蓝图。
    from backend.routes.auth_routes import auth_bp
    # 用户、商家、骑手、管理员接口按角色拆分，统一挂载到 /api 下。
    from backend.routes.user_routes import user_bp
    from backend.routes.merchant_routes import merchant_bp
    from backend.routes.rider_routes import rider_bp
    from backend.routes.admin_routes import admin_bp

    # 注册接口蓝图，并统一添加 /api 前缀区分接口和前端页面路由。
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(user_bp, url_prefix='/api/user')
    app.register_blueprint(merchant_bp, url_prefix='/api/merchant')
    app.register_blueprint(rider_bp, url_prefix='/api/rider')
    app.register_blueprint(admin_bp, url_prefix='/api/admin')

    # 前端页面和静态资源由 Flask 直接托管，方便课程设计本地一键启动。
    frontend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'frontend')

    @app.route('/')
    def index():
        return send_from_directory(frontend_dir, 'index.html')

    @app.route('/<path:filename>')
    def serve_static(filename):
        return send_from_directory(frontend_dir, filename)

    @app.route('/pages/<path:subpath>')
    def serve_pages(subpath):
        return send_from_directory(os.path.join(frontend_dir, 'pages'), subpath)

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=AppConfig.DEBUG, host=AppConfig.HOST, port=AppConfig.PORT)
