# ==================================================
# 外卖订餐管理系统 - 统一认证辅助函数
# ==================================================
from flask import request, session
from backend.services.token_service import token_service


def get_current_user(required_role):
    """
    获取当前登录用户信息，支持 Token 和 Session 两种方式。
    
    - Token 方式：前端通过 X-Auth-Token 请求头传入 token（多角色并发登录）
    - Session 方式：兼容旧逻辑，通过 cookie session 获取
    
    返回: user_id (int) 或 None
    """
    # 1. 优先使用 X-Auth-Token 请求头
    auth_header = request.headers.get('X-Auth-Token', '')
    if auth_header:
        user_info = token_service.get_user(auth_header)
        if user_info and user_info['role'] == required_role:
            return user_info['user_id']
        return None
    
    # 2. 回退到 session
    user_id = session.get('user_id')
    role = session.get('role')
    if user_id is not None and role == required_role:
        return user_id
    
    return None
