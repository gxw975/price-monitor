# 商品分类功能 — 当前状态与未解决问题

## 数据库状态（已正确）

```
JD:   397已分类 / 2未分类 (共399)
淘天: 165已分类 / 77未分类 (共242)
```

DB 是最新的，Python 直接更新已生效。

## 前端显示问题

**现象**：商品列表页「未分类(N)」的 N 始终显示旧数字（如 399 或 11），不更新。

**根因**：前端 `products` 状态在「一键推荐」后没有正确重新加载筛选后的数据。

**相关文件**：
- `src/app/admin/monitor-products/[id]/page.tsx` — 行 292 一键推荐按钮的 onClick
- 该页面 `products` state 通过 `GET /api/monitor-products/{id}/products?sku_category_id=0` 筛选

## 后端 API 问题

**现象**：`POST /api/monitor-products/{id}/apply-recommendations` 返回 `applied: 0`，即使 SkuNormalizer 匹配正确。

**测试结果**：
```bash
# 终端直接测试 — 匹配正常
./venv/bin/python3 -c "
import sys; sys.path.insert(0,'src')
from services.sku_normalizer import SkuNormalizer
n = SkuNormalizer(19)  # JD
print(n.match_sku_category('蒙牛一米八八儿童奶粉 300g*3赠1保温杯'))
# → {'id': 6, 'name': '袋装 (300g)', ...}  ✅ 正确
"
```

**可能原因**：FastAPI uvicorn 未 reload，运行的是旧代码（有两个 match_sku_category 方法的版本）。

## 已修改的文件

1. **`src/services/sku_normalizer.py`**
   - 新增 `DEFAULT_CATEGORY_RULES["条装"]`（独立于袋装）
   - `match_sku_category` 新增重量推断：300g→袋装, 800g→罐装 等
   - **删除了重复的旧版 match_sku_category 方法**（关键修复）

2. **`src/api/monitor_products.py`**
   - 新增 `POST /{id}/apply-recommendations` 端点
   - 新增 `PUT /{id}/sku-categories/{cat_id}` 单商品分类更新
   - 新增 `_recalc_unit_prices` 辅助函数

3. **`src/app/admin/monitor-products/[id]/page.tsx`**
   - 分类筛选按钮（全部/袋装/罐装/条装/混合装/未分类）
   - 一键推荐按钮
   - 分类列悬浮编辑（点击显示下拉框）
   - 标题悬浮卡片预览
   - 筛选按钮显示计数
   - 一键推荐后保持筛选条件刷新

4. **`src/app/admin/analysis/page.tsx`**
   - 白名单同时匹配 seller_name + shop_name

5. **`src/app/admin/alerts/page.tsx`**
   - 新增平台列

## 验证命令

```bash
# 1. 确认 DB 状态
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
SET search_path TO price_monitor;
SELECT monitor_product_id, COUNT(*) FILTER (WHERE sku_category_id IS NULL) FROM \"Product\" GROUP BY 1;
"

# 2. 确认 match_sku_category 工作
./venv/bin/python3 -c "
import sys; sys.path.insert(0,'src')
from services.sku_normalizer import SkuNormalizer
for mp in [10,19]:
    n = SkuNormalizer(mp)
    print(f'MP{mp}: {len(n._categories)} cats, rules: {list(n._rules.keys())}')
"

# 3. 直接回填（绕过 API）
./venv/bin/python3 -c "
import sys; sys.path.insert(0,'src')
import psycopg2,os; from dotenv import load_dotenv; from urllib.parse import urlparse,parse_qs,urlunparse
load_dotenv(); url=os.getenv('DATABASE_URL'); p=urlparse(url)
clean=urlunparse(p._replace(query='')); conn=psycopg2.connect(clean)
with conn.cursor() as c: c.execute('SET search_path TO price_monitor')
from services.sku_normalizer import SkuNormalizer
for mp in [10,19]:
    n=SkuNormalizer(mp)
    c=conn.cursor()
    c.execute('SELECT product_id,title,price FROM \"Product\" WHERE monitor_product_id=%s AND sku_category_id IS NULL AND price>0',(mp,))
    updated=0
    for pid,title,price in c.fetchall():
        cat=n.match_sku_category(title)
        if not cat or not cat.get('id'): continue
        qty=n.extract_quantity(title)
        tw=qty*float(cat.get('conversion_factor',1))*25
        up=round(float(price)/tw,4) if tw>0 else 0
        c2=conn.cursor(); c2.execute('UPDATE \"Product\" SET sku_category_id=%s,unit_price=%s WHERE product_id=%s',(cat['id'],up,pid)); c2.close()
        conn.commit(); updated+=1
    print(f'MP{mp}: {updated} classified')
conn.close()
"

# 4. 重启服务
sudo supervisorctl -c /home/lab-admin/price-monitor/supervisor.conf restart all
```

## 关键注意

- 前端修改后必须 `npm run build` + 重启 nextjs-frontend
- 后端修改后必须重启 fastapi-backend（无 --reload 参数）
- 浏览器需要 Ctrl+Shift+R 硬刷新清除缓存
