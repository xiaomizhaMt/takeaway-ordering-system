-- =============================================
-- 外卖订餐管理系统核心查询精简版 SQL
-- 用途：仅保留支撑主流程的最小查询集合，适合前后端快速联调
-- 主流程：用户下单点餐 -> 商家接单备餐 -> 配送员配送 -> 用户查看订单/评价
-- =============================================

USE takeaway_ordering_system;

-- =========================================================
-- 一、用户端核心查询
-- =========================================================

-- 1. 用户查看可点餐商家列表
SELECT
  merchant_id,
  shop_name,
  contact_phone,
  shop_address,
  business_hours,
  shop_desc
FROM `Merchant`
WHERE business_status = 1
  AND audit_status = 1
ORDER BY merchant_id;

-- 2. 用户按商家查看菜品列表
-- 参数：merchant_id
SELECT
  dish_id,
  merchant_id,
  category_name,
  dish_name,
  dish_desc,
  image_url,
  price,
  specification,
  stock,
  sales_count
FROM `Dish`
WHERE merchant_id = 1
  AND sale_status = 1
ORDER BY category_name, dish_id;

-- 3. 用户查询自己的订单列表
-- 参数：user_id
SELECT
  o.order_id,
  m.shop_name,
  o.order_amount,
  o.delivery_fee,
  o.pay_status,
  o.order_status,
  o.create_time,
  o.finish_time
FROM `Order_Info` o
JOIN `Merchant` m ON o.merchant_id = m.merchant_id
WHERE o.user_id = 1
ORDER BY o.create_time DESC;

-- 4. 用户查询订单详情（基本信息）
-- 参数：order_id
SELECT
  o.order_id,
  u.real_name AS user_name,
  m.shop_name,
  r.rider_name,
  o.receiver_name,
  o.receiver_phone,
  o.receiver_address,
  o.order_amount,
  o.delivery_fee,
  o.pay_status,
  o.order_status,
  o.create_time,
  o.accept_time,
  o.meal_ready_time,
  o.finish_time
FROM `Order_Info` o
JOIN `User` u ON o.user_id = u.user_id
JOIN `Merchant` m ON o.merchant_id = m.merchant_id
LEFT JOIN `Rider` r ON o.rider_id = r.rider_id
WHERE o.order_id = 1;

-- 5. 用户查询订单菜品明细
-- 参数：order_id
SELECT
  oi.order_item_id,
  d.dish_name,
  oi.specification,
  oi.quantity,
  oi.unit_price,
  oi.subtotal
FROM `Order_Item` oi
JOIN `Dish` d ON oi.dish_id = d.dish_id
WHERE oi.order_id = 1
ORDER BY oi.order_item_id;

-- =========================================================
-- 二、商家端核心查询
-- =========================================================

-- 6. 商家查询本店订单列表
-- 参数：merchant_id
SELECT
  o.order_id,
  u.real_name AS customer_name,
  o.receiver_phone,
  o.order_amount,
  o.pay_status,
  o.order_status,
  o.create_time,
  o.accept_time,
  o.meal_ready_time
FROM `Order_Info` o
JOIN `User` u ON o.user_id = u.user_id
WHERE o.merchant_id = 1
ORDER BY o.create_time DESC;

-- 7. 商家按状态筛选订单
-- 参数：merchant_id, order_status
SELECT
  o.order_id,
  u.real_name AS customer_name,
  o.order_amount,
  o.order_status,
  o.create_time,
  o.accept_time
FROM `Order_Info` o
JOIN `User` u ON o.user_id = u.user_id
WHERE o.merchant_id = 1
  AND o.order_status = 1
ORDER BY o.create_time DESC;

-- 8. 商家查询订单明细
-- 参数：order_id
SELECT
  oi.order_item_id,
  d.dish_name,
  oi.specification,
  oi.quantity,
  oi.unit_price,
  oi.subtotal
FROM `Order_Item` oi
JOIN `Dish` d ON oi.dish_id = d.dish_id
WHERE oi.order_id = 1
ORDER BY oi.order_item_id;

-- 9. 商家查询本店评价列表
-- 参数：merchant_id
SELECT
  rv.review_id,
  rv.order_id,
  u.real_name AS user_name,
  rv.dish_score,
  rv.delivery_score,
  rv.content,
  rv.merchant_reply,
  rv.review_time
FROM `Review` rv
JOIN `User` u ON rv.user_id = u.user_id
WHERE rv.merchant_id = 1
ORDER BY rv.review_time DESC;

-- 10. 商家查询本店菜品列表
-- 参数：merchant_id
SELECT
  dish_id,
  category_name,
  dish_name,
  price,
  specification,
  stock,
  warning_stock,
  sale_status,
  sales_count
FROM `Dish`
WHERE merchant_id = 1
ORDER BY category_name, dish_id;

-- =========================================================
-- 三、配送员端核心查询
-- =========================================================

-- 11. 配送员查询自己的配送任务列表
-- 参数：rider_id
SELECT
  dly.delivery_id,
  dly.order_id,
  m.shop_name,
  u.real_name AS customer_name,
  o.receiver_phone,
  o.receiver_address,
  dly.delivery_status,
  dly.accept_time,
  dly.pickup_time,
  dly.delivered_time
FROM `Delivery` dly
JOIN `Order_Info` o ON dly.order_id = o.order_id
JOIN `Merchant` m ON o.merchant_id = m.merchant_id
JOIN `User` u ON o.user_id = u.user_id
WHERE dly.rider_id = 1
ORDER BY dly.accept_time DESC;

-- 12. 配送员查看配送详情
-- 参数：delivery_id
SELECT
  dly.delivery_id,
  dly.order_id,
  r.rider_name,
  m.shop_name,
  u.real_name AS customer_name,
  o.receiver_name,
  o.receiver_phone,
  o.receiver_address,
  dly.delivery_status,
  dly.accept_time,
  dly.pickup_time,
  dly.delivered_time,
  dly.exception_note,
  dly.delivery_income
FROM `Delivery` dly
JOIN `Rider` r ON dly.rider_id = r.rider_id
JOIN `Order_Info` o ON dly.order_id = o.order_id
JOIN `Merchant` m ON o.merchant_id = m.merchant_id
JOIN `User` u ON o.user_id = u.user_id
WHERE dly.delivery_id = 1;

-- =========================================================
-- 四、平台/管理员端核心查询
-- =========================================================

-- 13. 平台查询全部订单列表
SELECT
  o.order_id,
  u.username,
  m.shop_name,
  r.rider_name,
  o.order_amount,
  o.pay_status,
  o.order_status,
  o.create_time
FROM `Order_Info` o
JOIN `User` u ON o.user_id = u.user_id
JOIN `Merchant` m ON o.merchant_id = m.merchant_id
LEFT JOIN `Rider` r ON o.rider_id = r.rider_id
ORDER BY o.create_time DESC;

-- 14. 平台查询异常订单
-- 说明：订单状态为7，或配送状态为3，视为异常订单
SELECT
  o.order_id,
  u.username,
  m.shop_name,
  r.rider_name,
  o.order_status,
  dly.delivery_status,
  dly.exception_note,
  o.create_time
FROM `Order_Info` o
JOIN `User` u ON o.user_id = u.user_id
JOIN `Merchant` m ON o.merchant_id = m.merchant_id
LEFT JOIN `Rider` r ON o.rider_id = r.rider_id
LEFT JOIN `Delivery` dly ON o.order_id = dly.order_id
WHERE o.order_status = 7
   OR dly.delivery_status = 3
ORDER BY o.create_time DESC;

-- 15. 订单金额一致性校验
-- 规则：订单总金额 = 明细小计汇总 + 配送费
SELECT
  o.order_id,
  SUM(oi.subtotal) AS item_total,
  o.delivery_fee,
  o.order_amount,
  CASE
    WHEN SUM(oi.subtotal) + o.delivery_fee = o.order_amount THEN '正确'
    ELSE '错误'
  END AS amount_check
FROM `Order_Info` o
JOIN `Order_Item` oi ON o.order_id = oi.order_id
GROUP BY o.order_id, o.delivery_fee, o.order_amount
ORDER BY o.order_id;

-- =========================================================
-- 五、补充说明（给队友看）
-- =========================================================
-- 1）这份文件是“精简版”，只保留最核心的查询。
-- 2）示例中的固定条件（如 user_id = 1、merchant_id = 1）在接后端接口时改成传参即可。
-- 3）如果后续要做更完整的后台或统计功能，可再参考《外卖订餐管理系统_常用业务查询.sql》。