# ==================================================
# 钱包服务：三端余额与资金流水
# ==================================================
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from backend.db.db_helper import get_db


ROLE_TABLES = {
    "user": ("User", "user_id"),
    "merchant": ("Merchant", "merchant_id"),
    "rider": ("Rider", "rider_id"),
}

INCOME_TYPES = {"merchant_income", "rider_income"}

_wallet_schema_checked = False
_wallet_backfill_checked = False


def money(value) -> Decimal:
    """将输入金额转换为 Decimal，保留两位小数，避免浮点数精度问题。"""
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def ensure_wallet_schema():
    """兼容旧库：补齐三端钱包余额字段和钱包流水表。"""
    global _wallet_schema_checked
    if _wallet_schema_checked:
        return

    conn = get_db()
    with conn.cursor() as cursor:
        for table in ("User", "Merchant", "Rider"):
            cursor.execute(f"SHOW COLUMNS FROM `{table}` LIKE 'wallet_balance'")
            if not cursor.fetchone():
                cursor.execute(
                    f"""ALTER TABLE `{table}`
                        ADD COLUMN `wallet_balance` DECIMAL(10,2) NOT NULL DEFAULT 0.00
                        COMMENT '钱包余额'"""
                )

        cursor.execute(
            """CREATE TABLE IF NOT EXISTS `Wallet_Transaction` (
                 `transaction_id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键，钱包流水编号',
                 `owner_type` VARCHAR(20) NOT NULL COMMENT '钱包归属：user/merchant/rider',
                 `owner_id` BIGINT NOT NULL COMMENT '归属主体ID',
                 `transaction_type` VARCHAR(30) NOT NULL COMMENT '流水类型',
                 `amount` DECIMAL(10,2) NOT NULL COMMENT '变动金额：收入为正，支出为负',
                 `balance_after` DECIMAL(10,2) NOT NULL COMMENT '变动后余额',
                 `related_order_id` BIGINT NULL COMMENT '关联订单',
                 `related_delivery_id` BIGINT NULL COMMENT '关联配送',
                 `pay_channel` VARCHAR(20) NULL COMMENT '充值或提现渠道',
                 `remark` VARCHAR(300) NULL COMMENT '备注',
                 `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
                 PRIMARY KEY (`transaction_id`),
                 INDEX `idx_wallet_owner_time` (`owner_type`, `owner_id`, `create_time`),
                 INDEX `idx_wallet_order` (`related_order_id`),
                 INDEX `idx_wallet_delivery` (`related_delivery_id`),
                 CONSTRAINT `chk_wallet_owner_type` CHECK (`owner_type` IN ('user', 'merchant', 'rider')),
                 CONSTRAINT `chk_wallet_amount` CHECK (`amount` <> 0)
               ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='钱包资金流水表'"""
        )
    conn.commit()
    _wallet_schema_checked = True


def _owner_table(owner_type: str):
    if owner_type not in ROLE_TABLES:
        raise ValueError("钱包归属类型不合法")
    return ROLE_TABLES[owner_type]


def get_wallet(owner_type: str, owner_id: int, limit: int = 50):
    ensure_wallet_schema()
    table, pk = _owner_table(owner_type)
    conn = get_db()
    with conn.cursor() as cursor:
        cursor.execute(
            f"SELECT wallet_balance FROM `{table}` WHERE {pk} = %s",
            (owner_id,),
        )
        owner = cursor.fetchone()
        if not owner:
            raise ValueError("钱包账户不存在")
        cursor.execute(
            """SELECT * FROM `Wallet_Transaction`
               WHERE owner_type = %s AND owner_id = %s
               ORDER BY create_time DESC, transaction_id DESC
               LIMIT %s""",
            (owner_type, owner_id, int(limit or 50)),
        )
        transactions = cursor.fetchall()
        cursor.execute(
            """SELECT
                 COALESCE(SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END), 0) AS total_income,
                 COALESCE(SUM(CASE WHEN transaction_type = 'withdraw' THEN -amount ELSE 0 END), 0) AS total_withdraw,
                 COALESCE(SUM(CASE WHEN transaction_type = 'recharge' THEN amount ELSE 0 END), 0) AS total_recharge
               FROM `Wallet_Transaction`
               WHERE owner_type = %s AND owner_id = %s""",
            (owner_type, owner_id),
        )
        summary = cursor.fetchone() or {}
    return {
        "balance": owner.get("wallet_balance"),
        "transactions": transactions,
        "summary": summary,
    }


def _has_income_transaction(cursor, owner_type, owner_id, transaction_type, order_id=None, delivery_id=None):
    if transaction_type not in INCOME_TYPES:
        return False
    if delivery_id is not None:
        cursor.execute(
            """SELECT transaction_id FROM `Wallet_Transaction`
               WHERE owner_type = %s AND owner_id = %s AND transaction_type = %s
                 AND related_delivery_id = %s
               LIMIT 1""",
            (owner_type, owner_id, transaction_type, delivery_id),
        )
    else:
        cursor.execute(
            """SELECT transaction_id FROM `Wallet_Transaction`
               WHERE owner_type = %s AND owner_id = %s AND transaction_type = %s
                 AND related_order_id = %s
               LIMIT 1""",
            (owner_type, owner_id, transaction_type, order_id),
        )
    return cursor.fetchone() is not None


def change_wallet(
    cursor,
    owner_type: str,
    owner_id: int,
    amount,
    transaction_type: str,
    *,
    order_id=None,
    delivery_id=None,
    pay_channel=None,
    remark=None,
):
    amount = money(amount)
    if amount == Decimal("0.00"):
        raise ValueError("钱包变动金额不能为0")
    table, pk = _owner_table(owner_type)

    if _has_income_transaction(cursor, owner_type, owner_id, transaction_type, order_id, delivery_id):
        return None

    cursor.execute(
        f"SELECT wallet_balance FROM `{table}` WHERE {pk} = %s FOR UPDATE",
        (owner_id,),
    )
    owner = cursor.fetchone()
    if not owner:
        raise ValueError("钱包账户不存在")
    current = money(owner.get("wallet_balance"))
    new_balance = money(current + amount)
    if new_balance < Decimal("0.00"):
        raise ValueError("钱包余额不足")

    cursor.execute(
        f"UPDATE `{table}` SET wallet_balance = %s WHERE {pk} = %s",
        (new_balance, owner_id),
    )
    cursor.execute(
        """INSERT INTO `Wallet_Transaction`
           (owner_type, owner_id, transaction_type, amount, balance_after,
            related_order_id, related_delivery_id, pay_channel, remark, create_time)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            owner_type,
            owner_id,
            transaction_type,
            amount,
            new_balance,
            order_id,
            delivery_id,
            pay_channel,
            remark,
            datetime.now(),
        ),
    )
    return {"amount": amount, "balance_after": new_balance}


def recharge_user_wallet(user_id: int, amount, pay_channel: str):
    ensure_wallet_schema()
    if pay_channel not in ("wechat", "alipay", "bank_card"):
        raise ValueError("充值方式不合法")
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            result = change_wallet(
                cursor,
                "user",
                user_id,
                money(amount),
                "recharge",
                pay_channel=pay_channel,
                remark="用户钱包充值",
            )
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise


def withdraw_wallet(owner_type: str, owner_id: int, amount, pay_channel: str = "bank_card"):
    ensure_wallet_schema()
    if owner_type == "user":
        raise ValueError("用户钱包暂不支持提现")
    amount = money(amount)
    if amount <= Decimal("0.00"):
        raise ValueError("提现金额必须大于0")
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            result = change_wallet(
                cursor,
                owner_type,
                owner_id,
                -amount,
                "withdraw",
                pay_channel=pay_channel or "bank_card",
                remark="模拟提现",
            )
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise


def backfill_wallet_income():
    """为旧数据补齐已完成订单和已送达配送的收入流水。"""
    global _wallet_backfill_checked
    if _wallet_backfill_checked:
        return
    ensure_wallet_schema()
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """SELECT order_id, merchant_id, order_amount, delivery_fee
                   FROM `Order_Info`
                   WHERE order_status = 5"""
            )
            for order in cursor.fetchall():
                merchant_income = money(order.get("order_amount")) - money(order.get("delivery_fee"))
                if merchant_income > Decimal("0.00"):
                    change_wallet(
                        cursor,
                        "merchant",
                        order["merchant_id"],
                        merchant_income,
                        "merchant_income",
                        order_id=order["order_id"],
                        remark="历史完成订单补入账",
                    )

            cursor.execute(
                """SELECT delivery_id, order_id, rider_id, delivery_income
                   FROM `Delivery`
                   WHERE delivery_status = 2 AND delivery_income IS NOT NULL"""
            )
            for delivery in cursor.fetchall():
                income = money(delivery.get("delivery_income"))
                if income > Decimal("0.00"):
                    change_wallet(
                        cursor,
                        "rider",
                        delivery["rider_id"],
                        income,
                        "rider_income",
                        order_id=delivery["order_id"],
                        delivery_id=delivery["delivery_id"],
                        remark="历史配送收益补入账",
                    )
        conn.commit()
        _wallet_backfill_checked = True
    except Exception:
        conn.rollback()
        raise
