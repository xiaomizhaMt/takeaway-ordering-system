# ==================================================
# 外卖订餐管理系统 - 数据库连接辅助模块
# ==================================================
# 每个请求创建独立连接，避免多线程共用同一连接导致数据竞争
import pymysql
from flask import g
from backend.config import DatabaseConfig


def get_db():
    """获取当前请求的数据库连接（存储在 Flask g 对象中）"""
    if 'db' not in g:
        g.db = pymysql.connect(
            host=DatabaseConfig.HOST,
            port=DatabaseConfig.PORT,
            user=DatabaseConfig.USER,
            password=DatabaseConfig.PASSWORD,
            database=DatabaseConfig.DATABASE,
            charset=DatabaseConfig.CHARSET,
            cursorclass=pymysql.cursors.DictCursor
        )
    return g.db


def close_db(exception=None):
    """关闭当前请求的数据库连接"""
    db = g.pop('db', None)
    if db is not None:
        db.close()


class DBHelper:
    """数据库操作辅助类，使用 Flask g 对象管理连接（线程安全）"""

    def query_all(self, sql, params=None):
        """查询多条记录"""
        conn = get_db()
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql, params or ())
                return cursor.fetchall()
        except Exception as e:
            raise e

    def query_one(self, sql, params=None):
        """查询单条记录"""
        conn = get_db()
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql, params or ())
                return cursor.fetchone()
        except Exception as e:
            raise e

    def execute(self, sql, params=None):
        """执行插入/更新/删除操作，返回受影响行数"""
        conn = get_db()
        try:
            with conn.cursor() as cursor:
                affected = cursor.execute(sql, params or ())
                conn.commit()
                return affected
        except Exception as e:
            conn.rollback()
            raise e

    def execute_return_id(self, sql, params=None):
        """执行插入操作，返回自增ID"""
        conn = get_db()
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql, params or ())
                conn.commit()
                return cursor.lastrowid
        except Exception as e:
            conn.rollback()
            raise e

    # ========== 事务操作方法 ==========
    # 用于并发抢单等需要行锁的场景：

    def begin_transaction(self):
        """开启事务"""
        conn = get_db()
        conn.begin()

    def commit(self):
        """提交事务"""
        conn = get_db()
        conn.commit()

    def rollback(self):
        """回滚事务"""
        conn = get_db()
        conn.rollback()

    def query_one_with_lock(self, sql, params=None):
        """在事务内使用 SELECT ... FOR UPDATE 行锁查询单条记录"""
        conn = get_db()
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql + " FOR UPDATE", params or ())
                return cursor.fetchone()
        except Exception as e:
            raise e


