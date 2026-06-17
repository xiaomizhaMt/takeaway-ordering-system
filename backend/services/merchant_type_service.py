from backend.db.db_helper import DBHelper


# 数据库里可能已经存在早期编码问题写入的旧值。为了兼容现有检查约束，
# 后端继续按旧存储值落库，同时允许前端传入正常中文商家类型。
TYPE_LABEL_TO_STORAGE = {
    "奶茶咖啡": "濂惰尪鍜栧暋",
    "汉堡快餐": "姹夊牎蹇",
    "米粉汤面": "绫崇矇姹ら潰",
    "烧烤小吃": "鐑х儰灏忓悆",
    "粥食甜品": "绮ラ鐢滃搧",
    "热炒正餐": "鐑倰姝ｉ",
    "其他": "鍏朵粬",
}

TYPE_STORAGE_TO_LABEL = {v: k for k, v in TYPE_LABEL_TO_STORAGE.items()}
MERCHANT_TYPES = list(TYPE_STORAGE_TO_LABEL.keys())
MERCHANT_TYPE_LABELS = list(TYPE_LABEL_TO_STORAGE.keys())

MERCHANT_TYPE_ICONS = {
    "濂惰尪鍜栧暋": "☕",
    "姹夊牎蹇": "🍔",
    "绫崇矇姹ら潰": "🍜",
    "鐑х儰灏忓悆": "🍢",
    "绮ラ鐢滃搧": "🍰",
    "鐑倰姝ｉ": "🍲",
    "鍏朵粬": "🍽️",
}

_schema_checked = False
_db = DBHelper()


def normalize_merchant_type(value, default="鍏朵粬"):
    """把前端中文类型或旧库存储值统一转换为数据库存储值。"""
    value = (value or "").strip()
    if value in TYPE_LABEL_TO_STORAGE:
        return TYPE_LABEL_TO_STORAGE[value]
    if value in TYPE_STORAGE_TO_LABEL:
        return value
    return default


def merchant_type_label(value):
    """把数据库存储值转换为前端展示的中文商家类型。"""
    storage = normalize_merchant_type(value)
    return TYPE_STORAGE_TO_LABEL.get(storage, "其他")


def merchant_type_icon(merchant_type):
    """根据商家类型返回前端卡片使用的默认图标。"""
    return MERCHANT_TYPE_ICONS.get(normalize_merchant_type(merchant_type), "🍽️")


def infer_merchant_type(merchant):
    """根据店铺名称、简介和菜品关键词推断商家类型。"""
    shop_text = " ".join(str(merchant.get(k) or "") for k in ("shop_name", "shop_desc", "category_names", "dish_keywords"))

    if any(k in shop_text for k in ("咖啡", "奶茶", "茶饮", "饮品", "果茶", "豆浆", "酸梅汤")):
        return TYPE_LABEL_TO_STORAGE["奶茶咖啡"]
    if any(k in shop_text for k in ("汉堡", "炸鸡", "薯条", "披萨", "快餐", "三明治", "轻食", "沙拉")):
        return TYPE_LABEL_TO_STORAGE["汉堡快餐"]
    if any(k in shop_text for k in ("米粉", "汤面", "粉面", "粥粉面", "拉面", "面条", "牛肉面", "螺蛳粉", "馄饨", "馄饨")):
        return TYPE_LABEL_TO_STORAGE["米粉汤面"]
    if any(k in shop_text for k in ("烧烤", "烤串", "炸串", "串串", "烤鸡", "烤肉", "小吃", "夜宵")):
        return TYPE_LABEL_TO_STORAGE["烧烤小吃"]
    if any(k in shop_text for k in ("粥", "甜品", "蛋糕", "烘焙", "面包", "糕点", "糯米", "甜点")):
        return TYPE_LABEL_TO_STORAGE["粥食甜品"]
    if any(k in shop_text for k in ("热炒", "正餐", "川菜", "湘菜", "小炒", "炒菜", "盖饭", "套餐", "家常菜", "米饭")):
        return TYPE_LABEL_TO_STORAGE["热炒正餐"]
    return TYPE_LABEL_TO_STORAGE["其他"]


def ensure_merchant_type_schema():
    """兼容旧数据库：补齐商家类型字段、检查约束并回填已有商家类型。"""
    global _schema_checked
    if _schema_checked:
        return

    col = _db.query_one("SHOW COLUMNS FROM `Merchant` LIKE 'merchant_type'")
    added_column = False
    if not col:
        _db.execute("ALTER TABLE `Merchant` ADD COLUMN `merchant_type` VARCHAR(20) NOT NULL DEFAULT '鍏朵粬' COMMENT '商家类型'")
        added_column = True
    _ensure_merchant_type_check_constraint()

    _backfill_merchant_types(force=added_column)
    _schema_checked = True


def _ensure_merchant_type_check_constraint():
    """修复旧库中的商家类型 CHECK 约束，使其覆盖当前所有兼容存储值。"""
    try:
        constraint = _db.query_one(
            """SELECT CONSTRAINT_NAME
               FROM information_schema.CHECK_CONSTRAINTS
               WHERE CONSTRAINT_SCHEMA = DATABASE()
                 AND CONSTRAINT_NAME = 'chk_merchant_type'"""
        )
    except Exception:
        return
    if not constraint:
        return
    try:
        values = "', '".join(MERCHANT_TYPES)
        _db.execute("ALTER TABLE `Merchant` DROP CHECK `chk_merchant_type`")
        _db.execute(
            "ALTER TABLE `Merchant` ADD CONSTRAINT `chk_merchant_type` "
            f"CHECK (`merchant_type` IN ('{values}'))"
        )
    except Exception:
        pass


def _backfill_merchant_types(force=False):
    """为历史商家回填类型；已明确设置的类型默认不覆盖。"""
    merchants = _db.query_all(
        """SELECT m.merchant_id, m.account, m.shop_name, m.shop_desc, m.merchant_type,
                  ds.category_names, ds.dish_keywords
           FROM `Merchant` m
           LEFT JOIN (
               SELECT merchant_id,
                      GROUP_CONCAT(DISTINCT category_name) AS category_names,
                      GROUP_CONCAT(CONCAT_WS(' ', dish_name, dish_desc) SEPARATOR ' ') AS dish_keywords
               FROM `Dish`
               WHERE sale_status = 1
               GROUP BY merchant_id
           ) ds ON ds.merchant_id = m.merchant_id"""
    )
    for merchant in merchants:
        current = normalize_merchant_type(merchant.get("merchant_type"), default="")
        fixed_type = _fixed_sample_merchant_type(merchant)
        if fixed_type:
            if current != fixed_type:
                _db.execute(
                    "UPDATE `Merchant` SET merchant_type = %s WHERE merchant_id = %s",
                    (fixed_type, merchant["merchant_id"]),
                )
            continue
        if current and not force and current != TYPE_LABEL_TO_STORAGE["其他"]:
            continue
        inferred = infer_merchant_type(merchant)
        if not force and current == TYPE_LABEL_TO_STORAGE["其他"] and inferred == TYPE_LABEL_TO_STORAGE["其他"]:
            continue
        _db.execute(
            "UPDATE `Merchant` SET merchant_type = %s WHERE merchant_id = %s",
            (inferred, merchant["merchant_id"]),
        )


def _fixed_sample_merchant_type(merchant):
    """修正示例数据中少量固定商家的类型，避免被关键词误判。"""
    account = (merchant.get("account") or "").strip()
    shop_name = (merchant.get("shop_name") or "").strip()
    if account == "merchant001" and shop_name in ("川香小馆", "宸濋灏忛"):
        return TYPE_LABEL_TO_STORAGE["热炒正餐"]
    if account == "merchant003" and shop_name in ("深夜食堂24H", "娣卞椋熷爞24H"):
        return TYPE_LABEL_TO_STORAGE["米粉汤面"]
    return None
