const API_BASE = '/api';
const TOKEN_KEY_PREFIX = 'token_';

// 每个角色使用独立 token key，避免同一浏览器多标签登录不同账号时互相覆盖。
function getTokenKey(role) {
  return TOKEN_KEY_PREFIX + role;
}

function saveToken(role, token) {
  if (!token) return;
  sessionStorage.setItem(getTokenKey(role), token);
  localStorage.removeItem(getTokenKey(role));
}

function getToken(role) {
  return sessionStorage.getItem(getTokenKey(role));
}

function removeToken(role) {
  sessionStorage.removeItem(getTokenKey(role));
  localStorage.removeItem(getTokenKey(role));
}

function detectRole() {
  if (window.CURRENT_ROLE) return window.CURRENT_ROLE;
  const path = window.location.pathname;
  if (path.includes('/admin/')) return 'admin';
  if (path.includes('/merchant/')) return 'merchant';
  if (path.includes('/rider/')) return 'rider';
  if (path.includes('/user/')) return 'user';
  return 'user';
}

// 统一的接口请求封装：自动拼接 /api 前缀、携带当前角色 token、处理 GET 查询参数。
const api = {
  async request(method, url, data = null, token = null) {
    const options = {
      method,
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include'
    };
    if (token) options.headers['X-Auth-Token'] = token;
    if (data && method !== 'GET') options.body = JSON.stringify(data);

    let fullUrl = `${API_BASE}${url}`;
    if (data && method === 'GET') {
      const params = new URLSearchParams();
      Object.entries(data).forEach(([k, v]) => {
        if (v !== null && v !== undefined && v !== '') params.append(k, v);
      });
      const qs = params.toString();
      if (qs) fullUrl += '?' + qs;
    }

    const resp = await fetch(fullUrl, options);
    return resp.json();
  },
  get(url, params = {}, role) { return this.request('GET', url, params, getToken(role || detectRole())); },
  post(url, data, role) { return this.request('POST', url, data, getToken(role || detectRole())); },
  put(url, data, role) { return this.request('PUT', url, data, getToken(role || detectRole())); },
  del(url, role) { return this.request('DELETE', url, null, getToken(role || detectRole())); }
};

// 登录、注册、退出和当前用户查询的统一认证入口。
const auth = {
  async login(username, password, role) {
    const res = await api.post('/auth/login', { username, password, role });
    if (res.code === 200 && res.data && res.data.token) saveToken(role, res.data.token);
    return res;
  },
  async register(username, password, name, phone, role = 'user', extraData = {}) {
    const data = { username, password, phone, role, ...extraData };
    if (role === 'user') data.real_name = name;
    else if (role === 'merchant') data.contact_name = name;
    else if (role === 'rider') data.rider_name = name;
    return api.post('/auth/register', data);
  },
  async logout(role) {
    const r = role || detectRole();
    const token = getToken(r);
    const res = await api.request('POST', '/auth/logout', null, token);
    removeToken(r);
    return res;
  },
  async currentUser(role) {
    const r = role || detectRole();
    if (!getToken(r)) return { code: 401, message: '未登录' };
    return api.get('/auth/current_user', {}, r);
  },
  anyLoggedIn() {
    return ['admin', 'merchant', 'rider', 'user'].some(r => !!getToken(r));
  }
};

// 右上角轻提示，适合表单保存、接单、支付等短反馈。
function showToast(message, type = 'success') {
  const colors = {
    success: 'var(--success)',
    error: 'var(--danger)',
    warning: 'var(--warning)',
    info: 'var(--info)'
  };
  const toast = document.createElement('div');
  toast.style.cssText = `
    position: fixed; top: 20px; right: 20px; z-index: 9999;
    background: ${colors[type] || colors.info}; color: white;
    padding: 12px 24px; border-radius: 8px; font-size: 0.9rem;
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    max-width: 400px;
  `;
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.3s';
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

// 居中轻提示，适合需要用户注意但不阻断流程的消息。
function showCenterToast(message, type = 'info') {
  const colors = {
    success: 'var(--success)',
    error: 'var(--danger)',
    warning: 'var(--warning)',
    info: 'var(--info)'
  };
  const toast = document.createElement('div');
  toast.style.cssText = `
    position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%);
    z-index: 10000; background: ${colors[type] || colors.info};
    color: ${type === 'warning' ? '#333' : 'white'};
    padding: 16px 26px; border-radius: 12px; font-size: 1rem;
    box-shadow: 0 10px 30px rgba(0,0,0,0.22);
    max-width: min(420px, 86vw); text-align: center;
  `;
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.25s';
    setTimeout(() => toast.remove(), 250);
  }, 2600);
}

// 前端状态码展示映射，需要和后端 Order_Info.order_status 保持一致。
const ORDER_STATUS = {
  0: { label: '待支付', badge: 'badge-warning' },
  1: { label: '待接单', badge: 'badge-warning' },
  2: { label: '备餐中', badge: 'badge-info' },
  3: { label: '已出餐', badge: 'badge-primary' },
  4: { label: '配送中', badge: 'badge-primary' },
  5: { label: '已完成', badge: 'badge-success' },
  6: { label: '已取消', badge: 'badge-secondary' },
  7: { label: '异常', badge: 'badge-danger' }
};

// 支付状态展示映射，对应 Order_Info.pay_status。
const PAY_STATUS = {
  0: { label: '未支付', badge: 'badge-warning' },
  1: { label: '支付成功', badge: 'badge-success' },
  2: { label: '支付失败', badge: 'badge-danger' },
  3: { label: '已退款', badge: 'badge-secondary' }
};

// 支付方式展示映射，对应 Order_Info.pay_method。
const PAY_METHOD = {
  wechat: { label: '微信支付' },
  alipay: { label: '支付宝' },
  bank_card: { label: '银行卡' },
  cash: { label: '货到付款' },
  wallet: { label: '我的钱包' }
};

// 配送任务状态展示映射，对应 Delivery.delivery_status。
const DELIVERY_STATUS = {
  0: { label: '待取餐', badge: 'badge-warning' },
  1: { label: '配送中', badge: 'badge-primary' },
  2: { label: '已送达', badge: 'badge-success' },
  3: { label: '异常', badge: 'badge-danger' }
};

// 骑手工作状态展示映射，对应 Rider.work_status。
const RIDER_WORK_STATUS = {
  0: { label: '离线', badge: 'badge-secondary' },
  1: { label: '在线', badge: 'badge-success' },
  2: { label: '忙碌', badge: 'badge-warning' }
};

// 售后状态展示映射，对应 Order_Info.after_sale_status。
const AFTER_SALE_STATUS = {
  0: { label: '无', badge: 'badge-secondary' },
  1: { label: '申请中', badge: 'badge-warning' },
  2: { label: '已处理', badge: 'badge-success' }
};

// 页面加载时校验当前角色身份，不通过时清理 token 并跳回登录页。
async function checkRole(requiredRole) {
  const token = getToken(requiredRole);
  if (!token) {
    window.location.href = '../../index.html';
    return null;
  }
  const res = await auth.currentUser(requiredRole);
  if (res.code === 200 && res.data && res.data.role === requiredRole) return res.data;
  removeToken(requiredRole);
  window.location.href = '../../index.html';
  return null;
}

function orderStatusLabel(status) {
  const s = ORDER_STATUS[status];
  return s ? `<span class="badge ${s.badge}">${s.label}</span>` : status;
}

function payStatusLabel(status) {
  const s = PAY_STATUS[status];
  return s ? `<span class="badge ${s.badge}">${s.label}</span>` : status;
}

function payMethodLabel(method) {
  const s = PAY_METHOD[method];
  return s ? s.label : '未选择';
}

function deliveryStatusLabel(status) {
  const s = DELIVERY_STATUS[status];
  return s ? `<span class="badge ${s.badge}">${s.label}</span>` : status;
}
