# Takeaway Ordering Management System

English summary of the main Chinese README. The primary document is `README.md`.

## Overview

This project is a takeaway ordering management system built with Python Flask, MySQL, and vanilla HTML/CSS/JavaScript.

Core flow:

```text
User orders and pays -> merchant accepts and prepares -> rider delivers -> user confirms and reviews -> admin supervises refunds and complaints
```

Roles:

| Role | Main Capabilities |
|------|-------------------|
| User | Browse merchants and dishes, manage profile/address, cart checkout, payment, wallet, orders, reviews, complaints |
| Merchant | Shop settings, map address, shop image, dish management, orders, reviews, statistics, wallet |
| Rider | Available tasks, task acceptance, pickup/delivery, exception reporting, income wallet |
| Admin | User/merchant/rider management, audits, order supervision, complaints, refunds, platform statistics |

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3 + Flask |
| Database | MySQL 8.0+ |
| Driver | PyMySQL |
| Frontend | HTML5 + CSS3 + Vanilla JavaScript |
| Auth | Token + Flask Session compatibility |
| Entry | `run.py` |
| Database migration | `init_db.py` |

## Project Structure

```text
run.py
init_db.py
requirements.txt
backend/
  app.py
  config.py
  db/db_helper.py
  routes/
    auth_routes.py
    user_routes.py
    merchant_routes.py
    rider_routes.py
    admin_routes.py
  services/
  utils/
frontend/
  index.html
  register.html
  css/style.css
  js/api.js
  js/map-config.js
  js/map-picker.js
  pages/
    user/
    merchant/
    rider/
    admin/
database/
  01_create_database.sql
  03_insert_sample_data.sql
```

## Database

Database name:

```text
takeaway_ordering_system
```

Main tables:

| Table | Purpose |
|-------|---------|
| `User` | User account, profile, default address, wallet |
| `Merchant` | Shop information, business/audit status, map coordinates, shop image, wallet |
| `Rider` | Rider account, work/audit status, wallet |
| `Dish` | Dish details, image, price, stock, sales |
| `Order_Info` | Order master data, payment, delivery fee, status, address snapshots |
| `Order_Item` | Order line items |
| `Delivery` | Rider delivery lifecycle and income |
| `Review` | Reviews, complaints, merchant replies |
| `Wallet_Transaction` | Wallet ledger for users, merchants, and riders |

Location fields are stored in `User`, `Merchant`, and `Order_Info`. AMap is used only for address picking/searching; delivery fee and rider sorting use stored coordinates.

## AMap Configuration

Configure:

```text
frontend/js/map-config.js
```

The key must be an AMap `Web JS API` key with a matching security JS code:

```javascript
window.MAP_CONFIG = window.MAP_CONFIG || {
  amapKey: 'your_amap_js_api_key',
  securityJsCode: 'your_amap_security_js_code'
};
```

If AMap is missing or fails to load, address fields still work as plain text inputs.

The committed `frontend/js/map-config.js` uses empty placeholders so real AMap keys are not uploaded to GitHub. Fill real values only in your local or deployed environment.

## Delivery Fee And Distance Rules

Delivery fee is calculated from merchant address to receiver address:

| Distance | Fee |
|----------|-----|
| <= 3 km | 3 yuan |
| > 3 km | 3 yuan + extra kilometers * 0.5 yuan |

If coordinates are missing, the fallback delivery fee is 3 yuan.

Distance restrictions:

- Users cannot add a merchant's dish to cart when the merchant is more than 100 km from the saved receiver address.
- The backend also rejects order creation when known merchant/receiver coordinates exceed 100 km.
- Rider available-task list hides orders over 100 km.
- Riders cannot accept orders over 50 km.
- Each rider can hold at most 3 unfinished tasks.

## Cart And Orders

- The cart page shows only selected cart items.
- Users can increase/decrease selected item quantities.
- Items from multiple merchants can be paid together.
- The system creates one order per merchant group.
- Batch payment uses `PUT /api/user/orders/pay-batch`.
- Each merchant group independently displays item subtotal, delivery fee, distance, and subtotal.

## Quick Start

1. Configure database connection.

`backend/config.py` is committed and reads values from environment variables. Do not hard-code real passwords in this file.

PowerShell example:

```powershell
$env:DB_HOST="localhost"
$env:DB_PORT="3306"
$env:DB_USER="root"
$env:DB_PASSWORD="your_mysql_password"
$env:DB_NAME="takeaway_ordering_system"
$env:APP_SECRET_KEY="change-me"
```

Linux / macOS example:

```bash
export DB_HOST=localhost
export DB_PORT=3306
export DB_USER=root
export DB_PASSWORD='your_mysql_password'
export DB_NAME=takeaway_ordering_system
export APP_SECRET_KEY='change-me'
```

Alternatively, copy `backend/config_local.example.py` to `backend/config_local.py` and fill real values there. `backend/config_local.py` is ignored by Git.

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Initialize or migrate database:

```bash
python init_db.py
```

Default mode is a safe migration: it creates missing objects and columns without clearing existing data.

Only use reset mode for a disposable demo database:

```bash
python init_db.py --reset
```

`--reset` deletes and recreates the database.

4. Start the app:

```bash
python run.py
```

Open:

```text
http://127.0.0.1:5000
```

## GitHub Remote

GitHub repository:

```text
https://github.com/xiaomizhaMt/database-course-design
```

The local repository keeps Gitee as `origin` and uses `github` for GitHub:

```bash
git remote -v
git push github codex/github-clean-upload:master
```

The GitHub upload was created from a clean initial commit instead of the old Gitee history, so old token/cache/API-key history is not copied to GitHub.

## Test Accounts

| Role | Username | Password |
|------|----------|----------|
| Admin | `admin` | `admin123` |
| User | `zhangsan` | `123456` |
| User | `lisi` | `123456` |
| User | `wangwu` | `123456` |
| Merchant | `merchant001` | `123456` |
| Merchant | `merchant002` | `123456` |
| Merchant | `merchant003` | `123456` |
| Rider | `rider001` | `123456` |
| Rider | `rider002` | `123456` |

Example users use `123456` as the payment password.

## Main API Groups

Authentication:

```http
POST /api/auth/login
POST /api/auth/register
POST /api/auth/logout
GET  /api/auth/current_user
POST /api/auth/token_login
```

User:

```http
GET    /api/user/profile
PUT    /api/user/profile
GET    /api/user/merchants
GET    /api/user/dishes
GET    /api/user/cart
POST   /api/user/cart/items
POST   /api/user/orders
PUT    /api/user/orders/pay-batch
GET    /api/user/orders
GET    /api/user/merchants/<merchant_id>/reviews
GET    /api/user/dishes/<dish_id>/reviews
GET    /api/user/wallet
POST   /api/user/wallet/recharge
GET    /api/user/reviews
POST   /api/user/reviews
```

Merchant:

```http
GET  /api/merchant/shop
PUT  /api/merchant/shop
GET  /api/merchant/dishes
POST /api/merchant/dishes
POST /api/merchant/dishes/<dish_id>/image
GET  /api/merchant/orders
GET  /api/merchant/reviews
GET  /api/merchant/wallet
POST /api/merchant/wallet/withdraw
```

Rider:

```http
GET  /api/rider/tasks/available
POST /api/rider/tasks/accept
PUT  /api/rider/tasks/<delivery_id>/pickup
PUT  /api/rider/tasks/<delivery_id>/deliver
PUT  /api/rider/tasks/<delivery_id>/exception
GET  /api/rider/income
GET  /api/rider/wallet
POST /api/rider/wallet/withdraw
```

Admin:

```http
GET /api/admin/users
GET /api/admin/merchants
GET /api/admin/riders
GET /api/admin/orders
GET /api/admin/orders/supervision
GET /api/admin/complaints
PUT /api/admin/complaints/<review_id>/handle
GET /api/admin/statistics/overview
```

## Notes

- This is a course-design/demo system using Flask's development server.
- Payment is simulated; no real third-party payment provider is integrated.
- `python init_db.py` is safe for existing data; `python init_db.py --reset` is destructive.
- The Chinese README contains the full detailed walkthrough and test checklist.
