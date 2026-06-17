from datetime import datetime
from decimal import Decimal

from flask import Blueprint, request

from backend.db.db_helper import DBHelper, get_db
from backend.services.location_schema_service import ensure_location_schema, parse_latitude, parse_longitude
from backend.services.order_safety_service import ensure_order_edge_schema, force_refund_order
from backend.services.wallet_service import (
    backfill_wallet_income,
    change_wallet,
    ensure_wallet_schema,
    get_wallet,
    money as wallet_money,
    withdraw_wallet,
)
from backend.utils.auth_helper import get_current_user
from backend.utils.response import error, success, unauthorized


rider_bp = Blueprint("rider", __name__)
db = DBHelper()

# 骑手接单约束：最多同时配送 3 单，接单距离限制 50km，超过 100km 的订单不展示。
MAX_ACTIVE_TASKS = 3
MAX_ACCEPT_DISTANCE_KM = Decimal("50")
MAX_VISIBLE_DISTANCE_KM = Decimal("100")


@rider_bp.before_request
def ensure_rider_edge_schema():
    """骑手端接口访问前补齐订单、钱包、地图字段，兼容旧数据库。"""
    ensure_order_edge_schema()
    ensure_wallet_schema()
    ensure_location_schema()


@rider_bp.route("/wallet", methods=["GET"])
def get_rider_wallet():
    """查询骑手收益钱包，返回余额和资金流水。"""
    rider_id = get_current_user("rider")
    if not rider_id:
        return unauthorized()
    try:
        backfill_wallet_income()
        return success(get_wallet("rider", rider_id))
    except Exception as e:
        return error(f"查询钱包失败：{str(e)}")


@rider_bp.route("/wallet/withdraw", methods=["POST"])
def withdraw_rider_wallet():
    """骑手提现接口，扣减可提现余额并写入钱包流水。"""
    rider_id = get_current_user("rider")
    if not rider_id:
        return unauthorized()
    data = request.get_json() or {}
    try:
        result = withdraw_wallet(
            "rider",
            rider_id,
            data.get("amount"),
            data.get("pay_channel") or data.get("withdraw_channel") or "bank_card",
        )
        return success(result, "提现成功")
    except Exception as e:
        return error(f"提现失败：{str(e)}")


@rider_bp.route("/profile", methods=["GET"])
def get_profile():
    """查询当前登录配送员资料，供配送员端个人信息与页头展示使用。"""
    rider_id = get_current_user("rider")
    if not rider_id:
        return unauthorized()
    rider = db.query_one("SELECT * FROM `Rider` WHERE rider_id = %s", (rider_id,))
    if not rider:
        return error("配送员不存在", 404)
    return success(rider)


@rider_bp.route("/profile", methods=["PUT"])
def update_profile():
    """更新配送员基础资料；只开放姓名和联系电话，避免前端越权修改审核或钱包字段。"""
    rider_id = get_current_user("rider")
    if not rider_id:
        return unauthorized()
    data = request.get_json() or {}
    update_fields, params = [], []
    for field in ["rider_name", "phone"]:
        if field in data:
            update_fields.append(f"`{field}` = %s")
            params.append(data[field])
    if not update_fields:
        return error("没有需要修改的字段")
    params.append(rider_id)
    db.execute(f"UPDATE `Rider` SET {', '.join(update_fields)} WHERE rider_id = %s", params)
    return success(None, "修改成功")


@rider_bp.route("/status", methods=["PUT"])
def update_work_status():
    """切换配送员工作状态；只有在线状态的配送员才允许接单。"""
    rider_id = get_current_user("rider")
    if not rider_id:
        return unauthorized()
    data = request.get_json() or {}
    work_status = data.get("work_status")
    if work_status not in [0, 1, 2]:
        return error("无效的工作状态")
    db.execute("UPDATE `Rider` SET work_status = %s WHERE rider_id = %s", (work_status, rider_id))
    status_map = {0: "离线", 1: "在线", 2: "忙碌"}
    return success(None, f"状态已切换为{status_map[work_status]}")


def _dish_summary_subquery():
    """订单菜品摘要子查询，供任务列表和详情复用。"""
    return """
        LEFT JOIN (
          SELECT oi.order_id,
                 GROUP_CONCAT(CONCAT(di.dish_name, 'x', oi.quantity) ORDER BY oi.order_item_id SEPARATOR '，') AS dish_summary,
                 GROUP_CONCAT(di.image_url ORDER BY oi.order_item_id SEPARATOR ',') AS image_urls
          FROM `Order_Item` oi
          JOIN `Dish` di ON oi.dish_id = di.dish_id
          GROUP BY oi.order_id
        ) item_summary ON item_summary.order_id = o.order_id
    """


def _delivery_distance_sql():
    """计算商家到收货地址的配送距离，缺少坐标时返回 NULL。"""
    return """CASE
        WHEN COALESCE(o.merchant_latitude, m.shop_latitude) IS NULL
          OR COALESCE(o.merchant_longitude, m.shop_longitude) IS NULL
          OR o.receiver_latitude IS NULL
          OR o.receiver_longitude IS NULL
        THEN NULL
        ELSE ROUND(6371 * 2 * ASIN(SQRT(
          POW(SIN((RADIANS(o.receiver_latitude) - RADIANS(COALESCE(o.merchant_latitude, m.shop_latitude))) / 2), 2) +
          COS(RADIANS(COALESCE(o.merchant_latitude, m.shop_latitude))) * COS(RADIANS(o.receiver_latitude)) *
          POW(SIN((RADIANS(o.receiver_longitude) - RADIANS(COALESCE(o.merchant_longitude, m.shop_longitude))) / 2), 2)
        )), 2)
      END"""


@rider_bp.route("/tasks", methods=["GET"])
def list_tasks():
    """查询骑手已接任务，支持状态、关键词和日期筛选。"""
    rider_id = get_current_user("rider")
    if not rider_id:
        return unauthorized()
    status_filter = request.args.get("delivery_status", type=int)
    keyword = request.args.get("keyword", "").strip()
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()

    sql = f"""SELECT d.*, o.order_id, o.merchant_id, o.receiver_name, o.receiver_phone,
                    o.receiver_address, o.receiver_latitude, o.receiver_longitude,
                    o.order_amount, m.shop_name, m.shop_address as merchant_address,
                    COALESCE(o.merchant_latitude, m.shop_latitude) AS merchant_latitude,
                    COALESCE(o.merchant_longitude, m.shop_longitude) AS merchant_longitude,
                    item_summary.dish_summary, item_summary.image_urls
             FROM `Delivery` d
             JOIN `Order_Info` o ON d.order_id = o.order_id
             JOIN `Merchant` m ON o.merchant_id = m.merchant_id
             {_dish_summary_subquery()}
             WHERE d.rider_id = %s"""
    params = [rider_id]
    if status_filter is not None:
        sql += " AND d.delivery_status = %s"
        params.append(status_filter)
    if keyword:
        sql += " AND (CAST(o.order_id AS CHAR) LIKE %s OR m.shop_name LIKE %s OR o.receiver_name LIKE %s OR o.receiver_phone LIKE %s OR item_summary.dish_summary LIKE %s)"
        kw = f"%{keyword}%"
        params.extend([kw, kw, kw, kw, kw])
    if start_date:
        sql += " AND d.accept_time >= %s"
        params.append(start_date)
    if end_date:
        sql += " AND d.accept_time <= %s"
        params.append(end_date + " 23:59:59" if len(end_date) == 10 else end_date)
    sql += " ORDER BY d.accept_time DESC"
    return success(db.query_all(sql, params))


@rider_bp.route("/tasks/available", methods=["GET"])
def list_available_orders():
    """查询可接订单，支持按发布时间或骑手到商家的距离排序。"""
    sort = (request.args.get("sort") or "time").strip()
    rider_lat = parse_latitude(request.args.get("lat"))
    rider_lng = parse_longitude(request.args.get("lng"))
    use_distance = sort == "distance" and rider_lat is not None and rider_lng is not None

    distance_select = ""
    params = []
    if use_distance:
        distance_select = """,
                  CASE
                    WHEN COALESCE(o.merchant_latitude, m.shop_latitude) IS NULL
                      OR COALESCE(o.merchant_longitude, m.shop_longitude) IS NULL
                    THEN NULL
                    ELSE ROUND(6371 * 2 * ASIN(SQRT(
                      POW(SIN((RADIANS(COALESCE(o.merchant_latitude, m.shop_latitude)) - RADIANS(%s)) / 2), 2) +
                      COS(RADIANS(%s)) * COS(RADIANS(COALESCE(o.merchant_latitude, m.shop_latitude))) *
                      POW(SIN((RADIANS(COALESCE(o.merchant_longitude, m.shop_longitude)) - RADIANS(%s)) / 2), 2)
                    )), 2)
                  END AS distance_km"""
        params.extend([rider_lat, rider_lat, rider_lng])

    delivery_distance_sql = _delivery_distance_sql()
    sql = f"""SELECT o.*, m.shop_name, m.shop_address as merchant_address,
                    COALESCE(o.merchant_latitude, m.shop_latitude) AS merchant_latitude,
                    COALESCE(o.merchant_longitude, m.shop_longitude) AS merchant_longitude,
                    {delivery_distance_sql} AS delivery_distance_km
                    {distance_select},
                    item_summary.dish_summary, item_summary.image_urls
             FROM `Order_Info` o
             JOIN `Merchant` m ON o.merchant_id = m.merchant_id
             {_dish_summary_subquery()}
             WHERE o.order_status IN (2, 3)
               AND o.rider_id IS NULL
               AND o.order_id NOT IN (SELECT order_id FROM `Delivery`)
               AND ({delivery_distance_sql} IS NULL OR {delivery_distance_sql} <= %s)"""
    params.append(MAX_VISIBLE_DISTANCE_KM)
    sql += " ORDER BY distance_km IS NULL, distance_km ASC, o.create_time ASC" if use_distance else " ORDER BY o.create_time ASC"
    return success(db.query_all(sql, params))


@rider_bp.route("/tasks/accept", methods=["POST"])
def accept_task():
    """骑手接单接口，校验审核状态、在线状态、并发单数和配送距离。"""
    rider_id = get_current_user("rider")
    if not rider_id:
        return unauthorized()
    data = request.get_json() or {}
    order_id = data.get("order_id")
    if not order_id:
        return error("请提供订单编号")

    conn = get_db()
    try:
        with conn.cursor() as cursor:
            conn.begin()
            # 锁定骑手行，确保审核状态、在线状态和并发接单数在同一事务内判断。
            cursor.execute("SELECT rider_id, work_status, audit_status FROM `Rider` WHERE rider_id = %s FOR UPDATE", (rider_id,))
            rider = cursor.fetchone()
            if not rider:
                conn.rollback()
                return error("骑手不存在")
            if rider.get("audit_status") != 1:
                conn.rollback()
                return error("骑手账号尚未通过审核")
            if rider.get("work_status") != 1:
                conn.rollback()
                return error("骑手必须在线才能接单")
            cursor.execute("SELECT delivery_id FROM `Delivery` WHERE rider_id = %s AND delivery_status IN (0, 1) FOR UPDATE", (rider_id,))
            active_tasks = cursor.fetchall()
            if len(active_tasks) >= MAX_ACTIVE_TASKS:
                conn.rollback()
                return error(f"骑手最多只能同时接取{MAX_ACTIVE_TASKS}个未完成订单")
            # 锁定订单并重新计算商家到收货地址的距离，防止超过接单范围的订单被并发接走。
            cursor.execute(
                f"""SELECT o.*, {_delivery_distance_sql()} AS delivery_distance_km
                    FROM `Order_Info` o
                    JOIN `Merchant` m ON o.merchant_id = m.merchant_id
                    WHERE o.order_id = %s
                    FOR UPDATE""",
                (order_id,),
            )
            order = cursor.fetchone()
            if not order or order.get("order_status") not in (2, 3) or order.get("rider_id"):
                conn.rollback()
                return error("订单当前不可接取")
            delivery_distance = order.get("delivery_distance_km")
            if delivery_distance is not None and Decimal(str(delivery_distance)) > MAX_ACCEPT_DISTANCE_KM:
                conn.rollback()
                return error(f"订单配送距离超过{MAX_ACCEPT_DISTANCE_KM}km，骑手不可接取")
            # Delivery 表以订单为单位检查是否已有骑手，避免同一订单生成多条配送任务。
            cursor.execute("SELECT delivery_id FROM `Delivery` WHERE order_id = %s FOR UPDATE", (order_id,))
            if cursor.fetchone():
                conn.rollback()
                return error("订单已被接取")
            now = datetime.now()
            # 先创建配送任务，再回写订单骑手字段；任一步失败都会回滚。
            cursor.execute(
                """INSERT INTO `Delivery` (order_id, rider_id, delivery_status, accept_time)
                   VALUES (%s, %s, 0, %s)""",
                (order_id, rider_id, now),
            )
            cursor.execute(
                """UPDATE `Order_Info`
                   SET rider_id = %s, order_status = CASE WHEN order_status = 3 THEN 4 ELSE order_status END
                   WHERE order_id = %s AND rider_id IS NULL AND order_status IN (2, 3)""",
                (rider_id, order_id),
            )
            if cursor.rowcount != 1:
                conn.rollback()
                return error("接单失败：订单状态已变化，请刷新后重试")
            conn.commit()
        return success(None, "接单成功")
    except Exception as e:
        conn.rollback()
        return error(f"接单失败：{str(e)}")


@rider_bp.route("/tasks/<int:delivery_id>/pickup", methods=["PUT"])
def pickup_task(delivery_id):
    """骑手取餐接口，商家出餐后才允许把任务推进到配送中。"""
    rider_id = get_current_user("rider")
    if not rider_id:
        return unauthorized()
    delivery = db.query_one("SELECT * FROM `Delivery` WHERE delivery_id = %s AND rider_id = %s", (delivery_id, rider_id))
    if not delivery:
        return error("配送任务不存在")
    if delivery.get("delivery_status") != 0:
        return error("当前任务不能取餐")
    order = db.query_one("SELECT meal_ready_time FROM `Order_Info` WHERE order_id = %s", (delivery["order_id"],))
    if not order or not order.get("meal_ready_time"):
        return error("商家尚未出餐，不能取餐")
    now = datetime.now()
    db.execute("UPDATE `Delivery` SET delivery_status = 1, pickup_time = %s WHERE delivery_id = %s", (now, delivery_id))
    db.execute("UPDATE `Order_Info` SET order_status = 4 WHERE order_id = %s", (delivery["order_id"],))
    return success(None, "取餐成功")


@rider_bp.route("/tasks/<int:delivery_id>/deliver", methods=["PUT"])
def deliver_task(delivery_id):
    """骑手送达接口，完成订单并把配送费记入骑手收益钱包。"""
    rider_id = get_current_user("rider")
    if not rider_id:
        return unauthorized()
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            conn.begin()
            cursor.execute("SELECT * FROM `Delivery` WHERE delivery_id = %s AND rider_id = %s FOR UPDATE", (delivery_id, rider_id))
            delivery = cursor.fetchone()
            if not delivery:
                conn.rollback()
                return error("配送任务不存在")
            if delivery.get("delivery_status") not in (0, 1):
                conn.rollback()
                return error("当前任务不能确认送达")
            cursor.execute("SELECT * FROM `Order_Info` WHERE order_id = %s FOR UPDATE", (delivery["order_id"],))
            order = cursor.fetchone()
            now = datetime.now()
            delivery_fee = wallet_money(order.get("delivery_fee")) if order else Decimal("0.00")
            rider_income = delivery_fee if delivery_fee > Decimal("0.00") else Decimal("5.00")
            cursor.execute(
                """UPDATE `Delivery`
                   SET delivery_status = 2,
                       pickup_time = COALESCE(pickup_time, %s),
                       delivered_time = %s,
                       delivery_income = COALESCE(delivery_income, %s)
                   WHERE delivery_id = %s""",
                (now, now, rider_income, delivery_id),
            )
            if order and order.get("order_status") in (2, 3, 4):
                cursor.execute("UPDATE `Order_Info` SET order_status = 5, finish_time = COALESCE(finish_time, %s) WHERE order_id = %s", (now, order["order_id"]))
            if rider_income > Decimal("0.00"):
                # 配送收益直接取订单快照中的配送费；钱包服务负责余额更新和流水落库。
                change_wallet(
                    cursor,
                    "rider",
                    rider_id,
                    rider_income,
                    "rider_income",
                    order_id=delivery["order_id"],
                    delivery_id=delivery_id,
                    remark="配送完成入账",
                )
            conn.commit()
        return success(None, "已送达")
    except Exception as e:
        conn.rollback()
        return error(f"送达失败：{str(e)}")


@rider_bp.route("/tasks/<int:delivery_id>/exception", methods=["PUT"])
def report_exception(delivery_id):
    """骑手异常上报接口，平台会尝试对关联订单执行强制退款。"""
    rider_id = get_current_user("rider")
    if not rider_id:
        return unauthorized()
    data = request.get_json() or {}
    exception_note = (data.get("exception_note") or "").strip()
    if not exception_note:
        return error("请填写异常说明")
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            conn.begin()
            cursor.execute("SELECT * FROM `Delivery` WHERE delivery_id = %s AND rider_id = %s FOR UPDATE", (delivery_id, rider_id))
            delivery = cursor.fetchone()
            if not delivery:
                conn.rollback()
                return error("配送任务不存在")
            if delivery.get("delivery_status") == 2:
                conn.rollback()
                return error("已送达任务不能上报异常")
            cursor.execute("UPDATE `Delivery` SET delivery_status = 3, exception_note = %s WHERE delivery_id = %s", (exception_note, delivery_id))
            cursor.execute(
                """UPDATE `Order_Info`
                   SET order_status = 7, after_sale_status = 2, after_sale_result = %s, after_sale_handle_time = %s
                   WHERE order_id = %s""",
                (f"配送异常，平台强制退款：{exception_note}", datetime.now(), delivery["order_id"]),
            )
            conn.commit()
        try:
            refund_amount = force_refund_order(delivery["order_id"], f"配送异常：{exception_note}", 1)
            return success({"refund_amount": str(refund_amount)}, "异常已上报，平台已处理退款")
        except Exception as refund_error:
            return success({"refund_error": str(refund_error)}, "异常已上报，退款处理请交由管理员复核")
    except Exception as e:
        conn.rollback()
        return error(f"异常上报失败：{str(e)}")


@rider_bp.route("/income", methods=["GET"])
def income_records():
    """查询骑手配送收益明细，供收益钱包页面和统计曲线使用。"""
    rider_id = get_current_user("rider")
    if not rider_id:
        return unauthorized()
    keyword = request.args.get("keyword", "").strip()
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    sql = """SELECT d.delivery_id, d.order_id, d.delivery_status, d.delivered_time,
                    d.delivery_income, m.shop_name, o.order_amount
             FROM `Delivery` d
             JOIN `Order_Info` o ON d.order_id = o.order_id
             JOIN `Merchant` m ON o.merchant_id = m.merchant_id
             WHERE d.rider_id = %s AND d.delivery_status = 2"""
    params = [rider_id]
    if keyword:
        sql += " AND (CAST(d.order_id AS CHAR) LIKE %s OR m.shop_name LIKE %s)"
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    if start_date:
        sql += " AND d.delivered_time >= %s"
        params.append(start_date)
    if end_date:
        sql += " AND d.delivered_time <= %s"
        params.append(end_date + " 23:59:59" if len(end_date) == 10 else end_date)
    sql += " ORDER BY d.delivered_time DESC"
    rows = db.query_all(sql, params)
    summary = {
        "total_deliveries": len(rows),
        "total_income": sum(float(i.get("delivery_income") or 0) for i in rows)
    }
    return success({"details": rows, "summary": summary})


@rider_bp.route("/core/tasks", methods=["GET"])
def core_query_my_tasks():
    rider_id = get_current_user("rider")
    if not rider_id:
        return unauthorized()
    tasks = db.query_all(
        """SELECT dly.delivery_id, dly.order_id, m.shop_name,
                  o.receiver_name AS customer_name, o.receiver_phone,
                  o.receiver_address, dly.delivery_status, dly.accept_time,
                  dly.pickup_time, dly.delivered_time
           FROM `Delivery` dly
           JOIN `Order_Info` o ON dly.order_id = o.order_id
           JOIN `Merchant` m ON o.merchant_id = m.merchant_id
           WHERE dly.rider_id = %s
           ORDER BY dly.accept_time DESC""",
        (rider_id,),
    )
    return success(tasks)


@rider_bp.route("/core/tasks/<int:delivery_id>", methods=["GET"])
def core_query_task_detail(delivery_id):
    rider_id = get_current_user("rider")
    if not rider_id:
        return unauthorized()
    task = db.query_one(
        """SELECT dly.delivery_id, dly.order_id, r.rider_name, m.shop_name,
                  m.shop_address AS merchant_address, o.receiver_name AS customer_name,
                  o.receiver_phone, o.receiver_address, dly.delivery_status,
                  dly.accept_time, dly.pickup_time, dly.delivered_time,
                  dly.exception_note, dly.delivery_income
           FROM `Delivery` dly
           JOIN `Rider` r ON dly.rider_id = r.rider_id
           JOIN `Order_Info` o ON dly.order_id = o.order_id
           JOIN `Merchant` m ON o.merchant_id = m.merchant_id
           WHERE dly.delivery_id = %s AND dly.rider_id = %s""",
        (delivery_id, rider_id),
    )
    if not task:
        return error("配送任务不存在", 404)
    return success(task)
