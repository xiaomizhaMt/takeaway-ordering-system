# ==================================================
# 外卖订餐管理系统 - 数据库初始化/迁移脚本
# 默认安全迁移；显式 --reset 才重建数据库和示例数据
# ==================================================
import argparse
import pymysql
import os
import sys

# 将项目根目录加入 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.config import DatabaseConfig

HOST = DatabaseConfig.HOST
PORT = DatabaseConfig.PORT
USER = DatabaseConfig.USER
PASSWORD = DatabaseConfig.PASSWORD
CHARSET = DatabaseConfig.CHARSET
DB_NAME = DatabaseConfig.DATABASE


BASE_TABLES = ['User', 'Merchant', 'Rider', 'Dish', 'Order_Info', 'Order_Item', 'Delivery', 'Review']
WALLET_TABLE = 'Wallet_Transaction'


def load_sql_statements(sql_file, skip_database_commands=True):
    """
    读取 SQL 文件并拆分为可执行语句。

    原来的写法是直接 content.split(';')，然后判断 stmt.startswith('--')。
    但项目 SQL 文件里经常是：

        -- 注释
        INSERT INTO ...

    这种情况下拆出来的一整段会以 "--" 开头，真正的 INSERT 语句也会被跳过，
    导致示例商家、菜品、订单等数据没有导入。

    这里先逐行去掉 "--" 注释行，再按分号拆分，保证注释后面的 SQL 能正常执行。
    """
    with open(sql_file, 'r', encoding='utf-8-sig') as f:
        lines = f.readlines()

    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        # 跳过空行和整行注释；保留 SQL 语句本身。
        if not stripped or stripped.startswith('--'):
            continue
        cleaned_lines.append(line)

    statements = []
    for stmt in ''.join(cleaned_lines).split(';'):
        stmt = stmt.strip()
        if not stmt:
            continue

        upper = stmt.upper()
        # 数据库创建/选择已由 Python 脚本负责，避免重复 DROP/CREATE/USE。
        if skip_database_commands and (
            upper.startswith('DROP DATABASE')
            or upper.startswith('CREATE DATABASE')
            or upper.startswith('USE ')
        ):
            continue
        statements.append(stmt)

    return statements


def connect(database=None):
    kwargs = {
        'host': HOST,
        'port': PORT,
        'user': USER,
        'password': PASSWORD,
        'charset': CHARSET,
    }
    if database:
        kwargs['database'] = database
    return pymysql.connect(**kwargs)


def database_exists(cursor):
    cursor.execute("SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME = %s", (DB_NAME,))
    return cursor.fetchone() is not None


def table_exists(cursor, table_name):
    cursor.execute(
        """SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
           WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s""",
        (DB_NAME, table_name),
    )
    return cursor.fetchone() is not None


def column_exists(cursor, table_name, column_name):
    cursor.execute(
        """SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
           WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s""",
        (DB_NAME, table_name, column_name),
    )
    return cursor.fetchone() is not None


def index_exists(cursor, table_name, index_name):
    cursor.execute(
        """SELECT INDEX_NAME FROM INFORMATION_SCHEMA.STATISTICS
           WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND INDEX_NAME = %s""",
        (DB_NAME, table_name, index_name),
    )
    return cursor.fetchone() is not None


def create_database_if_needed():
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(f'CREATE DATABASE IF NOT EXISTS `{DB_NAME}` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
    conn.commit()
    cursor.close()
    conn.close()


def run_reset(sql_dir):
    """危险模式：清空并重建数据库，再插入示例数据。"""
    print('=' * 50)
    print(' 外卖订餐管理系统 - 数据库重建')
    print('=' * 50)

    # 第一步：创建数据库
    print('\n[第1步] 删除并重建数据库...')
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(f'DROP DATABASE IF EXISTS `{DB_NAME}`')
    cursor.execute(f'CREATE DATABASE `{DB_NAME}` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
    conn.commit()
    cursor.close()
    conn.close()
    print(f'  数据库 {DB_NAME} 重建成功')

    # 第二步：建表 + 外键 + 索引
    print('\n[第2步] 建表 + 外键 + 索引...')
    conn = connect(DB_NAME)
    
    # 按分号拆分成独立 SQL 语句执行。注意：需要先去掉注释行，
    # 否则“注释 + SQL”的语句块会被错误跳过。
    statements = load_sql_statements(os.path.join(sql_dir, '01_create_database.sql'))
    
    cursor = conn.cursor()
    success_count = 0
    for stmt in statements:
        try:
            cursor.execute(stmt)
            success_count += 1
        except Exception as e:
            print(f'  跳过: [{stmt[:60]}...] {e}')
    conn.commit()
    cursor.close()
    print(f'  执行了 {success_count} 条语句')

    # 第三步：插入示例数据
    print('\n[第3步] 插入示例数据...')
    statements = load_sql_statements(os.path.join(sql_dir, '03_insert_sample_data.sql'))
    
    cursor = conn.cursor()
    success_count = 0
    for stmt in statements:
        try:
            cursor.execute(stmt)
            success_count += 1
        except Exception as e:
            print(f'  跳过: [{stmt[:60]}...] {e}')
    conn.commit()
    cursor.close()
    print(f'  执行了 {success_count} 条语句')

    conn.close()

    # 验证
    print('\n[第4步] 验证数据...')
    print_table_counts(BASE_TABLES + [WALLET_TABLE])

    print('\n' + '=' * 50)
    print(' 数据库重建完成！')
    print('=' * 50)


def create_wallet_transaction_table(cursor):
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


def add_index_if_missing(cursor, table_name, index_name, ddl):
    if not index_exists(cursor, table_name, index_name):
        cursor.execute(ddl)
        return True
    return False


def add_column_if_missing(cursor, table_name, column_name, ddl, changes):
    if not column_exists(cursor, table_name, column_name):
        cursor.execute(f"ALTER TABLE `{table_name}` ADD COLUMN `{column_name}` {ddl}")
        changes.append(f'{table_name}.{column_name}')


def run_safe_migration():
    """默认模式：只补新增字段和表，不删除、不覆盖已有业务数据。"""
    print('=' * 50)
    print(' 外卖订餐管理系统 - 数据库安全迁移')
    print('=' * 50)

    print('\n[第1步] 确认数据库存在...')
    create_database_if_needed()
    print(f'  数据库 {DB_NAME} 已就绪')

    conn = connect(DB_NAME)
    cursor = conn.cursor()
    changes = []
    try:
        print('\n[第2步] 检查基础表...')
        missing_tables = [t for t in BASE_TABLES if not table_exists(cursor, t)]
        if missing_tables:
            print('  缺少基础表：' + ', '.join(missing_tables))
            print('  为避免误初始化生产库，默认迁移不会自动建基础业务表。')
            print('  如果这是全新环境或你已手动删除本地数据库，请运行：python init_db.py --reset')
            return
        print('  基础业务表存在')

        print('\n[第3步] 补齐钱包相关结构...')
        for table in ['User', 'Merchant', 'Rider']:
            if not column_exists(cursor, table, 'wallet_balance'):
                cursor.execute(
                    f"""ALTER TABLE `{table}`
                        ADD COLUMN `wallet_balance` DECIMAL(10,2) NOT NULL DEFAULT 0.00
                        COMMENT '钱包余额'"""
                )
                changes.append(f'{table}.wallet_balance')

        if not table_exists(cursor, WALLET_TABLE):
            create_wallet_transaction_table(cursor)
            changes.append(WALLET_TABLE)
        else:
            if add_index_if_missing(
                cursor,
                WALLET_TABLE,
                'idx_wallet_owner_time',
                "CREATE INDEX `idx_wallet_owner_time` ON `Wallet_Transaction` (`owner_type`, `owner_id`, `create_time`)",
            ):
                changes.append('idx_wallet_owner_time')
            if add_index_if_missing(
                cursor,
                WALLET_TABLE,
                'idx_wallet_order',
                "CREATE INDEX `idx_wallet_order` ON `Wallet_Transaction` (`related_order_id`)",
            ):
                changes.append('idx_wallet_order')
            if add_index_if_missing(
                cursor,
                WALLET_TABLE,
                'idx_wallet_delivery',
                "CREATE INDEX `idx_wallet_delivery` ON `Wallet_Transaction` (`related_delivery_id`)",
            ):
                changes.append('idx_wallet_delivery')

        print('\n[绗?姝 琛ラ綈鍦板浘瀹氫綅瀛楁...')
        add_column_if_missing(cursor, 'User', 'default_latitude', "DECIMAL(10,7) NULL COMMENT 'default address latitude' AFTER `default_address`", changes)
        add_column_if_missing(cursor, 'User', 'default_longitude', "DECIMAL(10,7) NULL COMMENT 'default address longitude' AFTER `default_latitude`", changes)
        add_column_if_missing(cursor, 'User', 'default_location_name', "VARCHAR(120) NULL COMMENT 'default address POI name' AFTER `default_longitude`", changes)
        add_column_if_missing(cursor, 'Merchant', 'shop_latitude', "DECIMAL(10,7) NULL COMMENT 'shop latitude' AFTER `shop_address`", changes)
        add_column_if_missing(cursor, 'Merchant', 'shop_longitude', "DECIMAL(10,7) NULL COMMENT 'shop longitude' AFTER `shop_latitude`", changes)
        add_column_if_missing(cursor, 'Merchant', 'shop_location_name', "VARCHAR(120) NULL COMMENT 'shop POI name' AFTER `shop_longitude`", changes)
        add_column_if_missing(cursor, 'Merchant', 'shop_image_url', "VARCHAR(255) NULL COMMENT 'shop image URL' AFTER `shop_location_name`", changes)
        add_column_if_missing(cursor, 'Order_Info', 'receiver_latitude', "DECIMAL(10,7) NULL COMMENT 'receiver latitude snapshot' AFTER `receiver_address`", changes)
        add_column_if_missing(cursor, 'Order_Info', 'receiver_longitude', "DECIMAL(10,7) NULL COMMENT 'receiver longitude snapshot' AFTER `receiver_latitude`", changes)
        add_column_if_missing(cursor, 'Order_Info', 'merchant_latitude', "DECIMAL(10,7) NULL COMMENT 'merchant latitude snapshot' AFTER `receiver_longitude`", changes)
        add_column_if_missing(cursor, 'Order_Info', 'merchant_longitude', "DECIMAL(10,7) NULL COMMENT 'merchant longitude snapshot' AFTER `merchant_latitude`", changes)

        conn.commit()
        if changes:
            print('  已更新：' + ', '.join(changes))
        else:
            print('  无需更新，数据库结构已是最新')
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()

    print('\n[第4步] 验证数据...')
    print_table_counts(BASE_TABLES + [WALLET_TABLE])

    print('\n' + '=' * 50)
    print(' 安全迁移完成，已有数据未删除')
    print('=' * 50)


def print_table_counts(tables):
    conn = connect(DB_NAME)
    cursor = conn.cursor()
    for t in tables:
        if not table_exists(cursor, t):
            print(f'  {t}: 表不存在')
            continue
        cursor.execute(f'SELECT COUNT(*) FROM `{t}`')
        cnt = cursor.fetchone()[0]
        print(f'  {t}: {cnt} 条记录')
    cursor.close()
    conn.close()


def main():
    parser = argparse.ArgumentParser(description='外卖订餐管理系统数据库初始化/迁移脚本')
    parser.add_argument(
        '--reset',
        action='store_true',
        help='危险操作：删除并重建数据库，然后插入示例数据。默认不删除任何已有数据。',
    )
    args = parser.parse_args()
    sql_dir = os.path.join(os.path.dirname(__file__), 'database')

    if args.reset:
        run_reset(sql_dir)
    else:
        run_safe_migration()


if __name__ == '__main__':
    main()
