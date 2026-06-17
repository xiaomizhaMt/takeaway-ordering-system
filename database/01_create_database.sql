-- =============================================
-- 外卖订餐管理系统数据库脚本（收敛版：8张表）
-- 适用数据库：MySQL 8.0+
-- 说明：按"建库 -> 建表 -> 外键 -> 索引"顺序组织，便于团队协作查看
-- =============================================

-- =============================================
-- 1. 创建数据库
-- =============================================
DROP DATABASE IF EXISTS takeaway_ordering_system;
CREATE DATABASE takeaway_ordering_system
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;

USE takeaway_ordering_system;

-- =============================================
-- 2. 创建用户表 User
-- =============================================
DROP TABLE IF EXISTS `User`;
CREATE TABLE `User` (
  `user_id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键，用户编号',
  `username` VARCHAR(50) NOT NULL COMMENT '登录账号',
  `password` VARCHAR(100) NOT NULL COMMENT '登录密码',
  `pay_password` VARCHAR(100) NULL COMMENT '支付密码（明文）',
  `real_name` VARCHAR(30) NULL COMMENT '用户姓名',
  `phone` VARCHAR(20) NOT NULL COMMENT '手机号',
  `default_receiver` VARCHAR(30) NULL COMMENT '默认收货人',
  `default_phone` VARCHAR(20) NULL COMMENT '默认收货联系电话',
  `default_address` VARCHAR(200) NULL COMMENT '默认收货地址',
  `account_status` TINYINT NOT NULL DEFAULT 1 COMMENT '账号状态：1正常，0禁用',
  `wallet_balance` DECIMAL(10,2) NOT NULL DEFAULT 0.00 COMMENT '钱包余额',
  `register_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '注册时间',
  PRIMARY KEY (`user_id`),
  UNIQUE KEY `uk_user_username` (`username`),
  UNIQUE KEY `uk_user_phone` (`phone`),
  CONSTRAINT `chk_user_account_status` CHECK (`account_status` IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户表';

-- =============================================
-- 3. 创建商家表 Merchant
-- =============================================
DROP TABLE IF EXISTS `Merchant`;
CREATE TABLE `Merchant` (
  `merchant_id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键，商家编号',
  `account` VARCHAR(50) NOT NULL COMMENT '商家账号',
  `password` VARCHAR(100) NOT NULL COMMENT '登录密码',
  `shop_name` VARCHAR(80) NOT NULL COMMENT '店铺名称',
  `contact_name` VARCHAR(30) NULL COMMENT '联系人',
  `contact_phone` VARCHAR(20) NOT NULL COMMENT '联系电话',
  `shop_address` VARCHAR(200) NOT NULL COMMENT '店铺地址',
  `shop_image_url` VARCHAR(255) NULL COMMENT '店铺图片URL',
  `merchant_type` VARCHAR(20) NOT NULL DEFAULT '其他' COMMENT '商家类型',
  `business_hours` VARCHAR(100) NULL COMMENT '营业时段，如09:00-21:00',
  `shop_desc` VARCHAR(300) NULL COMMENT '店铺简介',
  `business_status` TINYINT NOT NULL DEFAULT 1 COMMENT '营业状态：1营业，0歇业',
  `audit_status` TINYINT NOT NULL DEFAULT 0 COMMENT '审核状态：0待审，1通过，2驳回',
  `audit_time` DATETIME NULL COMMENT '审核时间',
  `wallet_balance` DECIMAL(10,2) NOT NULL DEFAULT 0.00 COMMENT '钱包余额',
  PRIMARY KEY (`merchant_id`),
  UNIQUE KEY `uk_merchant_account` (`account`),
  CONSTRAINT `chk_merchant_business_status` CHECK (`business_status` IN (0, 1)),
  CONSTRAINT `chk_merchant_audit_status` CHECK (`audit_status` IN (0, 1, 2)),
  CONSTRAINT `chk_merchant_type` CHECK (`merchant_type` IN ('奶茶咖啡', '汉堡快餐', '米粉汤面', '烧烤小吃', '粥食甜品', '热炒正餐', '其他'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='商家表';

-- =============================================
-- 4. 创建配送员表 Rider
-- =============================================
DROP TABLE IF EXISTS `Rider`;
CREATE TABLE `Rider` (
  `rider_id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键，配送员编号',
  `account` VARCHAR(50) NOT NULL COMMENT '配送员账号',
  `password` VARCHAR(100) NOT NULL COMMENT '登录密码',
  `rider_name` VARCHAR(30) NOT NULL COMMENT '配送员姓名',
  `phone` VARCHAR(20) NOT NULL COMMENT '手机号',
  `id_card` VARCHAR(30) NOT NULL COMMENT '身份证号',
  `work_status` TINYINT NOT NULL DEFAULT 0 COMMENT '工作状态：0离线，1在线，2忙碌',
  `audit_status` TINYINT NOT NULL DEFAULT 0 COMMENT '审核状态：0待审，1通过，2驳回',
  `audit_time` DATETIME NULL COMMENT '审核时间',
  `wallet_balance` DECIMAL(10,2) NOT NULL DEFAULT 0.00 COMMENT '钱包余额',
  `register_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '注册时间',
  PRIMARY KEY (`rider_id`),
  UNIQUE KEY `uk_rider_account` (`account`),
  UNIQUE KEY `uk_rider_phone` (`phone`),
  UNIQUE KEY `uk_rider_id_card` (`id_card`),
  CONSTRAINT `chk_rider_work_status` CHECK (`work_status` IN (0, 1, 2)),
  CONSTRAINT `chk_rider_audit_status` CHECK (`audit_status` IN (0, 1, 2))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='配送员表';

-- =============================================
-- 5. 创建菜品表 Dish
-- =============================================
DROP TABLE IF EXISTS `Dish`;
CREATE TABLE `Dish` (
  `dish_id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键，菜品编号',
  `merchant_id` BIGINT NOT NULL COMMENT '外键，所属商家',
  `category_name` VARCHAR(50) NULL COMMENT '菜品分类名称',
  `image_url` VARCHAR(255) NULL COMMENT '菜品图片URL',
  `dish_name` VARCHAR(80) NOT NULL COMMENT '菜品名称',
  `dish_desc` VARCHAR(300) NULL COMMENT '菜品详情',
  `price` DECIMAL(10,2) NOT NULL COMMENT '菜品价格',
  `specification` VARCHAR(100) NULL COMMENT '规格',
  `stock` INT NOT NULL COMMENT '库存数量',
  `warning_stock` INT NULL COMMENT '库存预警阈值',
  `sale_status` TINYINT NOT NULL DEFAULT 1 COMMENT '上架状态：1上架，0下架',
  `sales_count` INT NOT NULL DEFAULT 0 COMMENT '销量',
  PRIMARY KEY (`dish_id`),
  CONSTRAINT `chk_dish_price` CHECK (`price` >= 0),
  CONSTRAINT `chk_dish_stock` CHECK (`stock` >= 0),
  CONSTRAINT `chk_dish_warning_stock` CHECK (`warning_stock` IS NULL OR `warning_stock` >= 0),
  CONSTRAINT `chk_dish_sale_status` CHECK (`sale_status` IN (0, 1)),
  CONSTRAINT `chk_dish_category` CHECK (`category_name` IN ('盖饭', '甜品', '水果', '小吃', '饮品', '主食', '夜宵', '粥粉面')),
  CONSTRAINT `chk_dish_sales_count` CHECK (`sales_count` >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='菜品表';

-- =============================================
-- 6. 创建订单表 Order_Info
-- =============================================
DROP TABLE IF EXISTS `Order_Info`;
CREATE TABLE `Order_Info` (
  `order_id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键，订单编号',
  `user_id` BIGINT NOT NULL COMMENT '外键，用户编号',
  `merchant_id` BIGINT NOT NULL COMMENT '外键，商家编号',
  `rider_id` BIGINT NULL COMMENT '外键，配送员编号；未分配时为空',
  `receiver_name` VARCHAR(30) NOT NULL COMMENT '收货人快照',
  `receiver_phone` VARCHAR(20) NOT NULL COMMENT '收货电话快照',
  `receiver_address` VARCHAR(200) NOT NULL COMMENT '收货地址快照',
  `order_amount` DECIMAL(10,2) NOT NULL COMMENT '订单总金额',
  `delivery_fee` DECIMAL(10,2) NOT NULL DEFAULT 0.00 COMMENT '配送费',
  `tableware_count` INT NOT NULL DEFAULT 1 COMMENT '餐具份数',
  `pay_method` VARCHAR(20) NULL COMMENT '支付方式：wechat微信，alipay支付宝，bank_card银行卡，cash货到付款，wallet我的钱包',
  `pay_status` TINYINT NOT NULL DEFAULT 0 COMMENT '支付状态：0未支付，1支付成功，2支付失败，3已退款',
  `pay_time` DATETIME NULL COMMENT '支付时间',
  `order_status` TINYINT NOT NULL DEFAULT 0 COMMENT '订单状态：0待支付，1待接单，2备餐中，3已出餐，4配送中，5已完成，6已取消，7异常',
  `after_sale_status` TINYINT NOT NULL DEFAULT 0 COMMENT '售后状态：0无，1申请中，2已处理',

  `after_sale_apply_time` DATETIME NULL COMMENT '售后申请时间',
  `after_sale_reason` VARCHAR(500) NULL COMMENT '售后申请原因',
  `after_sale_result` VARCHAR(500) NULL COMMENT '售后/监管处理结果',
  `after_sale_handle_time` DATETIME NULL COMMENT '售后处理时间',
  `refund_amount` DECIMAL(10,2) NOT NULL DEFAULT 0.00 COMMENT '实际退款金额',
  `refund_type` TINYINT NOT NULL DEFAULT 0 COMMENT '退款类型：0无，1全额退款，2部分退款50%',
  `refund_reason` VARCHAR(300) NULL COMMENT '退款原因',
  `refund_time` DATETIME NULL COMMENT '退款处理时间',
  `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '下单时间',
  `accept_time` DATETIME NULL COMMENT '商家接单时间',
  `meal_ready_time` DATETIME NULL COMMENT '出餐时间',
  `finish_time` DATETIME NULL COMMENT '完成时间',
  PRIMARY KEY (`order_id`),
  CONSTRAINT `chk_order_amount` CHECK (`order_amount` >= 0),
  CONSTRAINT `chk_order_delivery_fee` CHECK (`delivery_fee` >= 0),
  CONSTRAINT `chk_order_tableware_count` CHECK (`tableware_count` >= 1),
  CONSTRAINT `chk_order_pay_status` CHECK (`pay_status` IN (0, 1, 2, 3)),
  CONSTRAINT `chk_order_status` CHECK (`order_status` IN (0, 1, 2, 3, 4, 5, 6, 7)),
  CONSTRAINT `chk_order_after_sale_status` CHECK (`after_sale_status` IN (0, 1, 2)),
  CONSTRAINT `chk_order_refund_type` CHECK (`refund_type` IN (0, 1, 2)),
  CONSTRAINT `chk_order_refund_amount` CHECK (`refund_amount` >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='订单表';

-- =============================================
-- 7. 创建订单明细表 Order_Item
-- =============================================
DROP TABLE IF EXISTS `Order_Item`;
CREATE TABLE `Order_Item` (
  `order_item_id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键，订单明细编号',
  `order_id` BIGINT NOT NULL COMMENT '外键，订单编号',
  `dish_id` BIGINT NOT NULL COMMENT '外键，菜品编号',
  `quantity` INT NOT NULL COMMENT '购买数量',
  `unit_price` DECIMAL(10,2) NOT NULL COMMENT '下单时单价',
  `specification` VARCHAR(100) NULL COMMENT '下单时规格',
  `subtotal` DECIMAL(10,2) NOT NULL COMMENT '明细小计',
  PRIMARY KEY (`order_item_id`),
  CONSTRAINT `chk_order_item_quantity` CHECK (`quantity` > 0),
  CONSTRAINT `chk_order_item_unit_price` CHECK (`unit_price` >= 0),
  CONSTRAINT `chk_order_item_subtotal` CHECK (`subtotal` >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='订单明细表';

-- =============================================
-- 8. 创建配送表 Delivery
-- =============================================
DROP TABLE IF EXISTS `Delivery`;
CREATE TABLE `Delivery` (
  `delivery_id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键，配送编号',
  `order_id` BIGINT NOT NULL COMMENT '外键，订单编号，唯一',
  `rider_id` BIGINT NOT NULL COMMENT '外键，配送员编号',
  `delivery_status` TINYINT NOT NULL DEFAULT 0 COMMENT '配送状态：0待取餐，1配送中，2已送达，3异常',
  `accept_time` DATETIME NULL COMMENT '配送员接单时间',
  `pickup_time` DATETIME NULL COMMENT '取餐时间',
  `delivered_time` DATETIME NULL COMMENT '送达时间',
  `exception_note` VARCHAR(300) NULL COMMENT '异常说明',
  `delivery_income` DECIMAL(10,2) NULL COMMENT '配送收益',
  PRIMARY KEY (`delivery_id`),
  UNIQUE KEY `uk_delivery_order_id` (`order_id`),
  CONSTRAINT `chk_delivery_status` CHECK (`delivery_status` IN (0, 1, 2, 3)),
  CONSTRAINT `chk_delivery_income` CHECK (`delivery_income` IS NULL OR `delivery_income` >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='配送表';

-- =============================================
-- 9. 创建评价表 Review
-- =============================================
DROP TABLE IF EXISTS `Review`;
CREATE TABLE `Review` (
  `review_id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键，评价编号',
  `order_id` BIGINT NOT NULL COMMENT '外键，订单编号',
  `user_id` BIGINT NOT NULL COMMENT '外键，用户编号',
  `merchant_id` BIGINT NOT NULL COMMENT '外键，商家编号',
  `rider_id` BIGINT NULL COMMENT '外键，配送员编号',
  `dish_id` BIGINT NULL COMMENT '单品评价关联菜品；为空表示订单整体评价',
  `dish_score` TINYINT NULL COMMENT '菜品评分',
  `delivery_score` TINYINT NULL COMMENT '配送评分',
  `review_type` TINYINT NOT NULL DEFAULT 1 COMMENT '评价类型：1普通，2投诉',

  `complaint_status` TINYINT NOT NULL DEFAULT 0 COMMENT '投诉审核状态：0无，1待审核，2通过，3驳回',
  `complaint_refund_type` TINYINT NOT NULL DEFAULT 0 COMMENT '投诉退款结论：0无，1全额，2部分50%',
  `complaint_handle_note` VARCHAR(500) NULL COMMENT '投诉审核备注',
  `complaint_handle_time` DATETIME NULL COMMENT '投诉审核时间',
  `content` VARCHAR(500) NULL COMMENT '评价内容',
  `merchant_reply` VARCHAR(500) NULL COMMENT '商家回复',
  `review_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '评价时间',
  PRIMARY KEY (`review_id`),
  KEY `idx_review_order_dish` (`order_id`, `dish_id`),
  CONSTRAINT `chk_review_dish_score` CHECK (`dish_score` IS NULL OR `dish_score` BETWEEN 1 AND 5),
  CONSTRAINT `chk_review_delivery_score` CHECK (`delivery_score` IS NULL OR `delivery_score` BETWEEN 1 AND 5),
  CONSTRAINT `chk_review_type` CHECK (`review_type` IN (1, 2)),
  CONSTRAINT `chk_review_complaint_status` CHECK (`complaint_status` IN (0, 1, 2, 3)),
  CONSTRAINT `chk_review_complaint_refund_type` CHECK (`complaint_refund_type` IN (0, 1, 2))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='评价表';

-- =============================================
-- 10. 创建钱包流水表 Wallet_Transaction
-- =============================================
DROP TABLE IF EXISTS `Wallet_Transaction`;
CREATE TABLE `Wallet_Transaction` (
  `transaction_id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键，钱包流水编号',
  `owner_type` VARCHAR(20) NOT NULL COMMENT '钱包归属：user/merchant/rider',
  `owner_id` BIGINT NOT NULL COMMENT '归属主体ID',
  `transaction_type` VARCHAR(30) NOT NULL COMMENT '流水类型：recharge/payment/refund/merchant_income/rider_income/withdraw',
  `amount` DECIMAL(10,2) NOT NULL COMMENT '变动金额：收入为正，支出为负',
  `balance_after` DECIMAL(10,2) NOT NULL COMMENT '变动后余额',
  `related_order_id` BIGINT NULL COMMENT '关联订单',
  `related_delivery_id` BIGINT NULL COMMENT '关联配送',
  `pay_channel` VARCHAR(20) NULL COMMENT '充值或提现渠道',
  `remark` VARCHAR(300) NULL COMMENT '备注',
  `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`transaction_id`),
  CONSTRAINT `chk_wallet_owner_type` CHECK (`owner_type` IN ('user', 'merchant', 'rider')),
  CONSTRAINT `chk_wallet_amount` CHECK (`amount` <> 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='钱包资金流水表';

-- =============================================
-- 11. 添加外键约束
-- 说明：先建表后统一加外键，便于阅读和维护
-- =============================================
ALTER TABLE `Dish`
  ADD CONSTRAINT `fk_dish_merchant`
    FOREIGN KEY (`merchant_id`) REFERENCES `Merchant` (`merchant_id`)
    ON UPDATE CASCADE
    ON DELETE RESTRICT;

ALTER TABLE `Order_Info`
  ADD CONSTRAINT `fk_order_user`
    FOREIGN KEY (`user_id`) REFERENCES `User` (`user_id`)
    ON UPDATE CASCADE
    ON DELETE RESTRICT,
  ADD CONSTRAINT `fk_order_merchant`
    FOREIGN KEY (`merchant_id`) REFERENCES `Merchant` (`merchant_id`)
    ON UPDATE CASCADE
    ON DELETE RESTRICT,
  ADD CONSTRAINT `fk_order_rider`
    FOREIGN KEY (`rider_id`) REFERENCES `Rider` (`rider_id`)
    ON UPDATE CASCADE
    ON DELETE SET NULL;

ALTER TABLE `Order_Item`
  ADD CONSTRAINT `fk_order_item_order`
    FOREIGN KEY (`order_id`) REFERENCES `Order_Info` (`order_id`)
    ON UPDATE CASCADE
    ON DELETE RESTRICT,
  ADD CONSTRAINT `fk_order_item_dish`
    FOREIGN KEY (`dish_id`) REFERENCES `Dish` (`dish_id`)
    ON UPDATE CASCADE
    ON DELETE RESTRICT;

ALTER TABLE `Delivery`
  ADD CONSTRAINT `fk_delivery_order`
    FOREIGN KEY (`order_id`) REFERENCES `Order_Info` (`order_id`)
    ON UPDATE CASCADE
    ON DELETE RESTRICT,
  ADD CONSTRAINT `fk_delivery_rider`
    FOREIGN KEY (`rider_id`) REFERENCES `Rider` (`rider_id`)
    ON UPDATE CASCADE
    ON DELETE RESTRICT;

ALTER TABLE `Review`
  ADD CONSTRAINT `fk_review_order`
    FOREIGN KEY (`order_id`) REFERENCES `Order_Info` (`order_id`)
    ON UPDATE CASCADE
    ON DELETE RESTRICT,
  ADD CONSTRAINT `fk_review_user`
    FOREIGN KEY (`user_id`) REFERENCES `User` (`user_id`)
    ON UPDATE CASCADE
    ON DELETE RESTRICT,
  ADD CONSTRAINT `fk_review_merchant`
    FOREIGN KEY (`merchant_id`) REFERENCES `Merchant` (`merchant_id`)
    ON UPDATE CASCADE
    ON DELETE RESTRICT,
  ADD CONSTRAINT `fk_review_rider`
    FOREIGN KEY (`rider_id`) REFERENCES `Rider` (`rider_id`)
    ON UPDATE CASCADE
    ON DELETE SET NULL,
  ADD CONSTRAINT `fk_review_dish`
    FOREIGN KEY (`dish_id`) REFERENCES `Dish` (`dish_id`)
    ON UPDATE CASCADE
    ON DELETE SET NULL;

-- =============================================
-- 12. 添加普通索引
-- =============================================
CREATE INDEX `idx_merchant_status` ON `Merchant` (`business_status`, `audit_status`);
CREATE INDEX `idx_dish_merchant_category` ON `Dish` (`merchant_id`, `category_name`, `sale_status`);
CREATE INDEX `idx_order_user_time` ON `Order_Info` (`user_id`, `create_time`);
CREATE INDEX `idx_order_merchant_time` ON `Order_Info` (`merchant_id`, `create_time`);
CREATE INDEX `idx_order_status_time` ON `Order_Info` (`order_status`, `create_time`);
CREATE INDEX `idx_delivery_status_rider` ON `Delivery` (`delivery_status`, `rider_id`);
CREATE INDEX `idx_review_merchant_time` ON `Review` (`merchant_id`, `review_time`);
CREATE INDEX `idx_review_dish_time` ON `Review` (`dish_id`, `review_time`);
CREATE INDEX `idx_order_after_sale_refund` ON `Order_Info` (`after_sale_status`, `refund_type`, `refund_time`);
CREATE INDEX `idx_review_complaint_status` ON `Review` (`review_type`, `complaint_status`, `review_time`);
CREATE INDEX `idx_wallet_owner_time` ON `Wallet_Transaction` (`owner_type`, `owner_id`, `create_time`);
CREATE INDEX `idx_wallet_order` ON `Wallet_Transaction` (`related_order_id`);
CREATE INDEX `idx_wallet_delivery` ON `Wallet_Transaction` (`related_delivery_id`);
