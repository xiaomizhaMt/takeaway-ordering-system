# ==================================================
# 外卖订餐管理系统 - Token 认证服务
# ==================================================
import uuid

class TokenService:
    """Token 管理（内存存储，支持多角色并发登录）"""

    def __init__(self):
        # token 映射到用户身份信息，前端每个角色单独保存一个 token。
        self._tokens = {}

    def generate(self, user_id, role, username):
        """生成新 token"""
        token = uuid.uuid4().hex
        self._tokens[token] = {
            'user_id': user_id,
            'role': role,
            'username': username
        }
        return token

    def get_user(self, token):
        """通过 token 获取用户信息"""
        return self._tokens.get(token)

    def remove(self, token):
        """移除 token（登出）"""
        self._tokens.pop(token, None)

# 全局单例，供认证辅助函数和登录接口复用。
token_service = TokenService()
