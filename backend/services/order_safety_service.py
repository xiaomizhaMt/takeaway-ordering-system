"""订单边缘流程与售后/退款辅助逻辑。

本项目数据库按课程设计收敛为少量核心表，因此售后、退款、投诉审核等
边缘状态统一补充在 Order_Info / Review 表中，避免再引入新的业务表。
"""

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from backend.db.db_helper import get_db
from backend.services.wallet_service import change_wallet


_schema_checked = False


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _column_exists(cursor, table: str, column: str) -> bool:
    cursor.execute(f"SHOW COLUMNS FROM `{table}` LIKE %s", (column,))
    return cursor.fetchone() is not None


def _index_exists(cursor, table: str, index_name: str) -> bool:
    cursor.execute(f"SHOW INDEX FROM `{table}` WHERE Key_name = %s", (index_name,))
    return cursor.fetchone() is not None


def _constraint_exists(cursor, table: str, constraint_name: str) -> bool:
    cursor.execute(
        """SELECT 1
           FROM information_schema.TABLE_CONSTRAINTS
           WHERE TABLE_SCHEMA = DATABASE()
             AND TABLE_NAME = %s
             AND CONSTRAINT_NAME = %s""",
        (table, constraint_name),
    )
    return cursor.fetchone() is not None


def ensure_order_edge_schema():
    """兼容旧库：补齐订单监管、售后、退款和投诉审核字段。"""
    global _schema_checked
    if _schema_checked:
        return

    conn = get_db()
    with conn.cursor() as cursor:
        order_columns = [
            (
                "after_sale_apply_time",
                "ALTER TABLE `Order_Info` ADD COLUMN `after_sale_apply_time` DATETIME NULL "
                "COMMENT '售后申请时间' AFTER `after_sale_status`",
            ),
            (
                "after_sale_reason",
                "ALTER TABLE `Order_Info` ADD COLUMN `after_sale_reason` VARCHAR(500) NULL "
                "COMMENT '售后申请原因' AFTER `after_sale_apply_time`",
            ),
            (
                "after_sale_result",
                "ALTER TABLE `Order_Info` ADD COLUMN `after_sale_result` VARCHAR(500) NULL "
                "COMMENT '售后处理结果/管理员审核说明' AFTER `after_sale_reason`",
            ),
            (
                "after_sale_handle_time",
                "ALTER TABLE `Order_Info` ADD COLUMN `after_sale_handle_time` DATETIME NULL "
                "COMMENT '售后处理时间' AFTER `after_sale_result`",
            ),
            (
                "refund_amount",
                "ALTER TABLE `Order_Info` ADD COLUMN `refund_amount` DECIMAL(10,2) NOT NULL DEFAULT 0.00 "
                "COMMENT '实际退款金额' AFTER `after_sale_handle_time`",
            ),
            (
                "refund_type",
                "ALTER TABLE `Order_Info` ADD COLUMN `refund_type` TINYINT NOT NULL DEFAULT 0 "
                "COMMENT '退款类型：0无，1全额退款，2部分退款50%' AFTER `refund_amount`",
            ),
            (
                "refund_reason",
                "ALTER TABLE `Order_Info` ADD COLUMN `refund_reason` VARCHAR(300) NULL "
                "COMMENT '退款原因' AFTER `refund_type`",
            ),
            (
                "refund_time",
                "ALTER TABLE `Order_Info` ADD COLUMN `refund_time` DATETIME NULL "
                "COMMENT '退款处理时间' AFTER `refund_reason`",
            ),
        ]
        for column, ddl in order_columns:
            if not _column_exists(cursor, "Order_Info", column):
                cursor.execute(ddl)

        review_columns = [
            (
                "dish_id",
                "ALTER TABLE `Review` ADD COLUMN `dish_id` BIGINT NULL "
                "COMMENT '单品评价关联菜品；为空表示订单整体评价' AFTER `rider_id`",
            ),
            (
                "complaint_status",
                "ALTER TABLE `Review` ADD COLUMN `complaint_status` TINYINT NOT NULL DEFAULT 0 "
                "COMMENT '投诉审核状态：0无投诉/未进入审核，1待审核，2审核通过，3审核驳回' AFTER `review_type`",
            ),
            (
                "complaint_refund_type",
                "ALTER TABLE `Review` ADD COLUMN `complaint_refund_type` TINYINT NOT NULL DEFAULT 0 "
                "COMMENT '投诉退款结论：0无，1全额退款，2部分退款50%' AFTER `complaint_status`",
            ),
            (
                "complaint_handle_note",
                "ALTER TABLE `Review` ADD COLUMN `complaint_handle_note` VARCHAR(500) NULL "
                "COMMENT '投诉审核备注' AFTER `merchant_reply`",
            ),
            (
                "complaint_handle_time",
                "ALTER TABLE `Review` ADD COLUMN `complaint_handle_time` DATETIME NULL "
                "COMMENT '投诉审核时间' AFTER `complaint_handle_note`",
            ),
        ]
        for column, ddl in review_columns:
            if not _column_exists(cursor, "Review", column):
                cursor.execute(ddl)

        # 评价由“每订单一条”扩展为“订单整体评价 + 可选单品评价”。
        # 旧库的 uk_review_order_id 可能同时被 fk_review_order 依赖，所以必须先建替代索引再删唯一索引。
        if not _index_exists(cursor, "Review", "idx_review_order_dish"):
            cursor.execute("CREATE INDEX `idx_review_order_dish` ON `Review` (`order_id`, `dish_id`)")
        if not _index_exists(cursor, "Review", "idx_review_dish_time"):
            cursor.execute("CREATE INDEX `idx_review_dish_time` ON `Review` (`dish_id`, `review_time`)")
        if _index_exists(cursor, "Review", "uk_review_order_id"):
            cursor.execute("ALTER TABLE `Review` DROP INDEX `uk_review_order_id`")
        if not _constraint_exists(cursor, "Review", "fk_review_dish"):
            cursor.execute(
                "ALTER TABLE `Review` ADD CONSTRAINT `fk_review_dish` "
                "FOREIGN KEY (`dish_id`) REFERENCES `Dish` (`dish_id`) "
                "ON UPDATE CASCADE ON DELETE SET NULL"
            )

    conn.commit()
    _schema_checked = True


def calculate_refund_amount(order, refund_type: int) -> Decimal:
    """refund_type: 1=全额，2=部分退款(50%)。"""
    amount = _money(order.get("order_amount"))
    if refund_type == 1:
        return amount
    if refund_type == 2:
        return _money(amount * Decimal("0.50"))
    return Decimal("0.00")


def apply_order_refund(cursor, order_id: int, refund_type: int, reason: str, *, after_sale_result: str = None):
    """在既有事务中对订单执行退款标记；已退款订单不会重复退款。"""
    if refund_type not in (1, 2):
        raise ValueError("退款类型必须为 1(全额) 或 2(50%部分退款)")

    cursor.execute("SELECT * FROM `Order_Info` WHERE order_id = %s FOR UPDATE", (order_id,))
    order = cursor.fetchone()
    if not order:
        raise ValueError("订单不存在")
    if order.get("refund_type") in (1, 2) or _money(order.get("refund_amount")) > 0:
        raise ValueError("订单已退款，不能重复退款")
    if order.get("pay_status") not in (1,):
        raise ValueError("仅已支付且未退款订单可执行退款")

    refund_amount = calculate_refund_amount(order, refund_type)
    now = datetime.now()
    cursor.execute(
        """UPDATE `Order_Info`
           SET pay_status = 3,
               after_sale_status = 2,
               after_sale_result = %s,
               after_sale_handle_time = %s,
               refund_amount = %s,
               refund_type = %s,
               refund_reason = %s,
               refund_time = %s
           WHERE order_id = %s""",
        (
            after_sale_result or reason,
            now,
            refund_amount,
            refund_type,
            reason,
            now,
            order_id,
        ),
    )
    change_wallet(
        cursor,
        "user",
        order["user_id"],
        refund_amount,
        "refund",
        order_id=order_id,
        pay_channel="wallet",
        remark=reason or "订单退款回我的钱包",
    )
    return refund_amount


def force_refund_order(order_id: int, reason: str, refund_type: int = 1):
    """平台强制退款，默认全额退款。"""
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            refund_amount = apply_order_refund(
                cursor,
                order_id,
                refund_type,
                reason,
                after_sale_result=f"平台强制退款：{reason}",
            )
        conn.commit()
        return refund_amount
    except Exception:
        conn.rollback()
        raise
