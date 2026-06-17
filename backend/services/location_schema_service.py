"""地图选点相关的数据库兼容迁移与经纬度解析工具。"""
from decimal import Decimal, InvalidOperation

from backend.db.db_helper import get_db


_location_schema_checked = False


def _column_exists(cursor, table_name, column_name):
    """检查指定表中是否已经存在某个字段。"""
    cursor.execute(f"SHOW COLUMNS FROM `{table_name}` LIKE %s", (column_name,))
    return cursor.fetchone() is not None


def ensure_location_schema():
    """补齐地图选点需要的经纬度字段，不删除或覆盖已有业务数据。"""
    global _location_schema_checked
    if _location_schema_checked:
        return

    conn = get_db()
    try:
        with conn.cursor() as cursor:
            columns = {
                "User": [
                    ("default_latitude", "DECIMAL(10,7) NULL COMMENT '默认收货地址纬度' AFTER `default_address`"),
                    ("default_longitude", "DECIMAL(10,7) NULL COMMENT '默认收货地址经度' AFTER `default_latitude`"),
                    ("default_location_name", "VARCHAR(120) NULL COMMENT '默认收货地址地点名称' AFTER `default_longitude`"),
                ],
                "Merchant": [
                    ("shop_latitude", "DECIMAL(10,7) NULL COMMENT '店铺纬度' AFTER `shop_address`"),
                    ("shop_longitude", "DECIMAL(10,7) NULL COMMENT '店铺经度' AFTER `shop_latitude`"),
                    ("shop_location_name", "VARCHAR(120) NULL COMMENT '店铺地点名称' AFTER `shop_longitude`"),
                    ("shop_image_url", "VARCHAR(255) NULL COMMENT '店铺图片地址' AFTER `shop_location_name`"),
                ],
                "Order_Info": [
                    ("receiver_latitude", "DECIMAL(10,7) NULL COMMENT '收货地址纬度快照' AFTER `receiver_address`"),
                    ("receiver_longitude", "DECIMAL(10,7) NULL COMMENT '收货地址经度快照' AFTER `receiver_latitude`"),
                    ("merchant_latitude", "DECIMAL(10,7) NULL COMMENT '商家纬度快照' AFTER `receiver_longitude`"),
                    ("merchant_longitude", "DECIMAL(10,7) NULL COMMENT '商家经度快照' AFTER `merchant_latitude`"),
                ],
            }
            for table_name, specs in columns.items():
                for column_name, ddl in specs:
                    if not _column_exists(cursor, table_name, column_name):
                        cursor.execute(f"ALTER TABLE `{table_name}` ADD COLUMN `{column_name}` {ddl}")
        conn.commit()
        _location_schema_checked = True
    except Exception:
        conn.rollback()
        raise


def parse_coordinate(value, *, min_value, max_value):
    """解析并校验经纬度，非法或空值统一返回 None。"""
    if value in (None, ""):
        return None
    try:
        coord = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if coord < Decimal(str(min_value)) or coord > Decimal(str(max_value)):
        return None
    return coord.quantize(Decimal("0.0000001"))


def parse_latitude(value):
    """解析纬度，合法范围为 -90 到 90。"""
    return parse_coordinate(value, min_value=-90, max_value=90)


def parse_longitude(value):
    """解析经度，合法范围为 -180 到 180。"""
    return parse_coordinate(value, min_value=-180, max_value=180)


def parse_location_name(value):
    """清理地图地点名称，限制长度以匹配数据库字段。"""
    value = (value or "").strip()
    return value[:120] if value else None
