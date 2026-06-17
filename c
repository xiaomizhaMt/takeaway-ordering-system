# -*- coding: utf-8 -*-
"""批量替换所有前端页面的 loadUserInfo，使用 checkRole 做角色校验"""
import os
import re

BASE = r'c:\Users\xiaomizha\VSCode\database-course-design\frontend\pages'

# 角色 → 对应页面列表
PAGES = {
    'admin': ['admin/complaints.html', 'admin/dashboard.html', 'admin/merchants.html',
              'admin/orders.html', 'admin/riders.html', 'admin/statistics.html', 'admin/users.html'],
    'merchant': ['merchant/dashboard.html', 'merchant/dishes.html', 'merchant/orders.html',
                 'merchant/reviews.html', 'merchant/statistics.html'],
    'rider': ['rider/dashboard.html', 'rider/income.html', 'rider/tasks.html'],
    'user': ['user/cart.html', 'user/dashboard.html', 'user/orders.html', 'user/order_detail.html', 'user/reviews.html'],
}

def get_new_func(role, icon, is_cart=False):
    """生成新的 loadUserInfo 函数体（多行格式，支持缩进自适应）"""
    if is_cart:
        return f'''async function loadUserInfo() {{
      const u = await checkRole('{role}');
      if (!u) return;
      document.getElementById('userInfo').textContent = '{icon} ' + u.username;
      const p = await api.get('/user/profile');
      if (p.code === 200) {{
        document.getElementById('receiverName').value = p.data.default_receiver || '';
        document.getElementById('receiverPhone').value = p.data.default_phone || '';
        document.getElementById('receiverAddress').value = p.data.default_address || '';
      }}
    }}'''
    return f'''async function loadUserInfo() {{
      const u = await checkRole('{role}');
      if (u) document.getElementById('userInfo').textContent = '{icon} ' + u.username;
    }}'''


if __name__ == '__main__':
    for role, pages in PAGES.items():
        is_cart_page = (role == 'user')
        for page in pages:
            fp = os.path.join(BASE, page)
            with open(fp, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # cart.html gets special treatment
            is_cart = (page == 'user/cart.html')
            
            # Build the new function text (indent-agnostic)
            new_func = get_new_func(role, {'admin': '👑', 'merchant': '🏪', 'rider': '🛵', 'user': '👤'}[role], is_cart)
            
            # Pattern 1: multi-line async function loadUserInfo() { ... }
            pattern1 = r'(\s*)async function loadUserInfo\(\)\s*\{.*?\n\s*\}(?=\s*\n\s*(?:loadUserInfo|//|$))'
            m = re.search(pattern1, content, re.DOTALL)
            if m:
                indent = m.group(1)
                # Re-indent the new function
                lines = new_func.split('\n')
                reindented = '\n'.join([lines[0]] + [indent + l if l.strip() else l for l in lines[1:]])
                content = content.replace(m.group(0), reindented)
                print(f'✅ {page} (多行匹配)')
            else:
                # Pattern 2: single line async function loadUserInfo(){...}
                pattern2 = r'async function loadUserInfo\(\)\s*\{[^}]*;\s*\}'
                m2 = re.search(pattern2, content)
                if m2:
                    oneliner = f'async function loadUserInfo(){{const u=await checkRole(\'{role}\');if(u)document.getElementById(\'userInfo\').textContent=\'{icon_map[role]} \'+u.username;}}'
                    content = content.replace(m2.group(0), oneliner)
                    print(f'✅ {page} (单行匹配)')
                else:
                    # Pattern 3: try matching any loadUserInfo block with more complex content
                    pattern3 = r'async function loadUserInfo\(\)\s*\{(?:[^}]*\n)*?[^}]*\}'
                    m3 = re.search(pattern3, content, re.DOTALL)
                    if m3:
                        # For cart page, use the cart version
                        if is_cart:
                            new_func_full = f'''async function loadUserInfo() {{
      const u = await checkRole('{role}');
      if (!u) return;
      document.getElementById('userInfo').textContent = '{icon_map[role]} ' + u.username;
      const p = await api.get('/user/profile');
      if (p.code === 200) {{
        document.getElementById('receiverName').value = p.data.default_receiver || '';
        document.getElementById('receiverPhone').value = p.data.default_phone || '';
        document.getElementById('receiverAddress').value = p.data.default_address || '';
      }}
    }}'''
                        else:
                            new_func_full = f'''async function loadUserInfo() {{
      const u = await checkRole('{role}');
      if (u) document.getElementById('userInfo').textContent = '{icon_map[role]} ' + u.username;
    }}'''
                        content = content.replace(m3.group(0), new_func_full)
                        print(f'✅ {page} (复杂匹配)')
                    else:
                        print(f'❌ {page} - 无法匹配!')
                        continue
            
            with open(fp, 'w', encoding='utf-8') as f:
                f.write(content)
    
    print('\n🎉 全部完成!')
