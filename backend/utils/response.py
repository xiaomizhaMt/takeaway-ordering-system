# ==================================================
# 外卖订餐管理系统 - 统一响应格式
# ==================================================
from flask import jsonify


def success(data=None, message='操作成功'):
    """成功响应"""
    return jsonify({
        'code': 200,
        'message': message,
        'data': data
    })


def error(message='操作失败', code=400):
    """错误响应"""
    return jsonify({
        'code': code,
        'message': message,
        'data': None
    }), code


def unauthorized(message='未登录或登录已过期'):
    """未授权响应"""
    return jsonify({
        'code': 401,
        'message': message,
        'data': None
    }), 401


def forbidden(message='权限不足'):
    """无权限响应"""
    return jsonify({
        'code': 403,
        'message': message,
        'data': None
    }), 403


def not_found(message='资源不存在'):
    """未找到资源"""
    return jsonify({
        'code': 404,
        'message': message,
        'data': None
    }), 404
