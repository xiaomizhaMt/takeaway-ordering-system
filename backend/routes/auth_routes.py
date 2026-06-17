# ==================================================
# 外卖订餐管理系统 - 认证模块（登录/注册）
# ==================================================
from datetime import datetime
from flask import Blueprint, request, session
from backend.db.db_helper import DBHelper
from backend.services.merchant_type_service import (
    MERCHANT_TYPE_LABELS,
    ensure_merchant_type_schema,
    normalize_merchant_type,
)
from backend.services.location_schema_service import (
    ensure_location_schema,
    parse_latitude,
    parse_location_name,
    parse_longitude,
)
from backend.utils.response import success, error
from backend.services.token_service import token_service

auth_bp = Blueprint('auth', __name__)
db = DBHelper()
_user_pay_password_schema_checked = False


def ensure_user_pay_password_schema():
    """兼容旧数据库：确保用户表存在明文支付密码字段。"""
    global _user_pay_password_schema_checked
    if _user_pay_password_schema_checked:
        return
    exists = db.query_one("SHOW COLUMNS FROM `User` LIKE 'pay_password'")
    if not exists:
        db.execute(
            """ALTER TABLE `User`
               ADD COLUMN `pay_password` VARCHAR(100) NULL
               COMMENT '支付密码（明文）'
               AFTER `password`"""
        )
    db.execute(
        """UPDATE `User`
           SET pay_password = password
           WHERE pay_password IS NULL OR pay_password = ''"""
    )
    _user_pay_password_schema_checked = True


@auth_bp.route('/login', methods=['POST'])
def login():
    """多角色统一登录接口，支持用户、商家、骑手和管理员，并返回独立 token。"""
    data = request.get_json()
    if not data:
        return error('请提供登录信息')

    account = data.get('username', '').strip()
    password = data.get('password', '')
    # 前端按角色保存 token，同一浏览器多标签可同时登录不同角色。
    role = data.get('role', 'user')

    # 管理员不落业务表，使用课程设计固定账号：admin/admin123。
    if role == 'admin':
        if account == 'admin' and password == 'admin123':
            # token 用于当前标签页身份识别，session 仅保留为旧页面兼容。
            token = token_service.generate(0, 'admin', '管理员')
            session['user_id'] = 0
            session['role'] = 'admin'
            session['username'] = '管理员'
            return success({
                'user_id': 0,
                'username': '管理员',
                'role': 'admin',
                'token': token
            }, '管理员登录成功')
        else:
            return error('管理员账号或密码错误')

    table_map = {
        'user': ('User', 'username', 'user_id', 'real_name', '用户'),
        'merchant': ('Merchant', 'account', 'merchant_id', 'shop_name', '商家'),
        'rider': ('Rider', 'account', 'rider_id', 'rider_name', '配送员')
    }

    if role not in table_map:
        return error('无效的登录角色')

    table, account_field, id_field, name_field, role_cn = table_map[role]

    sql = f"SELECT * FROM `{table}` WHERE `{account_field}` = %s AND `password` = %s"
    user = db.query_one(sql, (account, password))

    if not user:
        return error('账号或密码错误')

    if table == 'User' and user.get('account_status') == 0:
        return error('账号已被禁用')
    if table == 'Merchant' and user.get('audit_status') != 1:
        return error('商家账号已注册，但尚未通过平台审核，请管理员审核通过后再登录')
    if table == 'Rider' and user.get('audit_status') != 1:
        return error('配送员账号已注册，但尚未通过平台审核，请管理员审核通过后再登录')

    user_id = user[id_field]
    username = user[name_field]

    # 生成按角色隔离的 token，避免多账号同浏览器操作时互相覆盖。
    token = token_service.generate(user_id, role, username)

    # 兼容依赖 session 的旧接口；新页面优先读取 X-Auth-Token。
    session['user_id'] = user_id
    session['role'] = role
    session['username'] = username

    return success({
        'user_id': user_id,
        'username': username,
        'role': role,
        'token': token
    }, f'{role_cn}登录成功')


@auth_bp.route('/register', methods=['POST'])
def register():
    """多角色注册接口，按角色写入用户、商家或骑手表。"""
    data = request.get_json()
    if not data:
        return error('请提供注册信息')

    ensure_location_schema()

    role = data.get('role', 'user').strip().lower()
    username = data.get('username', '').strip()
    password = data.get('password', '')
    phone = data.get('phone', '').strip()

    if not all([username, password, phone]):
        return error('账号、密码、手机号为必填项')

    if role == 'user':
        ensure_user_pay_password_schema()
        real_name = data.get('real_name', '').strip()
        pay_password = data.get('pay_password') or data.get('payment_password') or password
        if not real_name:
            return error('请输入姓名')

        exist = db.query_one("SELECT user_id FROM `User` WHERE username = %s", (username,))
        if exist:
            return error('该账号已被注册')
        exist_phone = db.query_one("SELECT user_id FROM `User` WHERE phone = %s", (phone,))
        if exist_phone:
            return error('该手机号已被注册')

        # 用户默认地址允许纯文本填写，也允许地图选点后附带经纬度。
        default_latitude = parse_latitude(data.get('default_latitude') or data.get('latitude'))
        default_longitude = parse_longitude(data.get('default_longitude') or data.get('longitude'))
        default_location_name = parse_location_name(data.get('default_location_name') or data.get('location_name'))
        sql = """INSERT INTO `User` (username, password, pay_password, real_name, phone, default_receiver,
                 default_phone, default_address, default_latitude, default_longitude, default_location_name,
                 account_status, register_time)
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, %s)"""
        params = (username, password, pay_password, real_name, phone,
                  real_name, phone, '', default_latitude, default_longitude, default_location_name, datetime.now())
        try:
            user_id = db.execute_return_id(sql, params)
            return success({'user_id': user_id}, '用户注册成功')
        except Exception as e:
            return error(f'注册失败：{str(e)}')

    elif role == 'merchant':
        ensure_merchant_type_schema()
        contact_name = data.get('contact_name', '').strip()
        shop_name = data.get('shop_name', '').strip()
        shop_address = data.get('shop_address', '').strip()
        merchant_type = normalize_merchant_type(data.get('merchant_type'), default='')
        if not all([contact_name, shop_name, shop_address]):
            return error('联系人姓名、店铺名称、店铺地址为必填项')
        if not merchant_type:
            return error('请选择商家类型：' + '、'.join(MERCHANT_TYPE_LABELS))

        exist = db.query_one("SELECT merchant_id FROM `Merchant` WHERE account = %s", (username,))
        if exist:
            return error('该账号已被注册')

        # 商家地址经纬度保存到店铺表，后续下单和骑手排序直接使用本地数据计算。
        shop_latitude = parse_latitude(data.get('shop_latitude') or data.get('latitude'))
        shop_longitude = parse_longitude(data.get('shop_longitude') or data.get('longitude'))
        shop_location_name = parse_location_name(data.get('shop_location_name') or data.get('location_name'))
        sql = """INSERT INTO `Merchant` (account, password, shop_name, contact_name, contact_phone,
                 shop_address, shop_latitude, shop_longitude, shop_location_name, shop_desc, merchant_type,
                 business_status, audit_status)
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, 0)"""
        params = (username, password, shop_name, contact_name, phone,
                  shop_address, shop_latitude, shop_longitude, shop_location_name,
                  data.get('shop_desc', ''), merchant_type)
        try:
            merchant_id = db.execute_return_id(sql, params)
            return success({'merchant_id': merchant_id}, '商家注册成功，请等待平台审核')
        except Exception as e:
            return error(f'注册失败：{str(e)}')

    elif role == 'rider':
        rider_name = data.get('rider_name', '').strip()
        if not rider_name:
            return error('请输入配送员姓名')

        exist = db.query_one("SELECT rider_id FROM `Rider` WHERE account = %s", (username,))
        if exist:
            return error('该账号已被注册')
        exist_phone = db.query_one("SELECT rider_id FROM `Rider` WHERE phone = %s", (phone,))
        if exist_phone:
            return error('该手机号已被注册')

        id_card = data.get('id_card', '').strip()
        if not id_card:
            return error('请输入身份证号')
        exist_id_card = db.query_one("SELECT rider_id FROM `Rider` WHERE id_card = %s", (id_card,))
        if exist_id_card:
            return error('该身份证号已被注册')

        sql = """INSERT INTO `Rider` (account, password, rider_name, phone, id_card,
                 work_status, audit_status, register_time)
                 VALUES (%s, %s, %s, %s, %s, 0, 0, %s)"""
        params = (username, password, rider_name, phone,
                  id_card, datetime.now())
        try:
            rider_id = db.execute_return_id(sql, params)
            return success({'rider_id': rider_id}, '配送员注册成功，请等待平台审核')
        except Exception as e:
            return error(f'注册失败：{str(e)}')

    else:
        return error('无效的角色类型')


@auth_bp.route('/logout', methods=['POST'])
def logout():
    """退出登录接口，同时清理 token 和兼容 session。"""
    # 优先移除当前请求携带的 token，避免影响其他角色或其他标签页。
    auth_header = request.headers.get('X-Auth-Token', '')
    if auth_header:
        token_service.remove(auth_header)
    session.clear()
    return success(None, '已退出登录')


@auth_bp.route('/current_user', methods=['GET'])
def current_user():
    """获取当前登录用户信息，优先使用 token，失败后兼容 session。"""
    # 1. 优先使用 X-Auth-Token 请求头。
    auth_header = request.headers.get('X-Auth-Token', '')
    if auth_header:
        user_info = token_service.get_user(auth_header)
        if user_info:
            return success({
                'user_id': user_info['user_id'],
                'role': user_info['role'],
                'username': user_info['username']
            })
        return error('token 无效或已过期', 401)

    # 2. 回退到 session，兼容早期未接入 token 的页面。
    user_id = session.get('user_id')
    role = session.get('role')
    if user_id is None:
        return error('未登录', 401)

    return success({
        'user_id': user_id,
        'role': role,
        'username': session.get('username')
    })


@auth_bp.route('/token_login', methods=['POST'])
def token_login():
    """使用前端缓存的 token 恢复登录状态。"""
    data = request.get_json()
    if not data or not data.get('token'):
        return error('请提供 token')

    token = data.get('token')
    user_info = token_service.get_user(token)
    if not user_info:
        return error('token 无效或已过期', 401)

    # 刷新 session，方便仍读取 session 的旧接口继续工作。
    session['user_id'] = user_info['user_id']
    session['role'] = user_info['role']
    session['username'] = user_info['username']

    return success({
        'user_id': user_info['user_id'],
        'role': user_info['role'],
        'username': user_info['username'],
        'token': token
    })
