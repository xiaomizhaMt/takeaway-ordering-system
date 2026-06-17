# ==================================================
# 外卖订餐管理系统 - 用户服务模块后端接口
# ==================================================
"""
本文件根据两份课程设计文档中的“用户服务模块”补全后端能力。

实现范围说明：
1. 数据库设计文档将系统收敛为 8 张表，没有单独的“地址表、购物车表、
   支付流水表、订单状态历史表、评价图片表、用户端删除备份表”。
2. 因此本文件在不新增数据库表的前提下实现用户端功能：
   - 收货地址：映射为 User 表的默认收货人/电话/地址字段，并提供兼容接口。
   - 购物车：使用 Flask Session 做临时缓存，不落库。
   - 支付信息：使用 Order_Info 表的 pay_method/pay_status/pay_time/order_amount 字段。
   - 状态跟踪：使用 Order_Info 与 Delivery 已有时间字段拼装状态时间线。
   - 评价图片、商家评分、真实软删除：数据库无字段，保留接口注释说明。
"""

import math
from datetime import datetime, time
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Tuple

from flask import Blueprint, request, session

from backend.db.db_helper import DBHelper, get_db
from backend.services.merchant_type_service import (
    ensure_merchant_type_schema,
    merchant_type_label,
    merchant_type_icon,
    normalize_merchant_type,
)
from backend.services.location_schema_service import (
    ensure_location_schema,
    parse_latitude,
    parse_location_name,
    parse_longitude,
)
from backend.services.order_safety_service import ensure_order_edge_schema, apply_order_refund
from backend.services.wallet_service import (
    change_wallet,
    ensure_wallet_schema,
    get_wallet,
    money as wallet_money,
    recharge_user_wallet,
)
from backend.utils.auth_helper import get_current_user
from backend.utils.response import error, success, unauthorized


user_bp = Blueprint("user", __name__)
db = DBHelper()


# ==================================================
# 通用工具函数
# ==================================================

ORDER_STATUS_LABELS = {
    0: "待支付",
    1: "待接单",
    2: "备餐中",
    3: "已出餐",
    4: "配送中",
    5: "已完成",
    6: "已取消",
    7: "异常",
}

PAY_STATUS_LABELS = {
    0: "未支付",
    1: "支付成功",
    2: "支付失败",
    3: "已退款",
}

PAY_METHOD_LABELS = {
    "wechat": "微信支付",
    "alipay": "支付宝",
    "bank_card": "银行卡",
    "cash": "货到付款",
    "wallet": "我的钱包",
}

_payment_schema_checked = False


def _ensure_payment_schema():
    """
    兼容已初始化过的旧数据库。

    需求文档中明确用户支付时需要选择“支付方式”，且支付信息并入订单表。
    如果当前数据库是旧版本，Order_Info 可能还没有 pay_method 字段；这里在
    第一次用户端请求时自动补列，避免必须手工重建数据库。
    """
    global _payment_schema_checked
    if _payment_schema_checked:
        return

    conn = get_db()
    with conn.cursor() as cursor:
        cursor.execute("SHOW COLUMNS FROM `Order_Info` LIKE 'pay_method'")
        exists = cursor.fetchone()
        if not exists:
            cursor.execute(
                """ALTER TABLE `Order_Info`
                   ADD COLUMN `pay_method` VARCHAR(20) NULL
                   COMMENT '支付方式：wechat微信，alipay支付宝，bank_card银行卡，cash货到付款，wallet我的钱包'
                   AFTER `delivery_fee`"""
            )
            conn.commit()
        # 旧测试数据中可能已有“支付成功”的订单但没有支付方式；
        # 统一补为微信支付，保证订单详情中的支付信息完整可展示。
        cursor.execute(
            """UPDATE `Order_Info`
               SET pay_method = 'wechat'
               WHERE pay_status = 1 AND pay_method IS NULL"""
        )

        # 兼容旧数据库：补充用户支付密码字段。已有用户默认使用登录密码作为支付密码，
        # 后续新用户注册时会单独写入 pay_password。
        cursor.execute("SHOW COLUMNS FROM `User` LIKE 'pay_password'")
        exists = cursor.fetchone()
        if not exists:
            cursor.execute(
                """ALTER TABLE `User`
                   ADD COLUMN `pay_password` VARCHAR(100) NULL
                   COMMENT '支付密码'
                   AFTER `password`"""
            )
        cursor.execute(
            """UPDATE `User`
               SET pay_password = password
               WHERE pay_password IS NULL OR pay_password = ''"""
        )

        # 兼容旧数据库：补充餐具份数字段。下单时至少选择 1 份餐具。
        cursor.execute("SHOW COLUMNS FROM `Order_Info` LIKE 'tableware_count'")
        exists = cursor.fetchone()
        if not exists:
            cursor.execute(
                """ALTER TABLE `Order_Info`
                   ADD COLUMN `tableware_count` INT NOT NULL DEFAULT 1
                   COMMENT '餐具份数'
                   AFTER `delivery_fee`"""
            )
        conn.commit()
    _payment_schema_checked = True


@user_bp.before_request
def ensure_user_module_schema():
    """用户端接口访问前补齐支付、地图、订单边界和钱包兼容字段。"""
    _ensure_payment_schema()
    ensure_location_schema()
    ensure_order_edge_schema()
    ensure_wallet_schema()


DELIVERY_STATUS_LABELS = {
    0: "待取餐",
    1: "配送中",
    2: "已送达",
    3: "异常",
}


def _json_data():
    """安全读取 JSON 请求体；没有请求体时返回空字典。"""
    return request.get_json(silent=True) or {}


def _money(value) -> Decimal:
    """把前端或数据库金额统一转换为两位小数 Decimal。"""
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _distance_km(lat1, lng1, lat2, lng2) -> Optional[Decimal]:
    """使用 Haversine 公式计算两点直线距离，缺少坐标时返回 None。"""
    try:
        lat1 = float(lat1)
        lng1 = float(lng1)
        lat2 = float(lat2)
        lng2 = float(lng2)
    except (TypeError, ValueError):
        return None

    radius = 6371.0088
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return Decimal(str(radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))))


def _delivery_fee_by_distance(distance_km: Optional[Decimal]) -> Decimal:
    """按距离计算配送费：3km 内 3 元，超过部分每公里 0.5 元。"""
    if distance_km is None:
        return Decimal("3.00")
    if distance_km <= Decimal("3"):
        return Decimal("3.00")
    fee = Decimal("3.00") + (distance_km - Decimal("3")) * Decimal("0.50")
    return fee.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _is_delivery_distance_allowed(distance_km: Optional[Decimal]) -> bool:
    """有明确坐标的订单必须在 100km 内才允许下单。"""
    return distance_km is None or distance_km <= Decimal("100")


def _cart_key(user_id: int) -> str:
    """按用户隔离 Session 购物车，避免同一浏览器多账号串用。"""
    return f"cart_user_{user_id}"


def _get_cart(user_id: int) -> dict:
    """读取当前用户旧版 Session 购物车；结构为 {'merchant_id': int, 'items': {dish_id: item}}。"""
    return session.get(_cart_key(user_id), {"merchant_id": None, "items": {}})


def _save_cart(user_id: int, cart: dict):
    """保存购物车到 Session，并显式标记 session 已修改。"""
    session[_cart_key(user_id)] = cart
    session.modified = True


@user_bp.route("/wallet", methods=["GET"])
def get_user_wallet():
    """查询用户钱包余额和资金流水。"""
    user_id = get_current_user("user")
    if not user_id:
        return unauthorized()
    try:
        return success(get_wallet("user", user_id))
    except Exception as e:
        return error(f"查询钱包失败：{str(e)}")


@user_bp.route("/wallet/recharge", methods=["POST"])
def recharge_wallet():
    """用户使用第三方支付方式模拟充值到我的钱包。"""
    user_id = get_current_user("user")
    if not user_id:
        return unauthorized()
    data = _json_data()
    amount = _money(data.get("amount"))
    pay_channel = (data.get("pay_channel") or data.get("pay_method") or "wechat").strip()
    if amount <= Decimal("0.00"):
        return error("充值金额必须大于0")
    try:
        result = recharge_user_wallet(user_id, amount, pay_channel)
        return success(result, "充值成功")
    except Exception as e:
        return error(f"充值失败：{str(e)}")


def _is_merchant_open_now(business_hours: Optional[str]) -> bool:
    """
    判断商家当前是否在营业时间内。

    文档要求“非营业时段禁止用户提交该商家订单”。数据库中 business_hours
    是简单字符串，如 09:00-21:00；为空时只按 business_status 判断。
    """
    if not business_hours or "-" not in business_hours:
        return True
    try:
        start_s, end_s = [x.strip() for x in business_hours.split("-", 1)]
        start = time.fromisoformat(start_s)
        end = time.fromisoformat(end_s)
        now = datetime.now().time()
        if start <= end:
            return start <= now <= end
        # 兼容跨天营业时间，如 20:00-02:00
        return now >= start or now <= end
    except Exception:
        # 营业时间格式异常时不阻断业务，只使用营业状态字段控制。
        return True


def _format_actor_name(actor_type: str, order: Dict, delivery: Optional[Dict]) -> str:
    if actor_type == "merchant":
        return order.get("shop_name") or "商家"
    if actor_type == "rider":
        if delivery and delivery.get("rider_name"):
            return delivery.get("rider_name")
        return "配送员"
    if actor_type == "user":
        return "用户"
    return "系统"


def _build_order_flow(order: Dict, delivery: Optional[Dict]) -> List[Dict]:
    """
    根据 Order_Info 与 Delivery 的真实字段生成完整订单流转节点。

    不新增“虚拟状态表”，所有已完成节点均来自现有后端接口真实写入的时间字段：
    - 用户下单：Order_Info.create_time
    - 用户支付：Order_Info.pay_time
    - 商家接单：Order_Info.accept_time
    - 商家出餐：Order_Info.meal_ready_time
    - 配送员接单：Delivery.accept_time
    - 配送员取餐：Delivery.pickup_time
    - 配送员送达：Delivery.delivered_time
    - 订单完成：Order_Info.finish_time
    """
    delivery = delivery or {}
    order_status = order.get("order_status")
    pay_status = order.get("pay_status")
    delivery_status = delivery.get("delivery_status")

    raw_steps = [
        {
            "code": "submitted",
            "status": 0,
            "label": "用户提交订单",
            "description": "订单已生成，等待用户支付。",
            "actor": "user",
            "occurred_at": order.get("create_time"),
        },
        {
            "code": "paid",
            "status": 1,
            "label": "用户支付成功",
            "description": "支付成功后订单进入商家待接单队列。",
            "actor": "user",
            "occurred_at": order.get("pay_time") if pay_status in (1, 3) else None,
        },
        {
            "code": "merchant_accepted",
            "status": 2,
            "label": "商家接单",
            "description": "商家确认订单并开始备餐。",
            "actor": "merchant",
            "occurred_at": order.get("accept_time"),
        },
        {
            "code": "meal_ready",
            "status": 3,
            "label": "商家出餐",
            "description": "商家已完成出餐，等待或交给配送员取餐。",
            "actor": "merchant",
            "occurred_at": order.get("meal_ready_time"),
        },
        {
            "code": "rider_accepted",
            "status": 4,
            "label": "配送员接单",
            "description": "配送员已接下配送任务，准备到店取餐。",
            "actor": "rider",
            "occurred_at": delivery.get("accept_time"),
        },
        {
            "code": "picked_up",
            "status": 4,
            "label": "配送员取餐",
            "description": "配送员已从商家取餐，正在配送途中。",
            "actor": "rider",
            "occurred_at": delivery.get("pickup_time"),
        },
        {
            "code": "delivered",
            "status": 5,
            "label": "已送达",
            "description": "配送员确认订单已送达。",
            "actor": "rider",
            "occurred_at": delivery.get("delivered_time"),
        },
        {
            "code": "finished",
            "status": 5,
            "label": "订单完成",
            "description": "订单已完成，可进行评价。",
            "actor": "system",
            "occurred_at": order.get("finish_time"),
        },
    ]

    if order_status == 6:
        raw_steps.append({
            "code": "cancelled",
            "status": 6,
            "label": "订单已取消",
            "description": "订单已取消，若已支付则同步标记为退款。",
            "actor": "system",
            "occurred_at": order.get("finish_time") or order.get("pay_time") or order.get("create_time"),
            "terminal": True,
        })
    if order_status == 7 or delivery_status == 3:
        raw_steps.append({
            "code": "exception",
            "status": 7,
            "label": "订单异常",
            "description": delivery.get("exception_note") or "订单或配送发生异常。",
            "actor": "rider" if delivery_status == 3 else "merchant",
            "occurred_at": None,
            "terminal": True,
        })

    for step in raw_steps:
        step["actor_name"] = _format_actor_name(step.get("actor"), order, delivery)
        step["completed"] = bool(step.get("occurred_at"))
        step["current"] = False

    terminal = next((s for s in raw_steps if s.get("terminal")), None)
    normal_steps = [s for s in raw_steps if not s.get("terminal")]
    completed_steps = sorted(
        [s for s in normal_steps if s.get("completed")],
        key=lambda s: s.get("occurred_at"),
    )
    pending_steps = [s for s in normal_steps if not s.get("completed")]
    ordered_steps = completed_steps + pending_steps

    if terminal:
        terminal["completed"] = True
        terminal["current"] = True
        ordered_steps.append(terminal)
    else:
        for step in ordered_steps:
            if not step["completed"]:
                step["current"] = True
                break
        else:
            if ordered_steps:
                ordered_steps[-1]["current"] = True

    return ordered_steps


def _build_order_timeline(order: Dict, delivery: Optional[Dict]) -> List[Dict]:
    """返回已发生的订单流转事件，供详情页和状态接口展示。"""
    return [
        {
            "status": step["status"],
            "label": step["label"],
            "occurred_at": step["occurred_at"],
            "actor": step["actor"],
            "actor_name": step["actor_name"],
            "description": step.get("description"),
        }
        for step in _build_order_flow(order, delivery)
        if step.get("completed") and step.get("occurred_at")
    ]


def _get_owned_order(order_id: int, user_id: int) -> Optional[Dict]:
    """查询并校验订单是否属于当前登录用户。"""
    order = db.query_one(
        """SELECT o.*, m.shop_name, m.contact_phone, m.shop_address
           FROM `Order_Info` o
           JOIN `Merchant` m ON o.merchant_id = m.merchant_id
           WHERE o.order_id = %s AND o.user_id = %s""",
        (order_id, user_id),
    )
    if order and order.get("order_status") == 4 and order.get("finish_time"):
        # 兼容旧数据：之前配送员确认送达会写 finish_time，但 order_status 仍停在 4。
        order["order_status"] = 5
    return order


def _create_order_in_transaction(
    *,
    user_id: int,
    merchant_id: int,
    items: List[Dict],
    receiver_name: str,
    receiver_phone: str,
    receiver_address: str,
    delivery_fee,
    tableware_count: int,
    receiver_latitude=None,
    receiver_longitude=None,
) -> Tuple[int, Decimal]:
    """
    在一个数据库事务中创建订单。

    旧实现逐条提交，若中途失败可能出现“订单已生成但库存/明细不一致”。
    这里直接使用同一个连接完成：校验商家 -> 锁定菜品 -> 写订单 -> 写明细
    -> 扣库存/增销量 -> commit；任一步失败都会 rollback。
    """
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            # 1. 校验商家是否审核通过且营业。
            cursor.execute(
                """SELECT merchant_id, business_status, audit_status, business_hours,
                          shop_latitude, shop_longitude
                   FROM `Merchant`
                   WHERE merchant_id = %s""",
                (merchant_id,),
            )
            merchant = cursor.fetchone()
            if not merchant:
                raise ValueError("商家不存在")
            if merchant["business_status"] != 1 or merchant["audit_status"] != 1:
                raise ValueError("商家暂未营业或未通过审核")
            if not _is_merchant_open_now(merchant.get("business_hours")):
                raise ValueError("当前不在商家营业时间内，暂不能下单")

            # 2. 校验并锁定菜品库存，避免并发下单导致超卖。
            # 锁库存前先合并同一菜品的多行数量，避免一次请求拆成多行造成超卖。
            merged_items = {}
            for item in items:
                dish_id = int(item.get("dish_id") or 0)
                quantity = int(item.get("quantity") or 1)
                if dish_id <= 0 or quantity <= 0:
                    raise ValueError("菜品编号或数量不合法")
                if dish_id not in merged_items:
                    merged_items[dish_id] = dict(item)
                    merged_items[dish_id]["quantity"] = quantity
                else:
                    merged_items[dish_id]["quantity"] = int(merged_items[dish_id].get("quantity") or 0) + quantity

            order_items = []
            total_amount = Decimal("0.00")
            for item in [merged_items[key] for key in sorted(merged_items)]:
                dish_id = int(item.get("dish_id") or 0)
                quantity = int(item.get("quantity") or 1)

                cursor.execute(
                    """SELECT dish_id, dish_name, price, specification, stock
                       FROM `Dish`
                       WHERE dish_id = %s
                         AND merchant_id = %s
                         AND sale_status = 1
                       FOR UPDATE""",
                    (dish_id, merchant_id),
                )
                dish = cursor.fetchone()
                if not dish:
                    raise ValueError(f"菜品ID {dish_id} 不存在或已下架")
                if int(dish["stock"]) < quantity:
                    raise ValueError(f"菜品 {dish['dish_name']} 库存不足")

                unit_price = _money(dish["price"])
                subtotal = _money(unit_price * quantity)
                total_amount += subtotal
                order_items.append({
                    "dish_id": dish_id,
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "specification": item.get("specification") or dish.get("specification") or "",
                    "subtotal": subtotal,
                })

            receiver_latitude = parse_latitude(receiver_latitude)
            receiver_longitude = parse_longitude(receiver_longitude)
            delivery_distance_km = _distance_km(
                merchant.get("shop_latitude"),
                merchant.get("shop_longitude"),
                receiver_latitude,
                receiver_longitude,
            )
            if not _is_delivery_distance_allowed(delivery_distance_km):
                raise ValueError("商家距离收货地址超过100km，暂不支持下单")
            delivery_fee = _delivery_fee_by_distance(delivery_distance_km)
            tableware_count = int(tableware_count or 1)
            if tableware_count < 1:
                raise ValueError("餐具份数至少选择 1 份")
            order_amount = _money(total_amount + delivery_fee)
            now = datetime.now()

            # 3. 写订单主表。下单后默认未支付，订单状态为“待支付”。
            cursor.execute(
                """INSERT INTO `Order_Info`
                   (user_id, merchant_id, receiver_name, receiver_phone, receiver_address,
                    receiver_latitude, receiver_longitude, merchant_latitude, merchant_longitude,
                    order_amount, delivery_fee, tableware_count, pay_status, order_status, after_sale_status,
                     create_time)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, 0, 0, %s)""",
                (
                    user_id,
                    merchant_id,
                    receiver_name,
                    receiver_phone,
                    receiver_address,
                    receiver_latitude,
                    receiver_longitude,
                    merchant.get("shop_latitude"),
                    merchant.get("shop_longitude"),
                    order_amount,
                    delivery_fee,
                    tableware_count,
                    now,
                ),
            )
            order_id = cursor.lastrowid

            # 4. 写订单明细，并同步扣库存、增加销量。
            for oi in order_items:
                cursor.execute(
                    """INSERT INTO `Order_Item`
                       (order_id, dish_id, quantity, unit_price, specification, subtotal)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (
                        order_id,
                        oi["dish_id"],
                        oi["quantity"],
                        oi["unit_price"],
                        oi["specification"],
                        oi["subtotal"],
                    ),
                )
                cursor.execute(
                    """UPDATE `Dish`
                       SET stock = stock - %s,
                           sales_count = sales_count + %s
                       WHERE dish_id = %s""",
                    (oi["quantity"], oi["quantity"], oi["dish_id"]),
                )

        conn.commit()
        return order_id, order_amount
    except Exception:
        conn.rollback()
        raise


# ==================================================
# 个人信息与收货地址
# ==================================================

@user_bp.route("/profile", methods=["GET"])
def get_profile():
    """查询当前用户基础信息和默认收货信息。"""
    user_id = get_current_user("user")
    if not user_id:
        return unauthorized()

    user = db.query_one("SELECT * FROM `User` WHERE user_id = %s", (user_id,))
    if not user:
        return error("用户不存在", 404)
    return success(user)


@user_bp.route("/profile", methods=["PUT"])
def update_profile():
    """修改当前用户姓名、手机号和默认收货信息。"""
    user_id = get_current_user("user")
    if not user_id:
        return unauthorized()

    data = _json_data()
    update_fields, params = [], []
    for field in [
        "real_name",
        "phone",
        "default_receiver",
        "default_phone",
        "default_address",
        "default_latitude",
        "default_longitude",
        "default_location_name",
    ]:
        if field in data:
            if field == "default_latitude":
                data[field] = parse_latitude(data[field])
            elif field == "default_longitude":
                data[field] = parse_longitude(data[field])
            elif field == "default_location_name":
                data[field] = parse_location_name(data[field])
            update_fields.append(f"`{field}` = %s")
            params.append(data[field])

    if not update_fields:
        return error("没有需要修改的字段")

    # 手机号唯一性校验，避免触发数据库唯一索引异常后返回不友好。
    if "phone" in data:
        exists = db.query_one(
            "SELECT user_id FROM `User` WHERE phone = %s AND user_id <> %s",
            (data["phone"], user_id),
        )
        if exists:
            return error("该手机号已被其他用户使用")

    params.append(user_id)
    db.execute(f"UPDATE `User` SET {', '.join(update_fields)} WHERE user_id = %s", params)
    return success(None, "个人信息修改成功")


@user_bp.route("/addresses", methods=["GET"])
def list_addresses():
    """
    查询用户收货地址。

    需求文档要求“收货地址管理”，但收敛版数据库没有 Address 表；
    因此将 User.default_receiver/default_phone/default_address 作为一个默认地址返回。
    """
    user_id = get_current_user("user")
    if not user_id:
        return unauthorized()
    user = db.query_one(
        """SELECT default_receiver, default_phone, default_address,
                  default_latitude, default_longitude, default_location_name
           FROM `User` WHERE user_id = %s""",
        (user_id,),
    )
    if not user:
        return error("用户不存在", 404)
    if not any([user.get("default_receiver"), user.get("default_phone"), user.get("default_address")]):
        return success([])
    return success([{
        "address_id": 1,
        "receiver_name": user.get("default_receiver"),
        "receiver_phone": user.get("default_phone"),
        "detail_address": user.get("default_address"),
        "latitude": user.get("default_latitude"),
        "longitude": user.get("default_longitude"),
        "location_name": user.get("default_location_name"),
        "is_default": 1,
        "address_label": "默认地址",
    }])


@user_bp.route("/addresses", methods=["POST"])
def create_address():
    """新增/覆盖默认收货地址；受 8 表设计限制，当前只保存一条默认地址。"""
    user_id = get_current_user("user")
    if not user_id:
        return unauthorized()
    data = _json_data()
    receiver = data.get("receiver_name") or data.get("receiver") or ""
    phone = data.get("receiver_phone") or data.get("phone") or ""
    address = data.get("detail_address") or data.get("address") or ""
    latitude = parse_latitude(data.get("latitude") or data.get("default_latitude"))
    longitude = parse_longitude(data.get("longitude") or data.get("default_longitude"))
    location_name = parse_location_name(data.get("location_name") or data.get("default_location_name"))
    if not all([receiver, phone, address]):
        return error("收货人、联系电话、详细地址不能为空")
    db.execute(
        """UPDATE `User`
           SET default_receiver = %s, default_phone = %s, default_address = %s,
               default_latitude = %s, default_longitude = %s, default_location_name = %s
           WHERE user_id = %s""",
        (receiver, phone, address, latitude, longitude, location_name, user_id),
    )
    return success({"address_id": 1}, "默认收货地址已保存")


@user_bp.route("/addresses/<int:address_id>", methods=["PUT"])
def update_address(address_id):
    """修改默认收货地址；address_id 仅兼容前端地址接口，当前固定为 1。"""
    if address_id != 1:
        return error("当前数据库设计仅支持默认地址")
    return create_address()


@user_bp.route("/addresses/<int:address_id>", methods=["DELETE"])
def delete_address(address_id):
    """删除默认收货地址；未完成订单中的地址快照不会受影响。"""
    user_id = get_current_user("user")
    if not user_id:
        return unauthorized()
    if address_id != 1:
        return error("地址不存在", 404)
    db.execute(
        """UPDATE `User`
           SET default_receiver = NULL, default_phone = NULL, default_address = NULL,
               default_latitude = NULL, default_longitude = NULL, default_location_name = NULL
           WHERE user_id = %s""",
        (user_id,),
    )
    return success(None, "默认收货地址已删除")


# ==================================================
# 商家与菜品浏览
# ==================================================

@user_bp.route("/merchants", methods=["GET"])
def list_merchants():
    """浏览营业商家，支持按店铺名称/简介/地址关键字搜索、按商家类型筛选，并附带评分摘要。"""
    ensure_merchant_type_schema()
    keyword = request.args.get("keyword", "").strip()
    merchant_type = normalize_merchant_type(request.args.get("type", "").strip(), default="")
    lat = parse_latitude(request.args.get("lat") or request.args.get("latitude"))
    lng = parse_longitude(request.args.get("lng") or request.args.get("longitude"))
    sql = """
        SELECT m.merchant_id, m.shop_name, m.contact_phone, m.shop_address,
               m.shop_latitude, m.shop_longitude, m.shop_location_name, m.shop_image_url,
               m.business_hours, m.shop_desc, m.merchant_type,
               COALESCE(rs.review_count, 0) AS review_count,
               rs.avg_dish_score,
               rs.avg_delivery_score
        FROM `Merchant` m
        LEFT JOIN (
            SELECT merchant_id,
                   COUNT(review_id) AS review_count,
                   ROUND(AVG(dish_score), 1) AS avg_dish_score,
                   ROUND(AVG(delivery_score), 1) AS avg_delivery_score
            FROM `Review`
            WHERE dish_id IS NULL
            GROUP BY merchant_id
        ) rs ON rs.merchant_id = m.merchant_id
        WHERE m.business_status = 1 AND m.audit_status = 1
    """
    params = []
    if keyword:
        sql += " AND (m.shop_name LIKE %s OR m.shop_desc LIKE %s OR m.shop_address LIKE %s OR m.merchant_type LIKE %s)"
        params.extend([f"%{keyword}%", f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"])
    if merchant_type:
        sql += " AND m.merchant_type = %s"
        params.append(merchant_type)
    sql += " ORDER BY m.shop_name"
    merchants = db.query_all(sql, params)
    for merchant in merchants:
        merchant["merchant_type"] = normalize_merchant_type(merchant.get("merchant_type"))
        merchant["shop_type"] = merchant_type_label(merchant["merchant_type"])
        merchant["type_icon"] = merchant_type_icon(merchant["merchant_type"])
        distance = _distance_km(lat, lng, merchant.get("shop_latitude"), merchant.get("shop_longitude"))
        merchant["distance_km"] = float(distance.quantize(Decimal("0.01"))) if distance is not None else None

    def relevance(merchant):
        if not keyword:
            return 0
        kw = keyword.lower()
        shop_name = str(merchant.get("shop_name") or "").lower()
        shop_desc = str(merchant.get("shop_desc") or "").lower()
        shop_address = str(merchant.get("shop_address") or "").lower()
        if shop_name == kw:
            return 0
        if shop_name.startswith(kw):
            return 1
        if kw in shop_name:
            return 2
        if kw in shop_desc:
            return 3
        if kw in shop_address:
            return 4
        return 5

    merchants.sort(key=lambda m: (
        relevance(m),
        m["distance_km"] if m.get("distance_km") is not None else 999999,
        m.get("shop_name") or "",
    ))
    return success(merchants)


@user_bp.route("/merchants/<int:merchant_id>", methods=["GET"])
def get_merchant_detail(merchant_id):
    """查询商家详情及评价统计。"""
    merchant = db.query_one(
        """SELECT m.merchant_id, m.shop_name, m.contact_name, m.contact_phone,
                  m.shop_address, m.shop_latitude, m.shop_longitude, m.shop_location_name, m.shop_image_url,
                  m.business_hours, m.shop_desc,
                  COALESCE(rs.review_count, 0) AS review_count,
                  rs.avg_dish_score,
                  rs.avg_delivery_score
           FROM `Merchant` m
           LEFT JOIN (
               SELECT merchant_id,
                      COUNT(review_id) AS review_count,
                      ROUND(AVG(dish_score), 1) AS avg_dish_score,
                      ROUND(AVG(delivery_score), 1) AS avg_delivery_score
               FROM `Review`
               WHERE dish_id IS NULL
               GROUP BY merchant_id
           ) rs ON rs.merchant_id = m.merchant_id
           WHERE m.merchant_id = %s""",
        (merchant_id,),
    )
    if not merchant:
        return error("商家不存在", 404)
    return success(merchant)


@user_bp.route("/merchants/<int:merchant_id>/reviews", methods=["GET"])
def get_merchant_reviews(merchant_id):
    """查询商家公开评价，供用户在商家菜单页查看。"""
    merchant = db.query_one(
        "SELECT merchant_id FROM `Merchant` WHERE merchant_id = %s AND audit_status = 1",
        (merchant_id,),
    )
    if not merchant:
        return error("商家不存在或未通过审核", 404)

    reviews = db.query_all(
        """SELECT r.review_id, r.order_id, r.dish_score, r.delivery_score,
                  r.review_type, r.content, r.merchant_reply, r.review_time,
                  u.real_name AS user_name,
                  item_summary.dish_summary
           FROM `Review` r
           JOIN `User` u ON r.user_id = u.user_id
           LEFT JOIN (
               SELECT oi.order_id,
                      GROUP_CONCAT(CONCAT(d.dish_name, 'x', oi.quantity)
                                   ORDER BY oi.order_item_id SEPARATOR '，') AS dish_summary
               FROM `Order_Item` oi
               JOIN `Dish` d ON d.dish_id = oi.dish_id
               GROUP BY oi.order_id
           ) item_summary ON item_summary.order_id = r.order_id
           WHERE r.merchant_id = %s AND r.dish_id IS NULL
           ORDER BY r.review_time DESC""",
        (merchant_id,),
    )

    summary = db.query_one(
        """SELECT COUNT(*) AS review_count,
                  ROUND(AVG(dish_score), 1) AS avg_dish_score,
                  ROUND(AVG(delivery_score), 1) AS avg_delivery_score
           FROM `Review`
           WHERE merchant_id = %s AND dish_id IS NULL""",
        (merchant_id,),
    ) or {"review_count": 0, "avg_dish_score": None, "avg_delivery_score": None}

    return success({"summary": summary, "reviews": reviews})


@user_bp.route("/dishes", methods=["GET"])
def list_dishes():
    """多条件查询菜品：商家、分类、价格区间、关键字、销量/价格排序。"""
    merchant_id = request.args.get("merchant_id", type=int)
    category = request.args.get("category", "").strip()
    keyword = request.args.get("keyword", "").strip()
    min_price = request.args.get("min_price", type=float)
    max_price = request.args.get("max_price", type=float)
    sort = request.args.get("sort", "")

    sql = """SELECT d.*, m.shop_name
             FROM `Dish` d
             JOIN `Merchant` m ON d.merchant_id = m.merchant_id
             WHERE d.sale_status = 1
               AND m.business_status = 1
               AND m.audit_status = 1"""
    params = []
    if merchant_id:
        sql += " AND d.merchant_id = %s"
        params.append(merchant_id)
    if category:
        sql += " AND d.category_name = %s"
        params.append(category)
    if keyword:
        sql += " AND (d.dish_name LIKE %s OR d.dish_desc LIKE %s OR m.shop_name LIKE %s)"
        params.extend([f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"])
    if min_price is not None:
        sql += " AND d.price >= %s"
        params.append(min_price)
    if max_price is not None:
        sql += " AND d.price <= %s"
        params.append(max_price)

    if sort == "sales":
        sql += " ORDER BY d.sales_count DESC, d.dish_id DESC"
    elif sort == "price_asc":
        sql += " ORDER BY d.price ASC, d.dish_id DESC"
    elif sort == "price_desc":
        sql += " ORDER BY d.price DESC, d.dish_id DESC"
    else:
        sql += " ORDER BY d.merchant_id, FIELD(d.category_name, '盖饭', '甜品', '水果', '小吃', '饮品', '主食', '夜宵', '粥粉面'), d.dish_id DESC"
    return success(db.query_all(sql, params))


@user_bp.route("/merchants/<int:merchant_id>/dishes/grouped", methods=["GET"])
def list_merchant_dishes_grouped(merchant_id):
    """查询指定商家的全部上架菜品，并按分类分组展示。"""
    dishes = db.query_all(
        """SELECT *
           FROM `Dish`
           WHERE merchant_id = %s AND sale_status = 1
           ORDER BY category_name, dish_id DESC""",
        (merchant_id,),
    )
    grouped = {}
    for dish in dishes:
        grouped.setdefault(dish.get("category_name") or "未分类", []).append(dish)
    return success(grouped)


@user_bp.route("/dishes/<int:dish_id>", methods=["GET"])
def get_dish_detail(dish_id):
    """查询菜品详情，并返回所属商家信息。"""
    dish = db.query_one(
        """SELECT d.*, m.shop_name, m.business_status, m.audit_status
           FROM `Dish` d
           JOIN `Merchant` m ON d.merchant_id = m.merchant_id
           WHERE d.dish_id = %s""",
        (dish_id,),
    )
    if not dish:
        return error("菜品不存在", 404)
    return success(dish)


@user_bp.route("/dishes/<int:dish_id>/reviews", methods=["GET"])
def get_dish_reviews(dish_id):
    """
    查询菜品相关历史评价。

    优先返回针对该菜品的单品评价；如果还没有单品评价，则回退展示包含该菜品的订单整体评价，
    并附带订单菜品摘要，避免把订单评价误认为单品评价。
    """
    dish = db.query_one("SELECT dish_id FROM `Dish` WHERE dish_id = %s", (dish_id,))
    if not dish:
        return error("菜品不存在", 404)

    dedicated_reviews = db.query_all(
        """SELECT r.review_id, r.order_id, r.dish_id, r.dish_score, r.delivery_score,
                  r.review_type, r.content, r.merchant_reply, r.review_time,
                  u.real_name, u.username AS user_name, d.dish_name AS review_dish_name,
                  item_summary.dish_summary,
                  'dish' AS review_scope
           FROM `Review` r
           JOIN `User` u ON r.user_id = u.user_id
           JOIN `Dish` d ON r.dish_id = d.dish_id
           LEFT JOIN (
               SELECT oi.order_id,
                      GROUP_CONCAT(CONCAT(di.dish_name, 'x', oi.quantity)
                                   ORDER BY oi.order_item_id SEPARATOR '，') AS dish_summary
               FROM `Order_Item` oi
               JOIN `Dish` di ON di.dish_id = oi.dish_id
               GROUP BY oi.order_id
           ) item_summary ON item_summary.order_id = r.order_id
           WHERE r.dish_id = %s
           ORDER BY r.review_time DESC""",
        (dish_id,),
    )
    if dedicated_reviews:
        return success(dedicated_reviews)

    order_reviews = db.query_all(
        """SELECT DISTINCT r.review_id, r.order_id, r.dish_id, r.dish_score, r.delivery_score,
                  r.review_type, r.content, r.merchant_reply, r.review_time,
                  u.real_name, u.username AS user_name, NULL AS review_dish_name,
                  item_summary.dish_summary,
                  'order' AS review_scope
           FROM `Review` r
           JOIN `User` u ON r.user_id = u.user_id
           JOIN `Order_Item` oi_filter ON oi_filter.order_id = r.order_id
           LEFT JOIN (
               SELECT oi.order_id,
                      GROUP_CONCAT(CONCAT(d.dish_name, 'x', oi.quantity)
                                   ORDER BY oi.order_item_id SEPARATOR '，') AS dish_summary
               FROM `Order_Item` oi
               JOIN `Dish` d ON d.dish_id = oi.dish_id
               GROUP BY oi.order_id
           ) item_summary ON item_summary.order_id = r.order_id
           WHERE r.dish_id IS NULL AND oi_filter.dish_id = %s
           ORDER BY r.review_time DESC""",
        (dish_id,),
    )
    return success(order_reviews)


# ==================================================
# Session 购物车
# ==================================================

@user_bp.route("/cart", methods=["GET"])
def get_cart():
    """查询当前用户 Session 购物车。"""
    user_id = get_current_user("user")
    if not user_id:
        return unauthorized()
    return success(_get_cart(user_id))


@user_bp.route("/cart/items", methods=["POST"])
def add_cart_item():
    """旧版 Session 购物车加购接口；同一 Session 购物车只支持单商家菜品。"""
    user_id = get_current_user("user")
    if not user_id:
        return unauthorized()

    data = _json_data()
    dish_id = int(data.get("dish_id") or 0)
    quantity = int(data.get("quantity") or 1)
    if dish_id <= 0 or quantity <= 0:
        return error("菜品编号和数量不合法")

    dish = db.query_one(
        """SELECT d.dish_id, d.merchant_id, d.dish_name, d.price, d.specification, d.stock,
                  m.business_status, m.audit_status
           FROM `Dish` d
           JOIN `Merchant` m ON d.merchant_id = m.merchant_id
           WHERE d.dish_id = %s AND d.sale_status = 1""",
        (dish_id,),
    )
    if not dish:
        return error("菜品不存在或已下架", 404)
    if dish["business_status"] != 1 or dish["audit_status"] != 1:
        return error("商家暂未营业")
    if dish["stock"] < quantity:
        return error("菜品库存不足")

    cart = _get_cart(user_id)
    merchant_id = int(dish["merchant_id"])
    if cart.get("merchant_id") and int(cart["merchant_id"]) != merchant_id:
        return error("购物车内已有其他商家的菜品，请先清空购物车")
    cart["merchant_id"] = merchant_id
    items = cart.setdefault("items", {})
    key = str(dish_id)
    old_qty = int(items.get(key, {}).get("quantity", 0))
    new_qty = old_qty + quantity
    if new_qty > int(dish["stock"]):
        return error("购物车数量超过当前库存")
    items[key] = {
        "dish_id": dish_id,
        "dish_name": dish["dish_name"],
        "price": str(dish["price"]),
        "quantity": new_qty,
        "specification": data.get("specification") or dish.get("specification") or "",
    }
    _save_cart(user_id, cart)
    return success(cart, "已加入购物车")


@user_bp.route("/cart/items/<int:dish_id>", methods=["PUT"])
def update_cart_item(dish_id):
    """修改购物车中某个菜品的数量和规格；数量小于等于 0 时移除该菜品。"""
    user_id = get_current_user("user")
    if not user_id:
        return unauthorized()
    data = _json_data()
    quantity = int(data.get("quantity") or 0)
    cart = _get_cart(user_id)
    items = cart.setdefault("items", {})
    key = str(dish_id)
    if key not in items:
        return error("购物车中不存在该菜品", 404)
    if quantity <= 0:
        items.pop(key, None)
    else:
        dish = db.query_one("SELECT stock FROM `Dish` WHERE dish_id = %s", (dish_id,))
        if not dish or int(dish["stock"]) < quantity:
            return error("菜品库存不足")
        items[key]["quantity"] = quantity
        if "specification" in data:
            items[key]["specification"] = data["specification"]
    if not items:
        cart = {"merchant_id": None, "items": {}}
    _save_cart(user_id, cart)
    return success(cart, "购物车已更新")


@user_bp.route("/cart/items/<int:dish_id>", methods=["DELETE"])
def delete_cart_item(dish_id):
    """删除购物车中的单个菜品。"""
    user_id = get_current_user("user")
    if not user_id:
        return unauthorized()
    cart = _get_cart(user_id)
    cart.setdefault("items", {}).pop(str(dish_id), None)
    if not cart["items"]:
        cart = {"merchant_id": None, "items": {}}
    _save_cart(user_id, cart)
    return success(cart, "菜品已从购物车移除")


@user_bp.route("/cart", methods=["DELETE"])
def clear_cart():
    """清空当前用户购物车。"""
    user_id = get_current_user("user")
    if not user_id:
        return unauthorized()
    _save_cart(user_id, {"merchant_id": None, "items": {}})
    return success(None, "购物车已清空")


@user_bp.route("/cart/checkout", methods=["POST"])
def checkout_cart():
    """基于 Session 购物车提交订单，成功后自动清空购物车。"""
    user_id = get_current_user("user")
    if not user_id:
        return unauthorized()

    cart = _get_cart(user_id)
    if not cart.get("merchant_id") or not cart.get("items"):
        return error("购物车为空")
    data = _json_data()
    items = list(cart["items"].values())
    return _create_order_endpoint(
        user_id=user_id,
        merchant_id=int(cart["merchant_id"]),
        items=items,
        data=data,
        clear_session_cart=True,
    )


# ==================================================
# 订单与支付
# ==================================================

def _resolve_order_input(user_id: int, data: Dict):
    """解析下单收货信息；缺省时回退到用户默认收货地址。"""
    receiver_name = data.get("receiver_name") or ""
    receiver_phone = data.get("receiver_phone") or ""
    receiver_address = data.get("receiver_address") or ""
    receiver_latitude = data.get("receiver_latitude") or data.get("latitude")
    receiver_longitude = data.get("receiver_longitude") or data.get("longitude")
    receiver_location_name = parse_location_name(data.get("receiver_location_name") or data.get("location_name"))
    try:
        tableware_count = int(data.get("tableware_count") or 1)
    except (TypeError, ValueError):
        return None, "餐具份数必须为数字"

    if not all([receiver_name, receiver_phone, receiver_address]):
        user = db.query_one(
            """SELECT default_receiver, default_phone, default_address,
                      default_latitude, default_longitude, default_location_name
               FROM `User` WHERE user_id = %s""",
            (user_id,),
        )
        if user:
            receiver_name = receiver_name or user.get("default_receiver") or ""
            receiver_phone = receiver_phone or user.get("default_phone") or ""
            receiver_address = receiver_address or user.get("default_address") or ""
            receiver_latitude = receiver_latitude or user.get("default_latitude")
            receiver_longitude = receiver_longitude or user.get("default_longitude")
            receiver_location_name = receiver_location_name or user.get("default_location_name")

    if not all([receiver_name, receiver_phone, receiver_address]):
        return None, "请填写完整收货信息"
    if tableware_count < 1:
        return None, "餐具份数至少选择 1 份"

    return {
        "receiver_name": receiver_name,
        "receiver_phone": receiver_phone,
        "receiver_address": receiver_address,
        "receiver_latitude": receiver_latitude,
        "receiver_longitude": receiver_longitude,
        "receiver_location_name": receiver_location_name,
        "tableware_count": tableware_count,
    }, None


def _save_default_address_if_empty(user_id: int, resolved: Dict):
    """用户首次下单但未维护默认地址时，把本次收货信息保存为默认地址。"""
    db.execute(
        """UPDATE `User`
           SET default_receiver = COALESCE(NULLIF(default_receiver, ''), %s),
               default_phone = COALESCE(NULLIF(default_phone, ''), %s),
               default_address = COALESCE(NULLIF(default_address, ''), %s),
               default_latitude = COALESCE(default_latitude, %s),
               default_longitude = COALESCE(default_longitude, %s),
               default_location_name = COALESCE(NULLIF(default_location_name, ''), %s)
           WHERE user_id = %s""",
        (
            resolved["receiver_name"],
            resolved["receiver_phone"],
            resolved["receiver_address"],
            parse_latitude(resolved["receiver_latitude"]),
            parse_longitude(resolved["receiver_longitude"]),
            resolved["receiver_location_name"],
            user_id,
        ),
    )


def _create_order_endpoint(user_id: int, merchant_id: int, items: List[Dict], data: Dict, clear_session_cart=False):
    """订单创建接口的公共实现，供直接下单和购物车结算复用。"""
    receiver_name = data.get("receiver_name") or ""
    receiver_phone = data.get("receiver_phone") or ""
    receiver_address = data.get("receiver_address") or ""
    receiver_latitude = data.get("receiver_latitude") or data.get("latitude")
    receiver_longitude = data.get("receiver_longitude") or data.get("longitude")
    receiver_location_name = parse_location_name(data.get("receiver_location_name") or data.get("location_name"))
    try:
        tableware_count = int(data.get("tableware_count") or 1)
    except (TypeError, ValueError):
        return error("餐具份数必须为数字")

    # 未显式填写收货信息时，自动使用用户默认收货信息。
    if not all([receiver_name, receiver_phone, receiver_address]):
        user = db.query_one(
            """SELECT default_receiver, default_phone, default_address,
                      default_latitude, default_longitude, default_location_name
               FROM `User` WHERE user_id = %s""",
            (user_id,),
        )
        if user:
            receiver_name = receiver_name or user.get("default_receiver") or ""
            receiver_phone = receiver_phone or user.get("default_phone") or ""
            receiver_address = receiver_address or user.get("default_address") or ""
            receiver_latitude = receiver_latitude or user.get("default_latitude")
            receiver_longitude = receiver_longitude or user.get("default_longitude")
            receiver_location_name = receiver_location_name or user.get("default_location_name")

    if not all([receiver_name, receiver_phone, receiver_address]):
        return error("请填写完整收货信息")
    if tableware_count < 1:
        return error("餐具份数至少选择 1 份")

    try:
        order_id, order_amount = _create_order_in_transaction(
            user_id=user_id,
            merchant_id=merchant_id,
            items=items,
            receiver_name=receiver_name,
            receiver_phone=receiver_phone,
            receiver_address=receiver_address,
            delivery_fee=data.get("delivery_fee", 3.00),
            tableware_count=tableware_count,
            receiver_latitude=receiver_latitude,
            receiver_longitude=receiver_longitude,
        )
        if clear_session_cart:
            _save_cart(user_id, {"merchant_id": None, "items": {}})
        # 用户首次手动填写收货信息后，若账号尚未设置默认地址，则自动保存为默认地址；
        # 后续购物车弹窗可“一键使用默认地址”，不需要每次逐项填写。
        db.execute(
            """UPDATE `User`
               SET default_receiver = COALESCE(NULLIF(default_receiver, ''), %s),
                   default_phone = COALESCE(NULLIF(default_phone, ''), %s),
                   default_address = COALESCE(NULLIF(default_address, ''), %s),
                   default_latitude = COALESCE(default_latitude, %s),
                   default_longitude = COALESCE(default_longitude, %s),
                   default_location_name = COALESCE(NULLIF(default_location_name, ''), %s)
               WHERE user_id = %s""",
            (
                receiver_name,
                receiver_phone,
                receiver_address,
                parse_latitude(receiver_latitude),
                parse_longitude(receiver_longitude),
                receiver_location_name,
                user_id,
            ),
        )
        return success(
            {"order_id": order_id, "order_amount": str(order_amount)},
            "下单成功",
        )
    except ValueError as e:
        return error(str(e))
    except Exception as e:
        return error(f"下单失败：{str(e)}")


@user_bp.route("/orders", methods=["POST"])
def create_order():
    """
    直接提交订单。

    兼容两种调用方式：
    1. 新版购物车传入 orders 分组，每个商家分组生成一个独立订单。
    2. 旧版单商家下单传入 merchant_id、items、receiver_xxx。
    无论哪种方式，后端都会做商家状态、营业时间、库存、距离和金额一致性校验。
    """
    user_id = get_current_user("user")
    if not user_id:
        return unauthorized()
    data = _json_data()
    grouped_orders = data.get("orders") or []
    if grouped_orders:
        # 新版购物车允许一次支付多个商家的商品，但订单仍按商家拆分。
        # 这样商家端、骑手端都可以继续按“一个商家一个订单”的业务单位处理。
        resolved, input_error = _resolve_order_input(user_id, data)
        if input_error:
            return error(input_error)
        created_orders = []
        total_amount = Decimal("0.00")
        try:
            for group in grouped_orders:
                merchant_id = int(group.get("merchant_id") or 0)
                items = group.get("items") or []
                if merchant_id <= 0 or not items:
                    return error("商家和菜品信息不能为空")
                order_id, order_amount = _create_order_in_transaction(
                    user_id=user_id,
                    merchant_id=merchant_id,
                    items=items,
                    receiver_name=resolved["receiver_name"],
                    receiver_phone=resolved["receiver_phone"],
                    receiver_address=resolved["receiver_address"],
                    delivery_fee=data.get("delivery_fee", 3.00),
                    tableware_count=resolved["tableware_count"],
                    receiver_latitude=resolved["receiver_latitude"],
                    receiver_longitude=resolved["receiver_longitude"],
                )
                total_amount += _money(order_amount)
                created_orders.append({
                    "order_id": order_id,
                    "merchant_id": merchant_id,
                    "order_amount": str(order_amount),
                })
            _save_default_address_if_empty(user_id, resolved)
            return success(
                {
                    "order_ids": [order["order_id"] for order in created_orders],
                    "orders": created_orders,
                    "order_count": len(created_orders),
                    "order_amount": str(_money(total_amount)),
                },
                "下单成功",
            )
        except ValueError as e:
            return error(str(e))
        except Exception as e:
            return error(f"下单失败：{str(e)}")

    # 兼容旧前端或直接购买场景：没有 orders 分组时按单商家订单创建。
    merchant_id = int(data.get("merchant_id") or 0)
    items = data.get("items") or []
    if merchant_id <= 0 or not items:
        return error("商家和菜品信息不能为空")
    return _create_order_endpoint(user_id, merchant_id, items, data)


@user_bp.route("/orders", methods=["GET"])
def list_orders():
    """查询用户全部订单，按下单时间倒序，并附带菜品摘要和配送摘要。"""
    user_id = get_current_user("user")
    if not user_id:
        return unauthorized()
    keyword = request.args.get("keyword", "").strip()
    order_status = request.args.get("order_status", type=int)
    pay_status = request.args.get("pay_status", type=int)
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()

    conditions = ["o.user_id = %s"]
    params = [user_id]
    if order_status is not None:
        if order_status == 5:
            conditions.append("(o.order_status = %s OR (o.order_status = 4 AND o.finish_time IS NOT NULL))")
            params.append(order_status)
        elif order_status == 4:
            conditions.append("o.order_status = %s AND o.finish_time IS NULL")
            params.append(order_status)
        else:
            conditions.append("o.order_status = %s")
            params.append(order_status)
    if pay_status is not None:
        conditions.append("o.pay_status = %s")
        params.append(pay_status)
    if start_date:
        conditions.append("o.create_time >= %s")
        params.append(start_date)
    if end_date:
        conditions.append("o.create_time <= %s")
        params.append(end_date + " 23:59:59" if len(end_date) == 10 else end_date)
    if keyword:
        conditions.append(
            "(CAST(o.order_id AS CHAR) LIKE %s OR m.shop_name LIKE %s OR item_summary.dish_summary LIKE %s)"
        )
        kw = f"%{keyword}%"
        params.extend([kw, kw, kw])

    orders = db.query_all(
        """SELECT o.*, m.shop_name,
                  item_summary.dish_summary,
                  r.rider_name, r.phone AS rider_phone,
                  de.delivery_status,
                  review_summary.review_id AS order_review_id
           FROM `Order_Info` o
           JOIN `Merchant` m ON o.merchant_id = m.merchant_id
           LEFT JOIN (
               SELECT oi.order_id,
                      GROUP_CONCAT(CONCAT(d.dish_name, 'x', oi.quantity)
                                   ORDER BY oi.order_item_id SEPARATOR '，') AS dish_summary
               FROM `Order_Item` oi
               JOIN `Dish` d ON d.dish_id = oi.dish_id
               GROUP BY oi.order_id
           ) item_summary ON item_summary.order_id = o.order_id
           LEFT JOIN (
               SELECT order_id, MIN(review_id) AS review_id
               FROM `Review`
               WHERE dish_id IS NULL
               GROUP BY order_id
           ) review_summary ON review_summary.order_id = o.order_id
           LEFT JOIN `Delivery` de ON de.order_id = o.order_id
           LEFT JOIN `Rider` r ON r.rider_id = COALESCE(de.rider_id, o.rider_id)
           WHERE """ + " AND ".join(conditions) + """
           ORDER BY o.create_time DESC""",
        params,
    )
    for order in orders:
        if order.get("order_status") == 4 and order.get("finish_time"):
            order["order_status"] = 5
        order["order_status_label"] = ORDER_STATUS_LABELS.get(order.get("order_status"), "未知")
        order["pay_status_label"] = PAY_STATUS_LABELS.get(order.get("pay_status"), "未知")
        order["pay_method_label"] = PAY_METHOD_LABELS.get(order.get("pay_method"), "未选择")
        order["delivery_status_label"] = DELIVERY_STATUS_LABELS.get(order.get("delivery_status"), None)
    return success(orders)


@user_bp.route("/orders/<int:order_id>", methods=["GET"])
def get_order_detail(order_id):
    """查询订单详情，关联展示菜品明细、支付信息、配送进度、评价信息。"""
    user_id = get_current_user("user")
    if not user_id:
        return unauthorized()
    order = _get_owned_order(order_id, user_id)
    if not order:
        return error("订单不存在", 404)
    items = db.query_all(
        """SELECT oi.*, d.dish_name, d.image_url, d.dish_desc
           FROM `Order_Item` oi
           JOIN `Dish` d ON oi.dish_id = d.dish_id
           WHERE oi.order_id = %s
           ORDER BY oi.order_item_id""",
        (order_id,),
    )
    delivery = db.query_one(
        """SELECT de.*, r.rider_name, r.phone AS rider_phone
           FROM `Delivery` de
           LEFT JOIN `Rider` r ON de.rider_id = r.rider_id
           WHERE de.order_id = %s""",
        (order_id,),
    )
    review = db.query_one("SELECT * FROM `Review` WHERE order_id = %s AND dish_id IS NULL", (order_id,))
    order.update({
        "items": items,
        "delivery": delivery,
        "review": review,
        "payment": {
            "pay_method": order.get("pay_method"),
            "pay_method_label": PAY_METHOD_LABELS.get(order.get("pay_method"), "未选择"),
            "pay_status": order.get("pay_status"),
            "pay_status_label": PAY_STATUS_LABELS.get(order.get("pay_status"), "未知"),
            "pay_time": order.get("pay_time"),
            "pay_amount": order.get("order_amount"),
            "delivery_fee": order.get("delivery_fee"),
        },
        "status_timeline": _build_order_timeline(order, delivery),
        "flow_steps": _build_order_flow(order, delivery),
    })
    return success(order)


@user_bp.route("/orders/<int:order_id>/pay", methods=["PUT"])
def pay_order(order_id):
    """
    修改未支付订单的支付状态。

    请求体可传：
    - pay_method：wechat/alipay/bank_card/cash
    - pay_status：1 支付成功，订单进入待接单；2 支付失败，订单保持待支付。

    支付信息会写回 Order_Info：支付方式、支付状态、支付时间、支付金额
    （支付金额直接使用订单总金额 order_amount，不允许前端篡改）。
    """
    user_id = get_current_user("user")
    if not user_id:
        return unauthorized()
    data = _json_data()
    pay_status = int(data.get("pay_status", 1))
    if pay_status not in (1, 2):
        return error("仅允许将未支付订单更新为支付成功或支付失败")
    pay_method = (data.get("pay_method") or "wechat").strip()
    if pay_method not in PAY_METHOD_LABELS:
        return error("支付方式不合法")

    order = _get_owned_order(order_id, user_id)
    if not order:
        return error("订单不存在", 404)
    if order["order_status"] == 6:
        return error("已取消订单不能支付")
    if order["pay_status"] == 1:
        return error("订单已支付")
    if order["pay_status"] == 3:
        return error("订单已退款")

    if pay_status == 1:
        pay_password = (data.get("pay_password") or data.get("payment_password") or "").strip()
        if not pay_password:
            return error("请输入支付密码")
        user = db.query_one(
            "SELECT pay_password FROM `User` WHERE user_id = %s",
            (user_id,),
        )
        if not user or not user.get("pay_password"):
            return error("未设置支付密码，请先设置支付密码")
        if user["pay_password"] != pay_password:
            return error("支付密码错误")

    # 支付成功/失败都记录本次支付处理时间，便于订单详情展示支付处理信息。
    now = datetime.now()
    next_order_status = 1 if pay_status == 1 else 0
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            if pay_status == 1 and pay_method == "wallet":
                change_wallet(
                    cursor,
                    "user",
                    user_id,
                    -_money(order.get("order_amount")),
                    "payment",
                    order_id=order_id,
                    pay_channel="wallet",
                    remark="我的钱包支付订单",
                )
            cursor.execute(
                """UPDATE `Order_Info`
                   SET pay_method = %s, pay_status = %s, pay_time = %s, order_status = %s
                   WHERE order_id = %s""",
                (pay_method, pay_status, now, next_order_status, order_id),
            )
        conn.commit()
    except Exception as e:
        conn.rollback()
        return error(f"支付失败：{str(e)}")
    return success(
        {
            "order_id": order_id,
            "pay_method": pay_method,
            "pay_method_label": PAY_METHOD_LABELS[pay_method],
            "pay_status": pay_status,
            "pay_status_label": PAY_STATUS_LABELS[pay_status],
            "pay_time": now,
            "pay_amount": order.get("order_amount"),
        },
        "支付成功" if pay_status == 1 else "已记录支付失败",
    )


@user_bp.route("/orders/pay-batch", methods=["PUT"])
def pay_orders_batch():
    """批量支付购物车拆分出的多个商家订单，统一校验支付密码并逐单更新支付状态。"""
    user_id = get_current_user("user")
    if not user_id:
        return unauthorized()
    data = _json_data()
    order_ids = []
    # 前端可能传字符串数组，这里统一转换为整数并去重，避免重复扣款或重复更新。
    for value in data.get("order_ids") or []:
        try:
            order_id = int(value)
        except (TypeError, ValueError):
            return error("订单号不合法")
        if order_id > 0 and order_id not in order_ids:
            order_ids.append(order_id)
    if not order_ids:
        return error("请选择需要支付的订单")

    pay_status = int(data.get("pay_status", 1))
    if pay_status not in (1, 2):
        return error("仅允许将订单更新为支付成功或支付失败")
    pay_method = (data.get("pay_method") or "wechat").strip()
    if pay_method not in PAY_METHOD_LABELS:
        return error("支付方式不合法")

    if pay_status == 1:
        pay_password = (data.get("pay_password") or data.get("payment_password") or "").strip()
        if not pay_password:
            return error("请输入支付密码")
        user = db.query_one("SELECT pay_password FROM `User` WHERE user_id = %s", (user_id,))
        if not user or not user.get("pay_password"):
            return error("未设置支付密码，请先设置支付密码")
        if user["pay_password"] != pay_password:
            return error("支付密码错误")

    placeholders = ",".join(["%s"] * len(order_ids))
    conn = get_db()
    now = datetime.now()
    try:
        with conn.cursor() as cursor:
            # 锁定本次需要支付的订单，避免用户重复点击支付或其他流程并发改状态。
            cursor.execute(
                f"""SELECT *
                    FROM `Order_Info`
                    WHERE user_id = %s AND order_id IN ({placeholders})
                    FOR UPDATE""",
                [user_id] + order_ids,
            )
            orders = cursor.fetchall()
            if len(orders) != len(order_ids):
                raise ValueError("部分订单不存在")
            for order in orders:
                # 每个订单独立校验状态；任何一个订单不可支付都会回滚整批支付。
                if order["order_status"] == 6:
                    raise ValueError(f"订单 {order['order_id']} 已取消，不能支付")
                if order["pay_status"] == 1:
                    raise ValueError(f"订单 {order['order_id']} 已支付")
                if order["pay_status"] == 3:
                    raise ValueError(f"订单 {order['order_id']} 已退款")
                if pay_status == 1 and pay_method == "wallet":
                    change_wallet(
                        cursor,
                        "user",
                        user_id,
                        -_money(order.get("order_amount")),
                        "payment",
                        order_id=order["order_id"],
                        pay_channel="wallet",
                        remark="购物车合并支付订单",
                    )
                cursor.execute(
                    """UPDATE `Order_Info`
                       SET pay_method = %s, pay_status = %s, pay_time = %s, order_status = %s
                       WHERE order_id = %s""",
                    (pay_method, pay_status, now, 1 if pay_status == 1 else 0, order["order_id"]),
                )
        conn.commit()
    except Exception as e:
        conn.rollback()
        return error(f"支付失败：{str(e)}")

    total_amount = sum((_money(order.get("order_amount")) for order in orders), Decimal("0.00"))
    return success(
        {
            "order_ids": order_ids,
            "pay_method": pay_method,
            "pay_method_label": PAY_METHOD_LABELS[pay_method],
            "pay_status": pay_status,
            "pay_status_label": PAY_STATUS_LABELS[pay_status],
            "pay_time": now,
            "pay_amount": str(_money(total_amount)),
        },
        "支付成功" if pay_status == 1 else "已记录支付失败",
    )


@user_bp.route("/orders/<int:order_id>/payment", methods=["GET"])
def get_order_payment(order_id):
    """查询订单支付信息。"""
    user_id = get_current_user("user")
    if not user_id:
        return unauthorized()
    order = _get_owned_order(order_id, user_id)
    if not order:
        return error("订单不存在", 404)
    return success({
        "order_id": order_id,
        "order_amount": order.get("order_amount"),
        "pay_amount": order.get("order_amount"),
        "delivery_fee": order.get("delivery_fee"),
        "pay_method": order.get("pay_method"),
        "pay_method_label": PAY_METHOD_LABELS.get(order.get("pay_method"), "未选择"),
        "pay_status": order.get("pay_status"),
        "pay_status_label": PAY_STATUS_LABELS.get(order.get("pay_status"), "未知"),
        "pay_time": order.get("pay_time"),
        "available_pay_methods": [
            {"value": key, "label": label}
            for key, label in PAY_METHOD_LABELS.items()
        ],
    })


@user_bp.route("/orders/<int:order_id>/cancel", methods=["PUT"])
def cancel_order(order_id):
    """
    取消未接单、未配送订单。

    允许状态：待支付(0)、待接单(1)。若已支付则同步设置为已退款；
    同时恢复库存并回退销量，保证数据一致。
    """
    user_id = get_current_user("user")
    if not user_id:
        return unauthorized()
    order = _get_owned_order(order_id, user_id)
    if not order:
        return error("订单不存在", 404)
    if order["order_status"] not in (0, 1):
        return error("当前订单状态不可取消")

    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT dish_id, quantity FROM `Order_Item` WHERE order_id = %s",
                (order_id,),
            )
            items = cursor.fetchall()
            for item in items:
                cursor.execute(
                    """UPDATE `Dish`
                       SET stock = stock + %s,
                           sales_count = GREATEST(sales_count - %s, 0)
                       WHERE dish_id = %s""",
                    (item["quantity"], item["quantity"], item["dish_id"]),
                )
            if order["pay_status"] == 1:
                apply_order_refund(
                    cursor,
                    order_id,
                    1,
                    "用户取消订单，退款回我的钱包",
                    after_sale_result="用户取消订单，系统自动退款",
                )
            cursor.execute(
                "UPDATE `Order_Info` SET order_status = 6 WHERE order_id = %s",
                (order_id,),
            )
        conn.commit()
        return success(None, "订单已取消")
    except Exception as e:
        conn.rollback()
        return error(f"取消失败：{str(e)}")


@user_bp.route("/orders/<int:order_id>/confirm", methods=["PUT"])
def confirm_order(order_id):
    """用户确认收货，将配送中/已送达订单更新为已完成。"""
    user_id = get_current_user("user")
    if not user_id:
        return unauthorized()
    order = _get_owned_order(order_id, user_id)
    if not order:
        return error("订单不存在", 404)
    if order["order_status"] == 5:
        return success(None, "订单已完成")
    if order["order_status"] not in (4,):
        return error("当前订单状态不能确认收货")
    now = datetime.now()
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """UPDATE `Order_Info`
                   SET order_status = 5, finish_time = %s
                   WHERE order_id = %s""",
                (now, order_id),
            )
            cursor.execute(
                "SELECT * FROM `Delivery` WHERE order_id = %s FOR UPDATE",
                (order_id,),
            )
            delivery = cursor.fetchone()
            delivery_fee = wallet_money(order.get("delivery_fee"))
            rider_income = delivery_fee if delivery_fee > Decimal("0.00") else Decimal("5.00")
            cursor.execute(
                """UPDATE `Delivery`
                   SET delivery_status = 2,
                       delivered_time = COALESCE(delivered_time, %s),
                       delivery_income = COALESCE(delivery_income, %s)
                   WHERE order_id = %s""",
                (now, rider_income, order_id),
            )
            merchant_income = wallet_money(order.get("order_amount")) - delivery_fee
            if merchant_income > Decimal("0.00"):
                change_wallet(
                    cursor,
                    "merchant",
                    order["merchant_id"],
                    merchant_income,
                    "merchant_income",
                    order_id=order_id,
                    remark="订单完成入账",
                )
            rider_id = (delivery or {}).get("rider_id") or order.get("rider_id")
            if rider_id and rider_income > Decimal("0.00"):
                change_wallet(
                    cursor,
                    "rider",
                    rider_id,
                    rider_income,
                    "rider_income",
                    order_id=order_id,
                    delivery_id=(delivery or {}).get("delivery_id"),
                    remark="配送完成入账",
                )
        conn.commit()
        return success(None, "确认收货成功")
    except Exception as e:
        conn.rollback()
        return error(f"确认收货失败：{str(e)}")


@user_bp.route("/orders/<int:order_id>/status", methods=["GET"])
def track_order_status(order_id):
    """实时查询订单当前状态、配送员信息和状态时间线。"""
    user_id = get_current_user("user")
    if not user_id:
        return unauthorized()
    order = _get_owned_order(order_id, user_id)
    if not order:
        return error("订单不存在", 404)
    delivery = db.query_one(
        """SELECT de.*, r.rider_name, r.phone AS rider_phone
           FROM `Delivery` de
           LEFT JOIN `Rider` r ON de.rider_id = r.rider_id
           WHERE de.order_id = %s""",
        (order_id,),
    )
    flow_steps = _build_order_flow(order, delivery)
    return success({
        "order_id": order_id,
        "shop_name": order.get("shop_name"),
        "merchant_phone": order.get("contact_phone"),
        "merchant_address": order.get("shop_address"),
        "receiver_name": order.get("receiver_name"),
        "receiver_phone": order.get("receiver_phone"),
        "receiver_address": order.get("receiver_address"),
        "order_amount": order.get("order_amount"),
        "delivery_fee": order.get("delivery_fee"),
        "create_time": order.get("create_time"),
        "order_status": order["order_status"],
        "order_status_label": ORDER_STATUS_LABELS.get(order["order_status"], "未知"),
        "pay_status": order["pay_status"],
        "pay_status_label": PAY_STATUS_LABELS.get(order["pay_status"], "未知"),
        "pay_method": order.get("pay_method"),
        "pay_method_label": PAY_METHOD_LABELS.get(order.get("pay_method"), "未选择"),
        "pay_time": order.get("pay_time"),
        "rider": None if not delivery else {
            "rider_id": delivery.get("rider_id"),
            "rider_name": delivery.get("rider_name"),
            "rider_phone": delivery.get("rider_phone"),
        },
        "delivery": delivery,
        "timeline": _build_order_timeline(order, delivery),
        "flow_steps": flow_steps,
        "current_step": next((step for step in flow_steps if step.get("current")), None),
    })


@user_bp.route("/orders/history/summary", methods=["GET"])
def get_history_summary():
    """查询用户历史订单数量和总消费金额，支持 start_date/end_date 过滤。"""
    user_id = get_current_user("user")
    if not user_id:
        return unauthorized()
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    sql = """SELECT COUNT(*) AS order_count,
                    SUM(CASE WHEN order_status = 5 THEN 1 ELSE 0 END) AS completed_order_count,
                    COALESCE(SUM(CASE WHEN pay_status = 1 THEN order_amount ELSE 0 END), 0) AS total_paid_amount
             FROM `Order_Info`
             WHERE user_id = %s"""
    params = [user_id]
    if start_date:
        sql += " AND create_time >= %s"
        params.append(start_date)
    if end_date:
        sql += " AND create_time <= %s"
        params.append(end_date)
    return success(db.query_one(sql, params))


@user_bp.route("/orders/<int:order_id>", methods=["DELETE"])
def delete_order(order_id):
    """
    删除已完成/已取消且无售后纠纷的历史订单。

    说明：需求文档希望“仅删除用户端展示，平台保留备份”，但当前 8 表数据库
    没有 is_deleted 字段或备份表；这里采用物理删除，并按外键顺序删除子表。
    """
    user_id = get_current_user("user")
    if not user_id:
        return unauthorized()
    order = _get_owned_order(order_id, user_id)
    if not order:
        return error("订单不存在", 404)
    if order["order_status"] not in (5, 6):
        return error("只能删除已完成或已取消订单")
    if order["after_sale_status"] != 0:
        return error("该订单存在售后纠纷，不能删除")

    conn = get_db()
    try:
        with conn.cursor() as cursor:
            # 先删从表，再删主表，避免外键 RESTRICT 报错。
            cursor.execute("DELETE FROM `Review` WHERE order_id = %s", (order_id,))
            cursor.execute("DELETE FROM `Delivery` WHERE order_id = %s", (order_id,))
            cursor.execute("DELETE FROM `Order_Item` WHERE order_id = %s", (order_id,))
            cursor.execute(
                "DELETE FROM `Order_Info` WHERE order_id = %s AND user_id = %s",
                (order_id, user_id),
            )
        conn.commit()
        return success(None, "订单已删除")
    except Exception as e:
        conn.rollback()
        return error(f"删除失败：{str(e)}")


# ==================================================
# 评价管理
# ==================================================


@user_bp.route("/orders/<int:order_id>/after-sale", methods=["POST"])
def apply_after_sale(order_id):
    """提交已完成订单的售后/投诉申请，后续由管理员审核退款结果。"""
    user_id = get_current_user("user")
    if not user_id:
        return unauthorized()
    data = _json_data()
    reason = (data.get("reason") or data.get("content") or "").strip()
    if not reason:
        return error("请填写售后原因")

    order = _get_owned_order(order_id, user_id)
    if not order:
        return error("订单不存在", 404)
    if order["order_status"] != 5:
        return error("只有已完成订单才能申请售后；配送异常由平台强制退款处理")
    if order["pay_status"] != 1:
        return error("只有已支付且未退款订单才能申请售后")
    if order["after_sale_status"] == 1:
        return error("该订单已有待处理售后申请")
    if order["after_sale_status"] == 2:
        return error("该订单售后申请已处理")

    now = datetime.now()
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """UPDATE `Order_Info`
                   SET after_sale_status = 1,
                       after_sale_apply_time = %s,
                       after_sale_reason = %s
                   WHERE order_id = %s AND user_id = %s""",
                (now, reason, order_id, user_id),
            )
            cursor.execute("SELECT review_id FROM `Review` WHERE order_id = %s AND dish_id IS NULL", (order_id,))
            review = cursor.fetchone()
            if review:
                cursor.execute(
                    """UPDATE `Review`
                       SET review_type = 2,
                           complaint_status = 1,
                           content = COALESCE(NULLIF(content, ''), %s)
                       WHERE review_id = %s""",
                    (reason, review["review_id"]),
                )
                review_id = review["review_id"]
            else:
                cursor.execute(
                    """INSERT INTO `Review`
                       (order_id, user_id, merchant_id, rider_id, review_type, complaint_status,
                        content, review_time)
                       VALUES (%s, %s, %s, %s, 2, 1, %s, %s)""",
                    (order_id, user_id, order["merchant_id"], order.get("rider_id"), reason, now),
                )
                review_id = cursor.lastrowid
        conn.commit()
        return success({"order_id": order_id, "review_id": review_id}, "售后申请已提交，等待管理员审核")
    except Exception as e:
        conn.rollback()
        return error(f"售后申请提交失败：{str(e)}")


@user_bp.route("/reviews", methods=["GET"])
def list_reviews():
    """查询当前用户全部评价记录，支持关键字、类型、回复状态、时间范围筛选。"""
    user_id = get_current_user("user")
    if not user_id:
        return unauthorized()
    keyword = request.args.get("keyword", "").strip()
    review_type = request.args.get("review_type", type=int)
    reply_status = request.args.get("reply_status", "").strip()  # 回复筛选：已回复/未回复
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()

    sql = """SELECT r.*, m.shop_name, o.order_amount, o.create_time AS order_time,
                    o.tableware_count, item_summary.dish_summary, d.dish_name AS review_dish_name
             FROM `Review` r
             JOIN `Merchant` m ON r.merchant_id = m.merchant_id
             JOIN `Order_Info` o ON r.order_id = o.order_id
             LEFT JOIN `Dish` d ON r.dish_id = d.dish_id
             LEFT JOIN (
                 SELECT oi.order_id,
                        GROUP_CONCAT(CONCAT(d.dish_name, 'x', oi.quantity)
                                     ORDER BY oi.order_item_id SEPARATOR '，') AS dish_summary
                 FROM `Order_Item` oi
                 JOIN `Dish` d ON d.dish_id = oi.dish_id
                 GROUP BY oi.order_id
             ) item_summary ON item_summary.order_id = r.order_id
             WHERE r.user_id = %s"""
    params = [user_id]
    if keyword:
        sql += " AND (CAST(r.order_id AS CHAR) LIKE %s OR m.shop_name LIKE %s OR r.content LIKE %s OR d.dish_name LIKE %s)"
        kw = f"%{keyword}%"
        params.extend([kw, kw, kw, kw])
    if review_type in (1, 2):
        sql += " AND r.review_type = %s"
        params.append(review_type)
    if reply_status == "replied":
        sql += " AND r.merchant_reply IS NOT NULL AND r.merchant_reply <> ''"
    elif reply_status == "unreplied":
        sql += " AND (r.merchant_reply IS NULL OR r.merchant_reply = '')"
    if start_date:
        sql += " AND r.review_time >= %s"
        params.append(start_date)
    if end_date:
        sql += " AND r.review_time <= %s"
        params.append(end_date + " 23:59:59" if len(end_date) == 10 else end_date)
    sql += " ORDER BY r.review_time DESC"

    reviews = db.query_all(sql, params)
    return success(reviews)


@user_bp.route("/reviews/<int:review_id>", methods=["GET"])
def get_review_detail(review_id):
    """查询单条评价详情。"""
    user_id = get_current_user("user")
    if not user_id:
        return unauthorized()
    review = db.query_one(
        """SELECT r.*, m.shop_name
           FROM `Review` r
           JOIN `Merchant` m ON r.merchant_id = m.merchant_id
           WHERE r.review_id = %s AND r.user_id = %s""",
        (review_id, user_id),
    )
    if not review:
        return error("评价不存在", 404)
    return success(review)


@user_bp.route("/orders/<int:order_id>/review", methods=["GET"])
def get_order_review(order_id):
    """查询指定订单对应的评价详情。"""
    user_id = get_current_user("user")
    if not user_id:
        return unauthorized()
    order = _get_owned_order(order_id, user_id)
    if not order:
        return error("订单不存在", 404)
    review = db.query_one("SELECT * FROM `Review` WHERE order_id = %s AND dish_id IS NULL", (order_id,))
    return success(review)


@user_bp.route("/reviews", methods=["POST"])
def add_review():
    """
    新增订单整体评价/投诉评价，并可附带若干条单品评价。

    dish_reviews 为选填数组：[{dish_id, content}]。内容为空的单品评价会被忽略。
    """
    user_id = get_current_user("user")
    if not user_id:
        return unauthorized()
    data = _json_data()
    order_id = int(data.get("order_id") or 0)
    if order_id <= 0:
        return error("请提供订单编号")

    order = _get_owned_order(order_id, user_id)
    if not order:
        return error("订单不存在", 404)
    if order["order_status"] != 5:
        return error("只有已完成订单才能评价")
    if db.query_one("SELECT review_id FROM `Review` WHERE order_id = %s AND dish_id IS NULL", (order_id,)):
        return error("该订单已评价")

    dish_score = data.get("dish_score")
    delivery_score = data.get("delivery_score")
    review_type = int(data.get("review_type") or 1)
    if dish_score is not None and int(dish_score) not in range(1, 6):
        return error("菜品评分必须为 1-5")
    if delivery_score is not None and int(delivery_score) not in range(1, 6):
        return error("配送评分必须为 1-5")
    if review_type not in (1, 2):
        return error("评价类型不合法")

    order_items = db.query_all(
        """SELECT oi.dish_id, d.dish_name
           FROM `Order_Item` oi
           JOIN `Dish` d ON d.dish_id = oi.dish_id
           WHERE oi.order_id = %s""",
        (order_id,),
    )
    order_dish_ids = {int(item["dish_id"]) for item in order_items}
    dish_reviews = []
    for item in data.get("dish_reviews") or []:
        try:
            item_dish_id = int(item.get("dish_id") or 0)
        except (TypeError, ValueError):
            return error("单品评价菜品编号不合法")
        content = (item.get("content") or "").strip()
        if not item_dish_id and not content:
            continue
        if item_dish_id not in order_dish_ids:
            return error("单品评价只能选择该订单中的菜品")
        if not content:
            continue
        dish_reviews.append({"dish_id": item_dish_id, "content": content})

    now = datetime.now()
    complaint_status = 1 if review_type == 2 else 0
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """INSERT INTO `Review`
                   (order_id, user_id, merchant_id, rider_id, dish_id, dish_score, delivery_score,
                    review_type, complaint_status, content, review_time)
                   VALUES (%s, %s, %s, %s, NULL, %s, %s, %s, %s, %s, %s)""",
                (
                    order_id,
                    user_id,
                    order["merchant_id"],
                    order.get("rider_id"),
                    dish_score,
                    delivery_score,
                    review_type,
                    complaint_status,
                    data.get("content", ""),
                    now,
                ),
            )
            review_id = cursor.lastrowid
            dish_review_ids = []
            for item in dish_reviews:
                cursor.execute(
                    """INSERT INTO `Review`
                       (order_id, user_id, merchant_id, rider_id, dish_id, dish_score, delivery_score,
                        review_type, complaint_status, content, review_time)
                       VALUES (%s, %s, %s, %s, %s, %s, NULL, 1, 0, %s, %s)""",
                    (
                        order_id,
                        user_id,
                        order["merchant_id"],
                        order.get("rider_id"),
                        item["dish_id"],
                        dish_score,
                        item["content"],
                        now,
                    ),
                )
                dish_review_ids.append(cursor.lastrowid)
            if review_type == 2:
                cursor.execute(
                    """UPDATE `Order_Info`
                       SET after_sale_status = 1,
                           after_sale_apply_time = COALESCE(after_sale_apply_time, %s),
                           after_sale_reason = COALESCE(NULLIF(after_sale_reason, ''), %s)
                       WHERE order_id = %s""",
                    (now, data.get("content", ""), order_id),
                )
        conn.commit()
        return success({"review_id": review_id, "dish_review_ids": dish_review_ids}, "评价提交成功")
    except Exception as e:
        conn.rollback()
        return error(f"评价提交失败：{str(e)}")


@user_bp.route("/reviews/<int:review_id>", methods=["PUT"])
def update_review(review_id):
    """修改未被商家回复的评价内容、评分和评价类型。"""
    user_id = get_current_user("user")
    if not user_id:
        return unauthorized()
    review = db.query_one(
        "SELECT * FROM `Review` WHERE review_id = %s AND user_id = %s",
        (review_id, user_id),
    )
    if not review:
        return error("评价不存在", 404)
    if review.get("merchant_reply"):
        return error("商家已回复，无法修改评价")

    data = _json_data()
    update_fields, params = [], []
    for field in ["dish_score", "delivery_score", "content", "review_type"]:
        if field in data:
            if field in ("dish_score", "delivery_score") and data[field] is not None:
                if int(data[field]) not in range(1, 6):
                    return error("评分必须为 1-5")
            if field == "review_type" and int(data[field]) not in (1, 2):
                return error("评价类型不合法")
            update_fields.append(f"`{field}` = %s")
            params.append(data[field])
    if not update_fields:
        return error("没有需要修改的字段")
    params.append(review_id)
    db.execute(f"UPDATE `Review` SET {', '.join(update_fields)} WHERE review_id = %s", params)
    return success(None, "评价修改成功")


@user_bp.route("/reviews/<int:review_id>", methods=["DELETE"])
def delete_review(review_id):
    """
    删除个人评价。

    当前数据库没有“平台备份/用户端隐藏”字段，因此仅允许删除普通且未回复评价；
    投诉评价或已被商家回复的评价保留，避免影响监管与纠纷处理。
    """
    user_id = get_current_user("user")
    if not user_id:
        return unauthorized()
    review = db.query_one(
        "SELECT * FROM `Review` WHERE review_id = %s AND user_id = %s",
        (review_id, user_id),
    )
    if not review:
        return error("评价不存在", 404)
    if review.get("review_type") == 2:
        return error("投诉评价不能由用户直接删除")
    if review.get("merchant_reply"):
        return error("商家已回复的评价不能删除")
    db.execute("DELETE FROM `Review` WHERE review_id = %s", (review_id,))
    return success(None, "评价已删除")
