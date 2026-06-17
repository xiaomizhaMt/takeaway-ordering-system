# ==================================================
# 外卖订餐管理系统 - 平台管理员端模块
# ==================================================
from datetime import datetime
from flask import Blueprint, request
from backend.db.db_helper import DBHelper, get_db
from backend.services.merchant_type_service import ensure_merchant_type_schema, merchant_type_label
from backend.services.order_safety_service import (
    apply_order_refund,
    ensure_order_edge_schema,
    force_refund_order,
)
from backend.services.wallet_service import ensure_wallet_schema
from backend.utils.response import success, error, unauthorized
from backend.utils.auth_helper import get_current_user

admin_bp = Blueprint('admin', __name__)
db = DBHelper()


@admin_bp.before_request
def ensure_admin_edge_schema():
    """管理员端接口访问前补齐订单、商家类型和钱包兼容字段。"""
    ensure_order_edge_schema()
    ensure_merchant_type_schema()
    ensure_wallet_schema()


# ========== 用户管理 ==========

@admin_bp.route('/users', methods=['GET'])
def list_users():
    """管理员查询用户列表，支持账号、姓名和手机号关键词筛选。"""
    if get_current_user('admin') is None:
        return unauthorized()

    keyword = request.args.get('keyword', '').strip()
    sql = "SELECT user_id, username, real_name, phone, password, account_status, register_time FROM `User`"
    params = []
    if keyword:
        sql += " WHERE username LIKE %s OR real_name LIKE %s OR phone LIKE %s"
        kw = f'%{keyword}%'
        params.extend([kw, kw, kw])
    sql += " ORDER BY register_time DESC"
    users = db.query_all(sql, params)
    return success(users)


@admin_bp.route('/users/<int:user_id>/status', methods=['PUT'])
def toggle_user_status(user_id):
    """启用/禁用用户账号"""
    if get_current_user('admin') is None:
        return unauthorized()

    data = request.get_json()
    status = data.get('account_status')

    if status not in [0, 1]:
        return error('无效的状态值')

    db.execute("UPDATE `User` SET account_status = %s WHERE user_id = %s",
               (status, user_id))
    msg = '已启用' if status == 1 else '已禁用'
    return success(None, f'用户账号{msg}')


@admin_bp.route('/users/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    """删除用户（需确认无关联订单）"""
    if get_current_user('admin') is None:
        return unauthorized()

    # 检查是否有订单
    order = db.query_one("SELECT COUNT(*) as cnt FROM `Order_Info` WHERE user_id = %s", (user_id,))
    if order and order['cnt'] > 0:
        return error('该用户存在关联订单，无法删除')
    db.execute("DELETE FROM `User` WHERE user_id = %s", (user_id,))
    return success(None, '用户已删除')


# ========== 商家管理 ==========

@admin_bp.route('/merchants', methods=['GET'])
def list_merchants():
    """管理员查询商家列表，并把商家类型编码转换为展示文案。"""
    if get_current_user('admin') is None:
        return unauthorized()

    keyword = request.args.get('keyword', '').strip()
    audit_status = request.args.get('audit_status', type=int)

    sql = "SELECT * FROM `Merchant`"
    conditions = []
    params = []

    if keyword:
        conditions.append("(shop_name LIKE %s OR account LIKE %s)")
        kw = f'%{keyword}%'
        params.extend([kw, kw])
    if audit_status is not None:
        conditions.append("audit_status = %s")
        params.append(audit_status)

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY merchant_id DESC"
    merchants = db.query_all(sql, params)
    for merchant in merchants:
        merchant['shop_type'] = merchant_type_label(merchant.get('merchant_type'))
    return success(merchants)


@admin_bp.route('/merchants/<int:merchant_id>', methods=['DELETE'])
def delete_merchant(merchant_id):
    """删除商家（需确认无关联订单）"""
    if get_current_user('admin') is None:
        return unauthorized()

    order = db.query_one("SELECT COUNT(*) as cnt FROM `Order_Info` WHERE merchant_id = %s", (merchant_id,))
    if order and order['cnt'] > 0:
        return error('该商家存在关联订单，无法删除')
    # 级联删除菜品
    db.execute("DELETE FROM `Dish` WHERE merchant_id = %s", (merchant_id,))
    db.execute("DELETE FROM `Merchant` WHERE merchant_id = %s", (merchant_id,))
    return success(None, '商家已删除')


@admin_bp.route('/merchants/<int:merchant_id>/audit', methods=['PUT'])
def audit_merchant(merchant_id):
    """管理员审核商家入驻申请。"""
    if get_current_user('admin') is None:
        return unauthorized()

    data = request.get_json()
    audit_status = data.get('audit_status')

    if audit_status not in [0, 1, 2]:
        return error('无效的审核状态')

    now = datetime.now()
    db.execute("UPDATE `Merchant` SET audit_status = %s, audit_time = %s WHERE merchant_id = %s",
               (audit_status, now, merchant_id))

    status_map = {0: '待审', 1: '通过', 2: '驳回'}
    return success(None, f'审核状态更新为：{status_map[audit_status]}')


# ========== 配送员管理 ==========

@admin_bp.route('/riders', methods=['GET'])
def list_riders():
    """管理员查询骑手列表，支持关键词和审核状态筛选。"""
    if get_current_user('admin') is None:
        return unauthorized()

    keyword = request.args.get('keyword', '').strip()
    audit_status = request.args.get('audit_status', type=int)

    sql = "SELECT * FROM `Rider`"
    conditions = []
    params = []

    if keyword:
        conditions.append("(rider_name LIKE %s OR account LIKE %s OR phone LIKE %s)")
        kw = f'%{keyword}%'
        params.extend([kw, kw, kw])
    if audit_status is not None:
        conditions.append("audit_status = %s")
        params.append(audit_status)

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY register_time DESC"
    riders = db.query_all(sql, params)
    return success(riders)


@admin_bp.route('/riders/<int:rider_id>', methods=['DELETE'])
def delete_rider(rider_id):
    """删除配送员（需确认无关联配送记录）"""
    if get_current_user('admin') is None:
        return unauthorized()

    delivery = db.query_one("SELECT COUNT(*) as cnt FROM `Delivery` WHERE rider_id = %s", (rider_id,))
    if delivery and delivery['cnt'] > 0:
        return error('该配送员存在关联配送记录，无法删除')
    db.execute("DELETE FROM `Rider` WHERE rider_id = %s", (rider_id,))
    return success(None, '配送员已删除')


@admin_bp.route('/riders/<int:rider_id>/audit', methods=['PUT'])
def audit_rider(rider_id):
    """审核配送员"""
    if get_current_user('admin') is None:
        return unauthorized()

    data = request.get_json()
    audit_status = data.get('audit_status')

    if audit_status not in [0, 1, 2]:
        return error('无效的审核状态')

    now = datetime.now()
    db.execute("UPDATE `Rider` SET audit_status = %s, audit_time = %s WHERE rider_id = %s",
               (audit_status, now, rider_id))

    status_map = {0: '待审', 1: '通过', 2: '驳回'}
    return success(None, f'审核状态更新为：{status_map[audit_status]}')


# ========== 订单监管 ==========

@admin_bp.route('/orders', methods=['GET'])
def list_orders():
    """管理员查询全平台订单列表，支持按时间、状态、用户、商家和菜品摘要筛选。"""
    if get_current_user('admin') is None:
        return unauthorized()

    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    order_status = request.args.get('order_status', type=int)
    keyword = request.args.get('keyword', '').strip()

    sql = """SELECT o.*, u.real_name as user_name, u.phone as user_phone,
                    m.shop_name, item_summary.dish_summary, item_summary.image_urls FROM `Order_Info` o
             JOIN `User` u ON o.user_id = u.user_id
             JOIN `Merchant` m ON o.merchant_id = m.merchant_id
             LEFT JOIN (
                SELECT oi.order_id,
                       GROUP_CONCAT(CONCAT(d.dish_name, 'x', oi.quantity) ORDER BY oi.order_item_id SEPARATOR '，') AS dish_summary,
                       GROUP_CONCAT(d.image_url ORDER BY oi.order_item_id SEPARATOR ',') AS image_urls
                FROM `Order_Item` oi
                JOIN `Dish` d ON oi.dish_id = d.dish_id
                GROUP BY oi.order_id
             ) item_summary ON item_summary.order_id = o.order_id
             WHERE 1=1"""
    params = []

    if start_date:
        sql += " AND o.create_time >= %s"
        params.append(start_date)
    if end_date:
        sql += " AND o.create_time <= %s"
        params.append(end_date + ' 23:59:59' if len(end_date) == 10 else end_date)
    if order_status is not None:
        sql += " AND o.order_status = %s"
        params.append(order_status)
    if keyword:
        sql += " AND (CAST(o.order_id AS CHAR) LIKE %s OR u.real_name LIKE %s OR m.shop_name LIKE %s OR item_summary.dish_summary LIKE %s)"
        kw = f'%{keyword}%'
        params.extend([kw, kw, kw, kw])

    sql += " ORDER BY o.create_time DESC"
    orders = db.query_all(sql, params)
    return success(orders)


@admin_bp.route('/orders/<int:order_id>', methods=['GET'])
def get_order_detail(order_id):
    """管理员查看单个订单详情，合并返回订单主表、菜品明细和配送信息。"""
    if get_current_user('admin') is None:
        return unauthorized()

    order = db.query_one(
        """SELECT o.*, u.real_name as user_name, u.phone as user_phone,
                  m.shop_name FROM `Order_Info` o
           JOIN `User` u ON o.user_id = u.user_id
           JOIN `Merchant` m ON o.merchant_id = m.merchant_id
           WHERE o.order_id = %s""", (order_id,))
    if not order:
        return error('订单不存在')

    # 订单明细用于核对用户下单商品、数量和单价。
    items = db.query_all(
        """SELECT oi.*, d.dish_name, d.image_url FROM `Order_Item` oi
           JOIN `Dish` d ON oi.dish_id = d.dish_id
           WHERE oi.order_id = %s""", (order_id,))
    order['items'] = items

    # 配送信息用于监管骑手接单、取餐、送达或异常上报进度。
    delivery = db.query_one(
        """SELECT d.*, r.rider_name, r.phone as rider_phone FROM `Delivery` d
           LEFT JOIN `Rider` r ON d.rider_id = r.rider_id
           WHERE d.order_id = %s""", (order_id,))
    order['delivery'] = delivery

    return success(order)


# ========== 投诉管理 ==========

@admin_bp.route('/complaints', methods=['GET'])
def list_complaints():
    """查询投诉评价和售后审核信息，供管理员按状态、关键词和时间范围筛选处理。"""
    if get_current_user('admin') is None:
        return unauthorized()

    complaint_status = request.args.get('complaint_status', type=int)
    keyword = request.args.get('keyword', '').strip()
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()

    sql = """SELECT r.*, u.real_name as user_name, u.phone as user_phone,
                    m.shop_name, o.order_amount, o.pay_status, o.order_status,
                    o.after_sale_status, o.after_sale_reason, o.after_sale_result,
                    o.refund_amount, o.refund_type, o.refund_reason, o.refund_time,
                    rider.rider_name
             FROM `Review` r
             JOIN `User` u ON r.user_id = u.user_id
             JOIN `Merchant` m ON r.merchant_id = m.merchant_id
             JOIN `Order_Info` o ON r.order_id = o.order_id
             LEFT JOIN `Rider` rider ON r.rider_id = rider.rider_id
             WHERE r.review_type = 2"""
    params = []
    if complaint_status is not None:
        sql += " AND r.complaint_status = %s"
        params.append(complaint_status)
    if keyword:
        sql += " AND (CAST(r.order_id AS CHAR) LIKE %s OR u.real_name LIKE %s OR m.shop_name LIKE %s OR r.content LIKE %s)"
        kw = f'%{keyword}%'
        params.extend([kw, kw, kw, kw])
    if start_date:
        sql += " AND r.review_time >= %s"
        params.append(start_date)
    if end_date:
        sql += " AND r.review_time <= %s"
        params.append(end_date + ' 23:59:59' if len(end_date) == 10 else end_date)
    sql += " ORDER BY r.review_time DESC"
    return success(db.query_all(sql, params))


@admin_bp.route('/complaints/<int:review_id>/handle', methods=['PUT'])
def handle_complaint(review_id):
    """审核用户投诉，可选择驳回、全额退款或 50% 部分退款。"""
    if get_current_user('admin') is None:
        return unauthorized()

    data = request.get_json() or {}
    action = (data.get('action') or '').strip()
    note = (data.get('note') or data.get('handle_note') or '').strip()
    if not note:
        return error('请填写审核备注')

    action_map = {
        'approve_full_refund': 1,
        'full_refund': 1,
        'refund': 1,
        'approve_half_refund': 2,
        'half_refund': 2,
        'partial_refund': 2,
        'reject': 0,
        'no_refund': 0,
    }
    if action not in action_map:
        return error('无效处理动作，请使用 full_refund / partial_refund / reject')

    conn = get_db()
    try:
        with conn.cursor() as cursor:
            conn.begin()
            cursor.execute(
                """SELECT r.*, o.pay_status, o.order_amount, o.after_sale_status
                   FROM `Review` r
                   JOIN `Order_Info` o ON r.order_id = o.order_id
                   WHERE r.review_id = %s AND r.review_type = 2
                   FOR UPDATE""",
                (review_id,),
            )
            complaint = cursor.fetchone()
            if not complaint:
                conn.rollback()
                return error('投诉不存在', 404)
            if complaint.get('complaint_status') in (2, 3):
                conn.rollback()
                return error('投诉已审核，不能重复处理')

            now = datetime.now()
            refund_type = action_map[action]
            refund_amount = None
            if refund_type in (1, 2):
                refund_amount = apply_order_refund(
                    cursor,
                    complaint['order_id'],
                    refund_type,
                    note,
                    after_sale_result=f'投诉审核通过：{note}',
                )
                complaint_status = 2
            else:
                cursor.execute(
                    """UPDATE `Order_Info`
                       SET after_sale_status = 2,
                           after_sale_result = %s,
                           after_sale_handle_time = %s
                       WHERE order_id = %s""",
                    (f'投诉审核驳回：{note}', now, complaint['order_id']),
                )
                complaint_status = 3

            cursor.execute(
                """UPDATE `Review`
                   SET complaint_status = %s,
                       complaint_refund_type = %s,
                       complaint_handle_note = %s,
                       complaint_handle_time = %s
                   WHERE review_id = %s""",
                (complaint_status, refund_type, note, now, review_id),
            )
        conn.commit()
        return success(
            {
                'review_id': review_id,
                'order_id': complaint['order_id'],
                'complaint_status': complaint_status,
                'refund_type': refund_type,
                'refund_amount': None if refund_amount is None else str(refund_amount),
            },
            '投诉审核完成',
        )
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return error(f'投诉处理失败：{str(e)}')


@admin_bp.route('/orders/<int:order_id>/force-refund', methods=['PUT'])
def admin_force_refund_order(order_id):
    """管理员从订单监管页发起强制退款，默认全额退款，也支持部分退款。"""
    if get_current_user('admin') is None:
        return unauthorized()
    data = request.get_json() or {}
    reason = (data.get('reason') or data.get('note') or '').strip()
    if not reason:
        return error('请填写强制退款原因')
    refund_type = 2 if (data.get('refund_type') in (2, '2', 'partial', 'partial_refund')) else 1
    try:
        amount = force_refund_order(order_id, reason, refund_type)
        return success({'order_id': order_id, 'refund_type': refund_type, 'refund_amount': str(amount)}, '强制退款已完成')
    except Exception as e:
        return error(f'强制退款失败：{str(e)}')


@admin_bp.route('/orders/supervision', methods=['GET'])
def order_supervision_summary():
    """订单流转监管摘要：统计异常、售后、待接单和待配送订单。"""
    if get_current_user('admin') is None:
        return unauthorized()
    stuck_minutes = request.args.get('stuck_minutes', 30, type=int)
    summary = db.query_one(
        """SELECT
                  SUM(CASE WHEN order_status = 7 THEN 1 ELSE 0 END) AS abnormal_count,
                  SUM(CASE WHEN after_sale_status = 1 THEN 1 ELSE 0 END) AS pending_after_sale_count,
                  SUM(CASE WHEN order_status = 1 THEN 1 ELSE 0 END) AS pending_accept_count,
                  SUM(CASE WHEN order_status IN (2, 3) AND rider_id IS NULL THEN 1 ELSE 0 END) AS pending_delivery_count,
                  SUM(CASE WHEN refund_type IN (1, 2) THEN 1 ELSE 0 END) AS refunded_count
           FROM `Order_Info`"""
    )
    stuck_orders = db.query_all(
        """SELECT o.order_id, o.order_status, o.after_sale_status, o.create_time,
                  o.accept_time, o.meal_ready_time, o.refund_amount, m.shop_name, u.real_name AS user_name
           FROM `Order_Info` o
           JOIN `Merchant` m ON o.merchant_id = m.merchant_id
           JOIN `User` u ON o.user_id = u.user_id
           WHERE (o.order_status = 1 AND o.pay_time < DATE_SUB(NOW(), INTERVAL %s MINUTE))
              OR (o.order_status IN (2, 3) AND o.rider_id IS NULL AND o.accept_time < DATE_SUB(NOW(), INTERVAL %s MINUTE))
              OR o.order_status = 7
              OR o.after_sale_status = 1
           ORDER BY o.create_time DESC""",
        (stuck_minutes, stuck_minutes),
    )
    return success({'summary': summary, 'stuck_orders': stuck_orders})


@admin_bp.route('/statistics/overview', methods=['GET'])
def get_statistics_overview():
    """平台核心数据统计概览，返回首页看板所需的用户、商家、骑手、订单和配送汇总。"""
    if get_current_user('admin') is None:
        return unauthorized()

    # 用户总量
    user_count = db.query_one("SELECT COUNT(*) as count FROM `User`")
    # 商家总量（审核通过的）
    merchant_count = db.query_one(
        "SELECT COUNT(*) as count FROM `Merchant` WHERE audit_status = 1")
    # 配送员总量（审核通过的）
    rider_count = db.query_one(
        "SELECT COUNT(*) as count FROM `Rider` WHERE audit_status = 1")
    # 订单总量和交易额（已完成的）
    order_stats = db.query_one(
        """SELECT COUNT(*) as total_orders,
                  COALESCE(SUM(order_amount), 0) as total_revenue
           FROM `Order_Info` WHERE order_status = 5""")
    # 配送总量（已送达的）
    delivery_count = db.query_one(
        "SELECT COUNT(*) as count FROM `Delivery` WHERE delivery_status = 2")

    # 各状态订单数量
    order_status_stats = db.query_all(
        """SELECT order_status, COUNT(*) as count
           FROM `Order_Info` GROUP BY order_status ORDER BY order_status""")

    return success({
        'user_count': user_count['count'] if user_count else 0,
        'merchant_count': merchant_count['count'] if merchant_count else 0,
        'rider_count': rider_count['count'] if rider_count else 0,
        'total_orders': order_stats['total_orders'] if order_stats else 0,
        'total_revenue': float(order_stats['total_revenue']) if order_stats else 0,
        'total_deliveries': delivery_count['count'] if delivery_count else 0,
        'order_status_stats': order_status_stats
    })


@admin_bp.route('/statistics/trends', methods=['GET'])
def get_statistics_trends():
    """按日统计近 N 天完成订单趋势，供管理端折线图和表格展示。"""
    if get_current_user('admin') is None:
        return unauthorized()

    days = request.args.get('days', 7, type=int)

    trends = db.query_all(
        """SELECT DATE(create_time) as date,
                  COUNT(*) as order_count,
                  COALESCE(SUM(order_amount), 0) as revenue
           FROM `Order_Info`
           WHERE order_status = 5 AND create_time >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
           GROUP BY DATE(create_time)
           ORDER BY date""", (days,))
    return success(trends)


@admin_bp.route('/statistics/merchant-ranking', methods=['GET'])
def get_merchant_ranking():
    """查询商家 Top10 排名，可按完成订单量或完成订单营收排序。"""
    if get_current_user('admin') is None:
        return unauthorized()

    sort_by = request.args.get('sort_by', 'orders')  # 排序字段：订单数/营收

    if sort_by == 'revenue':
        order_by = "total_revenue DESC"
    else:
        order_by = "order_count DESC"

    ranking = db.query_all(
        f"""SELECT m.merchant_id, m.shop_name, COUNT(*) as order_count,
                   COALESCE(SUM(o.order_amount), 0) as total_revenue
            FROM `Merchant` m
            JOIN `Order_Info` o ON m.merchant_id = o.merchant_id
            WHERE o.order_status = 5
            GROUP BY m.merchant_id
            ORDER BY {order_by}
            LIMIT 10""")
    return success(ranking)


# ==================================================
# 核心查询精简版 SQL 对应接口（管理员端，只查询不修改）
# ==================================================

@admin_bp.route('/core/orders', methods=['GET'])
def core_query_admin_orders():
    """核心查询 13：平台查询全部订单列表。"""
    if get_current_user('admin') is None:
        return unauthorized()
    orders = db.query_all(
        """SELECT o.order_id, u.username, m.shop_name, r.rider_name,
                  o.order_amount, o.pay_status, o.order_status, o.create_time
           FROM `Order_Info` o
           JOIN `User` u ON o.user_id = u.user_id
           JOIN `Merchant` m ON o.merchant_id = m.merchant_id
           LEFT JOIN `Rider` r ON o.rider_id = r.rider_id
           ORDER BY o.create_time DESC"""
    )
    return success(orders)


@admin_bp.route('/core/abnormal-orders', methods=['GET'])
def core_query_admin_abnormal_orders():
    """核心查询 14：平台查询异常订单。"""
    if get_current_user('admin') is None:
        return unauthorized()
    orders = db.query_all(
        """SELECT o.order_id, u.username, m.shop_name, r.rider_name,
                  o.order_status, dly.delivery_status, dly.exception_note,
                  o.create_time
           FROM `Order_Info` o
           JOIN `User` u ON o.user_id = u.user_id
           JOIN `Merchant` m ON o.merchant_id = m.merchant_id
           LEFT JOIN `Rider` r ON o.rider_id = r.rider_id
           LEFT JOIN `Delivery` dly ON o.order_id = dly.order_id
           WHERE o.order_status = 7
              OR dly.delivery_status = 3
           ORDER BY o.create_time DESC"""
    )
    return success(orders)


@admin_bp.route('/core/amount-check', methods=['GET'])
def core_query_admin_amount_check():
    """核心查询 15：订单金额一致性校验。"""
    if get_current_user('admin') is None:
        return unauthorized()
    rows = db.query_all(
        """SELECT o.order_id, SUM(oi.subtotal) AS item_total,
                  o.delivery_fee, o.order_amount,
                  CASE
                    WHEN SUM(oi.subtotal) + o.delivery_fee = o.order_amount THEN '正确'
                    ELSE '错误'
                  END AS amount_check
           FROM `Order_Info` o
           JOIN `Order_Item` oi ON o.order_id = oi.order_id
           GROUP BY o.order_id, o.delivery_fee, o.order_amount
           ORDER BY o.order_id"""
    )
    return success(rows)
