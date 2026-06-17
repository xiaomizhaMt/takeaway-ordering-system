# ==================================================
# 外卖订餐管理系统 - 启动入口
# ==================================================
import os
import sys

# 将项目根目录加入 Python 路径，确保从任意位置启动时都能导入 backend 包。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.app import create_app

app = create_app()

if __name__ == '__main__':
    import io
    from backend.config import AppConfig

    # Windows 终端默认编码可能不是 UTF-8，显式设置后中文启动日志不会乱码。
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    print('[外卖订餐管理系统] 启动中...')
    print(f'   访问地址: http://{AppConfig.HOST}:{AppConfig.PORT}')
    app.run(debug=AppConfig.DEBUG, host=AppConfig.HOST, port=AppConfig.PORT)
