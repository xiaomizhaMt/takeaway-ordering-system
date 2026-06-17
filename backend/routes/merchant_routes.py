# ==================================================
# 外卖订餐管理系统 - 商家端模块
# ==================================================
import os
import uuid
from datetime import datetime
from flask import Blueprint, request
from werkzeug.utils import secure_filename
from backend.db.db_helper import DBHelper
from backend.services.merchant_type_service import ensure_merchant_type_schema, normalize_merchant_type
from backend.services.location_schema_service import (
    ensure_location_schema,
    parse_latitude,
    parse_location_name,
    parse_longitude,
)
from backend.services.order_safety_service import ensure_order_edge_schema
from backend.services.wallet_service import (
    backfill_wallet_income,
    ensure_wallet_schema,
    get_wallet,
    withdraw_wallet,
)
from backend.utils.response import success, error, unauthorized
from backend.utils.auth_helper import get_current_user

merchant_bp = Blueprint('merchant', __name__)
db = DBHelper()


@merchant_bp.before_request
def ensure_merchant_edge_schema():
    """商家端接口访问前补齐订单、类型、地图和钱包相关兼容字段。"""
    ensure_order_edge_schema()
    ensure_merchant_type_schema()
    ensure_location_schema()
    ensure_wallet_schema()

ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
FIXED_DISH_CATEGORIES = ['盖饭', '甜品', '水果', '小吃', '饮品', '主食', '夜宵', '粥粉面']


def _allowed_image(filename):
    """校验上传图片扩展名，避免非图片文件进入公开上传目录。"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


def _dish_upload_dir():
    """返回菜品图片上传目录，并在目录缺失时自动创建。"""
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    upload_dir = os.path.join(root, 'frontend', 'uploads', 'dishes')
    os.makedirs(upload_dir, exist_ok=True)
    return upload_dir


def _merchant_upload_dir():
    """返回商家店铺图片上传目录，并在目录缺失时自动创建。"""
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    upload_dir = os.path.join(root, 'frontend', 'uploads', 'merchants')
    os.makedirs(upload_dir, exist_ok=True)
    return upload_dir


@merchant_bp.route('/wallet', methods=['GET'])
def get_merchant_wallet():
    """查询商家钱包余额和流水。"""
    merchant_id = get_current_user('merchant')
    if not merchant_id:
        return unauthorized()
    try:
        backfill_wallet_income()
        return success(get_wallet('merchant', merchant_id))
    except Exception as e:
        return error(f'查询钱包失败：{str(e)}')


@merchant_bp.route('/wallet/withdraw', methods=['POST'])
def withdraw_merchant_wallet():
    """商家模拟提现。"""
    merchant_id = get_current_user('merchant')
    if not merchant_id:
        return unauthorized()
    data = request.get_json() or {}
    try:
        result = withdraw_wallet(
            'merchant',
            merchant_id,
            data.get('amount'),
            data.get('pay_channel') or data.get('withdraw_channel') or 'bank_card',
        )
        return success(result, '提现成功')
    except Exception as e:
        return error(f'提现失败：{str(e)}')


# ========== 店铺信息管理 ==========

@merchant_bp.route('/shop', methods=['GET'])
def get_shop_info():
    """查询店铺信息"""
    merchant_id = get_current_user('merchant')
    if not merchant_id:
        return unauthorized()

    shop = db.query_one("SELECT * FROM `Merchant` WHERE merchant_id = %s", (merchant_id,))
    if not shop:
        return error('店铺不存在')
    return success(shop)


@merchant_bp.route('/shop', methods=['PUT'])
def update_shop_info():
    """修改店铺信息"""
    merchant_id = get_current_user('merchant')
    if not merchant_id:
        return unauthorized()

    data = request.get_json()
    if not data:
        return error('请提供修改信息')

    update_fields = []
    params = []
    allowed = ['shop_name', 'contact_name', 'contact_phone', 'shop_address',
               'shop_latitude', 'shop_longitude', 'shop_location_name',
               'shop_image_url', 'business_hours', 'shop_desc', 'business_status', 'merchant_type']
    for field in allowed:
        if field in data:
            if field == 'merchant_type':
                merchant_type = normalize_merchant_type(data[field], default='')
                if not merchant_type:
                    return error('请选择有效的商家类型')
                data[field] = merchant_type
            if field == 'shop_latitude':
                data[field] = parse_latitude(data[field])
            elif field == 'shop_longitude':
                data[field] = parse_longitude(data[field])
            elif field == 'shop_location_name':
                data[field] = parse_location_name(data[field])
            update_fields.append(f"`{field}` = %s")
            params.append(data[field])

    if not update_fields:
        return error('没有需要修改的字段')

    params.append(merchant_id)
    sql = f"UPDATE `Merchant` SET {', '.join(update_fields)} WHERE merchant_id = %s"
    try:
        db.execute(sql, params)
        return success(None, '修改成功')
    except Exception as e:
        return error(f'修改失败：{str(e)}')


# ========== 菜品分类管理 ==========

@merchant_bp.route('/shop/image', methods=['POST'])
def upload_shop_image():
    """上传商家店铺图片，并保存到 Merchant.shop_image_url。"""
    merchant_id = get_current_user('merchant')
    if not merchant_id:
        return unauthorized()

    file = request.files.get('image')
    if not file or not file.filename:
        return error('请选择要上传的图片')
    if not _allowed_image(file.filename):
        return error('仅支持 png、jpg、jpeg、gif、webp 格式图片')

    ext = secure_filename(file.filename).rsplit('.', 1)[1].lower()
    filename = f"merchant{merchant_id}_shop_{uuid.uuid4().hex[:12]}.{ext}"
    save_path = os.path.join(_merchant_upload_dir(), filename)
    file.save(save_path)

    image_url = f"/uploads/merchants/{filename}"
    db.execute(
        "UPDATE `Merchant` SET shop_image_url = %s WHERE merchant_id = %s",
        (image_url, merchant_id),
    )
    return success({"shop_image_url": image_url}, "图片上传成功")


@merchant_bp.route('/categories', methods=['GET'])
def list_categories():
    """查询固定菜品分类"""
    merchant_id = get_current_user('merchant')
    if not merchant_id:
        return unauthorized()

    return success(FIXED_DISH_CATEGORIES)


# ========== 菜品管理 ==========

@merchant_bp.route('/dishes', methods=['GET'])
def list_dishes():
    """查询商家菜品列表，支持名称/分类/上下架/库存预警筛选。"""
    merchant_id = get_current_user('merchant')
    if not merchant_id:
        return unauthorized()

    keyword = request.args.get('keyword', '').strip()
    category = request.args.get('category', '').strip()
    sale_status = request.args.get('sale_status', type=int)
    stock_alert = request.args.get('stock_alert', type=int)

    conditions = ["merchant_id = %s"]
    params = [merchant_id]
    if keyword:
        conditions.append("(dish_name LIKE %s OR dish_desc LIKE %s OR specification LIKE %s)")
        kw = f"%{keyword}%"
        params.extend([kw, kw, kw])
    if category:
        conditions.append("category_name = %s")
        params.append(category)
    if sale_status is not None:
        conditions.append("sale_status = %s")
        params.append(sale_status)
    if stock_alert == 1:
        conditions.append("warning_stock > 0 AND stock <= warning_stock")

    dishes = db.query_all(
        """SELECT * FROM `Dish`
           WHERE """ + " AND ".join(conditions) + """
           ORDER BY FIELD(category_name, '盖饭', '甜品', '水果', '小吃', '饮品', '主食', '夜宵', '粥粉面'), dish_id""",
        params)
    return success(dishes)


@merchant_bp.route('/dishes', methods=['POST'])
def add_dish():
    """新增菜品"""
    merchant_id = get_current_user('merchant')
    if not merchant_id:
        return unauthorized()

    data = request.get_json()
    if not data or not data.get('dish_name'):
        return error('菜品名称不能为空')
    category_name = (data.get('category_name') or '').strip()
    if category_name not in FIXED_DISH_CATEGORIES:
        return error('菜品分类必须从固定分类中选择')

    sql = """INSERT INTO `Dish` (merchant_id, category_name, dish_name, dish_desc,
             image_url, price, specification, stock, warning_stock, sale_status, sales_count)
             VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0)"""
    params = (merchant_id, category_name, data['dish_name'],
              data.get('dish_desc', ''), data.get('image_url', ''),
              data.get('price', 0), data.get('specification', ''),
              data.get('stock', 0), data.get('warning_stock', 0),
              data.get('sale_status', 0))

    try:
        dish_id = db.execute_return_id(sql, params)
        return success({'dish_id': dish_id}, '新增成功')
    except Exception as e:
        return error(f'新增失败：{str(e)}')


@merchant_bp.route('/dishes/<int:dish_id>', methods=['PUT'])
def update_dish(dish_id):
    """修改菜品"""
    merchant_id = get_current_user('merchant')
    if not merchant_id:
        return unauthorized()

    data = request.get_json()
    if not data:
        return error('请提供修改信息')
    if 'category_name' in data:
        category_name = (data.get('category_name') or '').strip()
        if category_name not in FIXED_DISH_CATEGORIES:
            return error('菜品分类必须从固定分类中选择')
        data['category_name'] = category_name

    update_fields = []
    params = []
    allowed = ['category_name', 'dish_name', 'dish_desc', 'image_url', 'price',
               'specification', 'stock', 'warning_stock', 'sale_status']
    for field in allowed:
        if field in data:
            update_fields.append(f"`{field}` = %s")
            params.append(data[field])

    if not update_fields:
        return error('没有需要修改的字段')

    params.extend([dish_id, merchant_id])
    sql = f"UPDATE `Dish` SET {', '.join(update_fields)} WHERE dish_id = %s AND merchant_id = %s"
    try:
        affected = db.execute(sql, params)
        if affected == 0:
            return error('菜品不存在或无权限修改')
        return success(None, '修改成功')
    except Exception as e:
        return error(f'修改失败：{str(e)}')


@merchant_bp.route('/dishes/<int:dish_id>/shelf', methods=['PUT'])
def update_dish_shelf_status(dish_id):
    """Put a dish on/off shelf; stock must be positive before putting on shelf."""
    merchant_id = get_current_user('merchant')
    if not merchant_id:
        return unauthorized()

    data = request.get_json() or {}
    sale_status = data.get('sale_status')
    if sale_status not in (0, 1):
        return error('sale_status must be 0(off shelf) or 1(on shelf)')

    dish = db.query_one(
        "SELECT dish_id, stock FROM `Dish` WHERE dish_id = %s AND merchant_id = %s",
        (dish_id, merchant_id),
    )
    if not dish:
        return error('Dish not found or no permission', 404)
    if sale_status == 1 and int(dish.get('stock') or 0) <= 0:
        return error('Dish with zero stock cannot be put on shelf; please stock in first')

    db.execute(
        "UPDATE `Dish` SET sale_status = %s WHERE dish_id = %s AND merchant_id = %s",
        (sale_status, dish_id, merchant_id),
    )
    return success(None, 'Dish put on shelf' if sale_status == 1 else 'Dish taken off shelf')


@merchant_bp.route('/dishes/<int:dish_id>/stock-in', methods=['PUT'])
def stock_in_dish(dish_id):
    """Stock in/replenish a dish atomically; optionally set shelf status."""
    merchant_id = get_current_user('merchant')
    if not merchant_id:
        return unauthorized()

    data = request.get_json() or {}
    try:
        quantity = int(data.get('quantity') or 0)
    except (TypeError, ValueError):
        return error('quantity must be a positive integer')
    if quantity <= 0:
        return error('quantity must be a positive integer')

    set_sale_status = data.get('sale_status')
    if set_sale_status is not None and set_sale_status not in (0, 1):
        return error('sale_status must be 0(off shelf) or 1(on shelf)')

    if set_sale_status is None:
        sql = "UPDATE `Dish` SET stock = stock + %s WHERE dish_id = %s AND merchant_id = %s"
        params = (quantity, dish_id, merchant_id)
    else:
        sql = "UPDATE `Dish` SET stock = stock + %s, sale_status = %s WHERE dish_id = %s AND merchant_id = %s"
        params = (quantity, set_sale_status, dish_id, merchant_id)
    affected = db.execute(sql, params)
    if affected == 0:
        return error('Dish not found or no permission', 404)
    dish = db.query_one(
        "SELECT dish_id, dish_name, stock, sale_status FROM `Dish` WHERE dish_id = %s AND merchant_id = %s",
        (dish_id, merchant_id),
    )
    return success(dish, 'Stock-in completed')


@merchant_bp.route('/dishes/<int:dish_id>/image', methods=['POST'])
def upload_dish_image(dish_id):
    """商家本地上传菜品图片，保存后写入 Dish.image_url。"""
    merchant_id = get_current_user('merchant')
    if not merchant_id:
        return unauthorized()

    dish = db.query_one(
        "SELECT dish_id, image_url FROM `Dish` WHERE dish_id = %s AND merchant_id = %s",
        (dish_id, merchant_id))
    if not dish:
        return error('菜品不存在或无权限修改', 404)

    file = request.files.get('image')
    if not file or not file.filename:
        return error('请选择要上传的图片')
    if not _allowed_image(file.filename):
        return error('仅支持 png、jpg、jpeg、gif、webp 格式图片')

    ext = secure_filename(file.filename).rsplit('.', 1)[1].lower()
    filename = f"merchant{merchant_id}_dish{dish_id}_{uuid.uuid4().hex[:12]}.{ext}"
    save_path = os.path.join(_dish_upload_dir(), filename)
    file.save(save_path)

    image_url = f"/uploads/dishes/{filename}"
    db.execute(
        "UPDATE `Dish` SET image_url = %s WHERE dish_id = %s AND merchant_id = %s",
        (image_url, dish_id, merchant_id))
    return success({"dish_id": dish_id, "image_url": image_url}, "图片上传成功")


@merchant_bp.route('/dishes/<int:dish_id>', methods=['DELETE'])
def delete_dish(dish_id):
    """删除菜品"""
    merchant_id = get_current_user('merchant')
    if not merchant_id:
        return unauthorized()

    # 检查订单关联
    order_count = db.query_one(
        "SELECT COUNT(*) as cnt FROM `Order_Item` WHERE dish_id = %s", (dish_id,))
    if order_count and order_count['cnt'] > 0:
        return error('该菜品有关联订单，无法删除')

    affected = db.execute("DELETE FROM `Dish` WHERE dish_id = %s AND merchant_id = %s",
                          (dish_id, merchant_id))
    if affected == 0:
        return error('菜品不存在或无权限删除')
    return success(None, '删除成功')


# ========== 库存管理 ==========

@merchant_bp.route('/stock/alerts', methods=['GET'])
def stock_alerts():
    """查询库存预警清单"""
    merchant_id = get_current_user('merchant')
    if not merchant_id:
        return unauthorized()

    alerts = db.query_all(
        "SELECT * FROM `Dish` WHERE merchant_id = %s AND warning_stock > 0 AND stock <= warning_stock ORDER BY stock",
        (merchant_id,))
    return success(alerts)


# ========== 订单管理 ==========

@merchant_bp.route('/orders', methods=['GET'])
def list_orders():
    """查询商家订单列表，支持状态/关键字/时间范围筛选。"""
    merchant_id = get_current_user('merchant')
    if not merchant_id:
        return unauthorized()

    status = request.args.get('status', type=int)
    keyword = request.args.get('keyword', '').strip()
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()
    sql = """SELECT o.*, u.real_name as user_name, u.phone as user_phone,
                    item_summary.dish_summary
             FROM `Order_Info` o
             JOIN `User` u ON o.user_id = u.user_id
             LEFT JOIN (
                SELECT oi.order_id,
                       GROUP_CONCAT(CONCAT(d.dish_name, 'x', oi.quantity)
                                    ORDER BY oi.order_item_id SEPARATOR '，') AS dish_summary
                FROM `Order_Item` oi
                JOIN `Dish` d ON d.dish_id = oi.dish_id
                GROUP BY oi.order_id
             ) item_summary ON item_summary.order_id = o.order_id
             WHERE o.merchant_id = %s"""
    params = [merchant_id]

    if status is not None:
        if status == 5:
            sql += " AND (o.order_status = %s OR (o.order_status = 4 AND o.finish_time IS NOT NULL))"
            params.append(status)
        elif status == 4:
            sql += " AND o.order_status = %s AND o.finish_time IS NULL"
            params.append(status)
        else:
            sql += " AND o.order_status = %s"
            params.append(status)
    if keyword:
        sql += " AND (CAST(o.order_id AS CHAR) LIKE %s OR u.real_name LIKE %s OR u.phone LIKE %s OR item_summary.dish_summary LIKE %s)"
        kw = f'%{keyword}%'
        params.extend([kw, kw, kw, kw])
    if start_date:
        sql += " AND o.create_time >= %s"
        params.append(start_date)
    if end_date:
        sql += " AND o.create_time <= %s"
        params.append(end_date + ' 23:59:59' if len(end_date) == 10 else end_date)

    sql += " ORDER BY o.create_time DESC"
    orders = db.query_all(sql, params)
    for order in orders:
        if order.get('order_status') == 4 and order.get('finish_time'):
            order['order_status'] = 5
    return success(orders)


@merchant_bp.route('/orders/<int:order_id>/accept', methods=['PUT'])
def accept_order(order_id):
    """商家接单接口，使用条件更新避免多端重复接单或订单状态被并发覆盖。"""
    merchant_id = get_current_user('merchant')
    if not merchant_id:
        return unauthorized()

    order = db.query_one(
        "SELECT * FROM `Order_Info` WHERE order_id = %s AND merchant_id = %s",
        (order_id, merchant_id))
    if not order:
        return error('订单不存在')
    if order.get('pay_status') != 1 or order.get('order_status') != 1:
        return error('只有已支付且待接单的订单可以接单')

    now = datetime.now()
    # WHERE 中再次限定支付状态和订单状态，防止读取后到更新前状态已被其他请求改变。
    affected = db.execute(
        """UPDATE `Order_Info`
           SET order_status = 2, accept_time = %s
           WHERE order_id = %s AND merchant_id = %s AND pay_status = 1 AND order_status = 1""",
        (now, order_id, merchant_id),
    )
    if affected == 0:
        return error('接单失败：订单状态已变化，请刷新后重试')
    return success(None, '已接单')

@merchant_bp.route('/orders/<int:order_id>/reject', methods=['PUT'])
def reject_order(order_id):
    """商家拒单接口，把待处理订单标记为异常，交由平台或用户后续处理。"""
    merchant_id = get_current_user('merchant')
    if not merchant_id:
        return unauthorized()

    order = db.query_one(
        "SELECT * FROM `Order_Info` WHERE order_id = %s AND merchant_id = %s",
        (order_id, merchant_id))
    if not order:
        return error('订单不存在')

    db.execute("UPDATE `Order_Info` SET order_status = 7 WHERE order_id = %s", (order_id,))
    return success(None, '已拒单')


@merchant_bp.route('/orders/<int:order_id>/ready', methods=['PUT'])
def meal_ready(order_id):
    """商家出餐接口；若骑手已接单则直接进入配送中，否则进入待配送状态。"""
    merchant_id = get_current_user('merchant')
    if not merchant_id:
        return unauthorized()

    order = db.query_one(
        "SELECT * FROM `Order_Info` WHERE order_id = %s AND merchant_id = %s",
        (order_id, merchant_id))
    if not order:
        return error('订单不存在')
    if order.get('order_status') not in (2, 4):
        return error('当前订单状态不能出餐')

    now = datetime.now()
    # 已有骑手时订单状态保持配送中；没有骑手时进入待配送，等待骑手接单。
    next_status = 4 if order.get('rider_id') else 3
    db.execute("UPDATE `Order_Info` SET order_status = %s, meal_ready_time = %s WHERE order_id = %s AND merchant_id = %s",
               (next_status, now, order_id, merchant_id))
    return success(None, '已出餐')


# ========== 评价管理 ==========

@merchant_bp.route('/reviews', methods=['GET'])
def list_reviews():
    """查询商家收到的评价列表，支持订单号/用户/内容/回复状态筛选。"""
    merchant_id = get_current_user('merchant')
    if not merchant_id:
        return unauthorized()

    keyword = request.args.get('keyword', '').strip()
    reply_status = request.args.get('reply_status', '').strip()  # 回复筛选：已回复/未回复
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()

    sql = """SELECT r.*, u.real_name as user_name FROM `Review` r
             JOIN `User` u ON r.user_id = u.user_id
             WHERE r.merchant_id = %s"""
    params = [merchant_id]
    if keyword:
        sql += " AND (CAST(r.order_id AS CHAR) LIKE %s OR u.real_name LIKE %s OR r.content LIKE %s)"
        kw = f'%{keyword}%'
        params.extend([kw, kw, kw])
    if reply_status == 'replied':
        sql += " AND r.merchant_reply IS NOT NULL AND r.merchant_reply <> ''"
    elif reply_status == 'unreplied':
        sql += " AND (r.merchant_reply IS NULL OR r.merchant_reply = '')"
    if start_date:
        sql += " AND r.review_time >= %s"
        params.append(start_date)
    if end_date:
        sql += " AND r.review_time <= %s"
        params.append(end_date + ' 23:59:59' if len(end_date) == 10 else end_date)
    sql += " ORDER BY r.review_time DESC"

    reviews = db.query_all(
        sql, params)
    return success(reviews)


@merchant_bp.route('/reviews/<int:review_id>/reply', methods=['PUT'])
def reply_review(review_id):
    """商家回复用户评价，只允许回复属于当前商家的评价记录。"""
    merchant_id = get_current_user('merchant')
    if not merchant_id:
        return unauthorized()

    data = request.get_json()
    if not data or not data.get('merchant_reply'):
        return error('回复内容不能为空')

    db.execute("UPDATE `Review` SET merchant_reply = %s WHERE review_id = %s AND merchant_id = %s",
               (data['merchant_reply'], review_id, merchant_id))
    return success(None, '回复成功')


# ========== 售后管理 ==========

@merchant_bp.route('/after-sales', methods=['GET'])
def list_after_sales():
    """查询当前商家的售后申请列表，仅返回已经进入售后流程的订单。"""
    merchant_id = get_current_user('merchant')
    if not merchant_id:
        return unauthorized()

    orders = db.query_all(
        """SELECT order_id, user_id, order_amount, after_sale_status, create_time
           FROM `Order_Info`
           WHERE merchant_id = %s AND after_sale_status > 0
           ORDER BY create_time DESC""", (merchant_id,))
    return success(orders)


@merchant_bp.route('/after-sales/<int:order_id>', methods=['PUT'])
def handle_after_sale(order_id):
    """商家处理售后申请；当前流程只允许把售后单标记为已处理。"""
    merchant_id = get_current_user('merchant')
    if not merchant_id:
        return unauthorized()

    data = request.get_json()
    status = data.get('after_sale_status')  # 2 表示已处理

    if status not in [2]:
        return error('无效的处理状态')

    db.execute("UPDATE `Order_Info` SET after_sale_status = %s WHERE order_id = %s AND merchant_id = %s",
               (status, order_id, merchant_id))
    return success(None, '处理成功')


# ========== 经营统计 ==========

@merchant_bp.route('/statistics/orders', methods=['GET'])
def order_statistics():
    """商家端经营统计——查询已完成订单的日营收趋势和汇总"""
    merchant_id = get_current_user('merchant')
    if not merchant_id:
        return unauthorized()

    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()

    conditions = ["merchant_id = %s", "order_status = 5"]
    params = [merchant_id]
    if start_date:
        conditions.append("create_time >= %s")
        params.append(start_date)
    if end_date:
        conditions.append("create_time <= %s")
        params.append(end_date + ' 23:59:59' if len(end_date) == 10 else end_date)
    where_sql = " AND ".join(conditions)

    try:
        daily = db.query_all(
            f"""SELECT DATE(create_time) AS date,
                       COUNT(*) AS order_count,
                       COALESCE(SUM(order_amount), 0) AS total_revenue,
                       COALESCE(SUM(delivery_fee), 0) AS total_delivery_fee
                FROM `Order_Info`
                WHERE {where_sql}
                GROUP BY DATE(create_time)
                ORDER BY date DESC""",
            params,
        )
        summary = db.query_one(
            f"""SELECT COUNT(*) AS total_orders,
                       COALESCE(SUM(order_amount), 0) AS total_revenue,
                       COALESCE(SUM(delivery_fee), 0) AS total_delivery_fee
                FROM `Order_Info`
                WHERE {where_sql}""",
            params,
        ) or {"total_orders": 0, "total_revenue": 0, "total_delivery_fee": 0}
        return success({'daily': daily, 'summary': summary})
    except Exception as e:
        return error(f'查询经营统计失败：{str(e)}')


@merchant_bp.route('/statistics/dishes', methods=['GET'])
def dish_statistics():
    """商家端经营统计——查询菜品销售排行榜（按营收/销量排序）"""
    merchant_id = get_current_user('merchant')
    if not merchant_id:
        return unauthorized()

    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()

    sales_conditions = ["o.merchant_id = %s", "o.order_status = 5"]
    sales_params = [merchant_id]
    if start_date:
        sales_conditions.append("o.create_time >= %s")
        sales_params.append(start_date)
    if end_date:
        sales_conditions.append("o.create_time <= %s")
        sales_params.append(end_date + ' 23:59:59' if len(end_date) == 10 else end_date)
    sales_where = " AND ".join(sales_conditions)

    try:
        dishes = db.query_all(
            f"""SELECT d.dish_id,
                       d.dish_name,
                       d.category_name,
                       d.price,
                       d.sales_count,
                       d.stock,
                       COALESCE(s.order_quantity, 0) AS order_quantity,
                       COALESCE(s.order_revenue, 0) AS order_revenue
                FROM `Dish` d
                LEFT JOIN (
                    SELECT oi.dish_id,
                           SUM(oi.quantity) AS order_quantity,
                           SUM(oi.subtotal) AS order_revenue
                    FROM `Order_Item` oi
                    JOIN `Order_Info` o ON oi.order_id = o.order_id
                    WHERE {sales_where}
                    GROUP BY oi.dish_id
                ) s ON s.dish_id = d.dish_id
                WHERE d.merchant_id = %s
                ORDER BY order_revenue DESC, order_quantity DESC, d.sales_count DESC, d.dish_id
                LIMIT 10""",
            sales_params + [merchant_id],
        )
        return success(dishes)
    except Exception as e:
        return error(f'查询菜品统计失败：{str(e)}')


# ==================================================
# 核心查询精简版 SQL 对应接口（商家端，只查询不修改）
# ==================================================

@merchant_bp.route('/core/orders', methods=['GET'])
def core_query_merchant_orders():
    """核心查询 6/7：商家查询本店订单列表，可按状态筛选。"""
    merchant_id = get_current_user('merchant')
    if not merchant_id:
        return unauthorized()
    status = request.args.get('order_status', type=int)
    if status is None:
        sql = """SELECT o.order_id, u.real_name AS customer_name, o.receiver_phone,
                        o.order_amount, o.pay_status, o.order_status, o.create_time,
                        o.accept_time, o.meal_ready_time, o.finish_time
                 FROM `Order_Info` o
                 JOIN `User` u ON o.user_id = u.user_id
                 WHERE o.merchant_id = %s
                 ORDER BY o.create_time DESC"""
        orders = db.query_all(sql, (merchant_id,))
        for order in orders:
            if order.get('order_status') == 4 and order.get('finish_time'):
                order['order_status'] = 5
        return success(orders)

    status_condition = "o.order_status = %s"
    params = [merchant_id, status]
    if status == 5:
        status_condition = "(o.order_status = %s OR (o.order_status = 4 AND o.finish_time IS NOT NULL))"
    elif status == 4:
        status_condition = "o.order_status = %s AND o.finish_time IS NULL"
    orders = db.query_all(
        """SELECT o.order_id, u.real_name AS customer_name, o.order_amount,
                  o.order_status, o.create_time, o.accept_time, o.finish_time
           FROM `Order_Info` o
           JOIN `User` u ON o.user_id = u.user_id
           WHERE o.merchant_id = %s
             AND """ + status_condition + """
           ORDER BY o.create_time DESC""",
        params,
    )
    for order in orders:
        if order.get('order_status') == 4 and order.get('finish_time'):
            order['order_status'] = 5
    return success(orders)


@merchant_bp.route('/core/orders/<int:order_id>/items', methods=['GET'])
def core_query_merchant_order_items(order_id):
    """核心查询 8：商家查询订单明细。"""
    merchant_id = get_current_user('merchant')
    if not merchant_id:
        return unauthorized()
    owned = db.query_one(
        "SELECT order_id FROM `Order_Info` WHERE order_id = %s AND merchant_id = %s",
        (order_id, merchant_id),
    )
    if not owned:
        return error('订单不存在或无权限查看', 404)
    items = db.query_all(
        """SELECT oi.order_item_id, d.dish_name, oi.specification,
                  oi.quantity, oi.unit_price, oi.subtotal
           FROM `Order_Item` oi
           JOIN `Dish` d ON oi.dish_id = d.dish_id
           WHERE oi.order_id = %s
           ORDER BY oi.order_item_id""",
        (order_id,),
    )
    return success(items)


@merchant_bp.route('/core/reviews', methods=['GET'])
def core_query_merchant_reviews():
    """核心查询 9：商家查询本店评价列表。"""
    merchant_id = get_current_user('merchant')
    if not merchant_id:
        return unauthorized()
    reviews = db.query_all(
        """SELECT rv.review_id, rv.order_id, u.real_name AS user_name,
                  rv.dish_score, rv.delivery_score, rv.content,
                  rv.merchant_reply, rv.review_time
           FROM `Review` rv
           JOIN `User` u ON rv.user_id = u.user_id
           WHERE rv.merchant_id = %s
           ORDER BY rv.review_time DESC""",
        (merchant_id,),
    )
    return success(reviews)


@merchant_bp.route('/core/dishes', methods=['GET'])
def core_query_merchant_dishes():
    """核心查询 10：商家查询本店菜品列表。"""
    merchant_id = get_current_user('merchant')
    if not merchant_id:
        return unauthorized()
    dishes = db.query_all(
        """SELECT dish_id, category_name, dish_name, price, specification,
                  stock, warning_stock, sale_status, sales_count
           FROM `Dish`
           WHERE merchant_id = %s
           ORDER BY FIELD(category_name, '盖饭', '甜品', '水果', '小吃', '饮品', '主食', '夜宵', '粥粉面'), dish_id""",
        (merchant_id,),
    )
    return success(dishes)
