# ============================================================
# 外卖订餐管理系统 - 完整业务流程演示脚本
# ============================================================
# 演示角色：用户 zhangsan、商家 merchant001、骑手 rider001
# 流程：浏览菜品 → 下单 → 支付 → 商家接单出餐 → 骑手配送 → 确认收货
# ============================================================
import os, sys, time
os.environ['USERNAME'] = '30215'
sys.path.insert(0, r'C:\Users\30215\Desktop\数据库课程设计')

from backend.app import create_app
from backend.db.db_helper import DBHelper

app = create_app()
client = app.test_client()

# ── 清理上次残留 ──
with app.app_context():
    db = DBHelper()
    db.execute("DELETE FROM `Review` WHERE order_id > 3")
    db.execute("DELETE FROM `Delivery`")
    db.execute("DELETE FROM `Order_Item` WHERE order_id > 3")
    db.execute("DELETE FROM `Order_Info` WHERE order_id > 3")
    db.execute("DELETE FROM `Dish` WHERE dish_id > 8")
    db.execute("ALTER TABLE `Dish` AUTO_INCREMENT = 9")
    db.execute("UPDATE `Dish` SET stock = 100, sales_count = 25 WHERE dish_id = 1")
    db.execute("UPDATE `Dish` SET stock = 50,  sales_count = 9  WHERE dish_id = 2")
    db.execute("UPDATE `Dish` SET stock = 100, sales_count = 30 WHERE dish_id = 3")
    db.execute("UPDATE `Dish` SET stock = 80,  sales_count = 20 WHERE dish_id = 4")
    db.execute("UPDATE `Dish` SET stock = 80,  sales_count = 10 WHERE dish_id = 5")
    db.execute("UPDATE `Dish` SET stock = 100, sales_count = 20 WHERE dish_id = 6")
    db.execute("UPDATE `Dish` SET stock = 150, sales_count = 30 WHERE dish_id = 7")
    db.execute("UPDATE `Dish` SET stock = 100, sales_count = 1  WHERE dish_id = 8")
    db.execute("UPDATE `Merchant` SET business_hours = '00:00-23:59' WHERE merchant_id = 1")
    db.execute("UPDATE `Merchant` SET business_hours = '00:00-23:59' WHERE merchant_id = 2")
    db.execute("UPDATE `Rider` SET work_status = 1 WHERE rider_id = 1")
    db.execute("UPDATE `Rider` SET work_status = 2 WHERE rider_id = 2")
    db.execute("UPDATE `User` SET default_receiver='', default_phone='', default_address='' WHERE user_id = 1")

PASS = 0; FAIL = 0
def step(title):
    print(f"\n{'='*65}")
    print(f"  {title}")
    print(f"{'='*65}")

def check(label, condition, detail=""):
    global PASS, FAIL
    mark = "✅" if condition else "❌"
    print(f"  {mark} {label}")
    if not condition and detail:
        print(f"     → {detail}")
    if condition: PASS += 1
    else: FAIL += 1

# ============================================================
# 第一步：三方登录
# ============================================================
step("第一步：三方登录")

resp = client.post('/api/auth/login', json={'username': 'zhangsan', 'password': '123456', 'role': 'user'})
data = resp.get_json()
user_token = data['data']['token']
check("用户 zhangsan 登录", data['code'] == 200)
print(f"     Token: {user_token[:20]}...")

resp = client.post('/api/auth/login', json={'username': 'merchant001', 'password': '123456', 'role': 'merchant'})
data = resp.get_json()
merchant_token = data['data']['token']
check("商家 merchant001 登录", data['code'] == 200)

resp = client.post('/api/auth/login', json={'username': 'rider001', 'password': '123456', 'role': 'rider'})
data = resp.get_json()
rider_token = data['data']['token']
check("骑手 rider001 登录", data['code'] == 200)

# ============================================================
# 第二步：用户浏览菜品
# ============================================================
step("第二步：用户浏览川香小馆菜品（merchant_id=1）")

resp = client.get('/api/user/dishes?merchant_id=1',
                  headers={'X-Auth-Token': user_token})
dishes = resp.get_json()['data']
check("查询菜品列表成功", resp.get_json()['code'] == 200 and len(dishes) > 0)

# 按分类展示
from collections import defaultdict
by_cat = defaultdict(list)
for d in dishes:
    by_cat[d['category_name']].append(d)

for cat, items in by_cat.items():
    print(f"\n  【{cat}】")
    for d in items:
        status = "在售" if d['sale_status'] == 1 else "已下架"
        print(f"    #{d['dish_id']} {d['dish_name']:10s} ¥{d['price']:>6}  库存:{d['stock']}  {status}")

# 用户选择
selected = [
    {'dish_id': 1, 'quantity': 2, 'name': '鱼香肉丝盖饭', 'price': 18},
    {'dish_id': 2, 'quantity': 1, 'name': '红糖糍粑',     'price': 8},
    {'dish_id': 3, 'quantity': 3, 'name': '酸梅汤',       'price': 4},
]
total = sum(it['price'] * it['quantity'] for it in selected)
print(f"\n  📋 已选菜品：")
for it in selected:
    print(f"    {it['name']} ×{it['quantity']}  = ¥{it['price'] * it['quantity']}")
print(f"    {'─'*25}")
print(f"    合计：¥{total}")

# ============================================================
# 第三步：提交订单
# ============================================================
step("第三步：用户提交订单")

order_payload = {
    'merchant_id': 1,
    'items': [{'dish_id': s['dish_id'], 'quantity': s['quantity']} for s in selected],
    'receiver_name': '张三',
    'receiver_phone': '13800000001',
    'receiver_address': '江苏科技大学',
    'remark': '少放辣椒，酸梅汤多加冰'
}
resp = client.post('/api/user/orders',
                   headers={'X-Auth-Token': user_token},
                   json=order_payload)
data = resp.get_json()
check("下单成功", data['code'] == 200, data.get('message',''))
order_id = data['data']['order_id']
order_amount = data['data']['order_amount']
print(f"     订单编号：#{order_id}")
print(f"     订单金额：¥{order_amount}")
print(f"     收货地址：江苏科技大学")

# ============================================================
# 第四步：用户支付
# ============================================================
step("第四步：用户在线支付")

resp = client.put(f'/api/user/orders/{order_id}/pay',
                  headers={'X-Auth-Token': user_token},
                  json={'pay_method': 'wechat', 'pay_password': '123456'})
data = resp.get_json()
check("微信支付成功", data['code'] == 200)

# 查一下当前订单状态
resp = client.get(f'/api/user/orders/{order_id}',
                  headers={'X-Auth-Token': user_token})
order = resp.get_json()['data']
status_map = {0:'待支付', 1:'待接单', 2:'备餐中', 3:'待配送', 4:'配送中', 5:'已完成', 6:'已取消'}
print(f"     当前状态：{status_map.get(order.get('order_status'), '未知')}")

# ============================================================
# 第五步：商家接单 + 备餐出餐
# ============================================================
step("第五步：商家处理订单")

# 5.1 商家查看新订单
resp = client.get(f'/api/merchant/orders?status=pending',
                  headers={'X-Auth-Token': merchant_token})
orders = resp.get_json()['data']
check("商家看到待接单列表", any(o['order_id'] == order_id for o in orders))

# 5.2 接单
resp = client.put(f'/api/merchant/orders/{order_id}/accept',
                  headers={'X-Auth-Token': merchant_token})
check("商家接单（待接单→备餐中）", resp.get_json()['code'] == 200)
print(f"     川香小馆后厨开始备餐...")

# 5.3 查询订单明细
resp = client.get(f'/api/merchant/core/orders/{order_id}/items',
                  headers={'X-Auth-Token': merchant_token})
items = resp.get_json()['data']
check("商家查看订单明细", resp.get_json()['code'] == 200 and len(items) > 0)
print(f"     后厨出菜单：")
for it in items:
    print(f"       · {it['dish_name']} ×{it['quantity']} = ¥{it['subtotal']}")

# 5.4 出餐
time.sleep(0.5)
print(f"     ⏳ 备餐完成，等待骑手取餐...")
resp = client.put(f'/api/merchant/orders/{order_id}/ready',
                  headers={'X-Auth-Token': merchant_token})
check("商家出餐（备餐中→待配送）", resp.get_json()['code'] == 200)

# ============================================================
# 第六步：骑手接单配送
# ============================================================
step("第六步：骑手取餐配送")

# 6.1 骑手查看待配送列表
resp = client.get('/api/rider/tasks/available',
                  headers={'X-Auth-Token': rider_token})
tasks = resp.get_json()['data']
check("骑手看到待配送订单", any(t['order_id'] == order_id for t in tasks))
print(f"     抢到配送任务：订单#{order_id}")

# 6.2 骑手接单
resp = client.post('/api/rider/tasks/accept',
                   headers={'X-Auth-Token': rider_token},
                   json={'order_id': order_id})
check("骑手接单成功", resp.get_json()['code'] == 200)

# 从任务列表取 delivery_id
resp = client.get('/api/rider/tasks',
                  headers={'X-Auth-Token': rider_token})
tasks = resp.get_json()['data']
delivery_task = next((t for t in tasks if t['order_id'] == order_id), None)
delivery_id = delivery_task['delivery_id']
print(f"     配送任务编号：#{delivery_id}")

# 6.3 骑手取餐
resp = client.put(f'/api/rider/tasks/{delivery_id}/pickup',
                  headers={'X-Auth-Token': rider_token})
check("骑手到店取餐", resp.get_json()['code'] == 200)
print(f"     🛵 骑手已取餐，正在配送中...")

# 6.4 骑手送达
resp = client.put(f'/api/rider/tasks/{delivery_id}/deliver',
                  headers={'X-Auth-Token': rider_token})
check("骑手送达", resp.get_json()['code'] == 200)

# ============================================================
# 第七步：用户确认收货 + 评价
# ============================================================
step("第七步：用户确认收货并评价")

# 7.1 确认收货
resp = client.put(f'/api/user/orders/{order_id}/confirm',
                  headers={'X-Auth-Token': user_token})
check("用户确认收货", resp.get_json()['code'] == 200)

# 7.2 用户查看订单最终状态
resp = client.get(f'/api/user/orders/{order_id}',
                  headers={'X-Auth-Token': user_token})
order = resp.get_json()['data']
check("订单状态→已完成", order['order_status'] == 5,
      f"当前状态码: {order['order_status']}")

# 7.3 提交评价
resp = client.post('/api/user/reviews',
                   headers={'X-Auth-Token': user_token},
                   json={
                       'order_id': order_id,
                       'dish_score': 5,
                       'delivery_score': 5,
                       'review_type': 1,
                       'content': '鱼香肉丝味道正宗，送餐速度很快！好评！'
                   })
check("提交5星好评", resp.get_json()['code'] == 200)
print(f"     评分：⭐⭐⭐⭐⭐")
print(f"     内容：鱼香肉丝味道正宗，送餐速度很快！好评！")

# ============================================================
# 第八步：商家查看评价
# ============================================================
step("第八步：商家查看评价并回复")

resp = client.get('/api/merchant/reviews',
                  headers={'X-Auth-Token': merchant_token})
reviews = resp.get_json()['data']
user_review = next((r for r in reviews if r.get('order_id') == order_id), None)
check("商家看到用户评价", user_review is not None)
if user_review:
    print(f"     用户评价：{user_review.get('content','')}  ★{user_review.get('rating',5)}")

    # 商家回复
    review_id = user_review['review_id']
    resp = client.put(f'/api/merchant/reviews/{review_id}/reply',
                       headers={'X-Auth-Token': merchant_token},
                       json={'merchant_reply': '感谢您的支持！欢迎再次光临川香小馆~'})
    check("商家回复评价", resp.get_json()['code'] == 200)

# ============================================================
# 第九步：商家查看经营数据
# ============================================================
step("第九步：商家查看经营统计")

resp = client.get('/api/merchant/statistics/orders',
                  headers={'X-Auth-Token': merchant_token})
data = resp.get_json().get('data', {})
summary = data.get('summary', {})
check("经营统计正常", summary.get('total_orders', 0) > 0)
print(f"     累计订单：{summary.get('total_orders', 0)} 单")
print(f"     累计营收：¥{summary.get('total_revenue', 0)}")
print(f"     已完成：{summary.get('completed_orders', 0)} 单")

# ============================================================
# 总结
# ============================================================
step("业务全流程完成")
print(f"""
  ┌─────────────────────────────────────────────────────────┐
  │                                                         │
  │   订单 #{order_id}  ¥{order_amount}                      │
  │                                                         │
  │   🧑 用户        →  下单  →  支付  →  确认收货  →  评价     │
  │   🏪 川香小馆     →  接单  →  出餐  →  回复评价             │
  │   🛵 骑手        →  抢单  →  取餐  →  送达                 │
  │                                                         │
  │   状态流转：待支付 → 待接单 → 备餐中 → 待配送 → 配送中 → 已完成  │
  │                                                         │
  └─────────────────────────────────────────────────────────┘
""")
print(f"  测试结果：通过 {PASS} | 失败 {FAIL} | 总计 {PASS+FAIL}")
if FAIL == 0:
    print(f"  🎉 全部通过！业务流程验证完成。")
