# v3.4-v3.5 变更总结（2026-06-10 ~ 2026-06-11）

共 40+ commits，核心目标：**SKU分类自动化 + 平台隔离 + 京东适配**

---

## 一、数据库变更

| 表 | 新增字段 | 说明 |
|----|---------|------|
| MonitorProduct | `platform` | 淘天/jd |
| Product | `platform`, `sku_category_id`, `unit_price`, `image_url` | 平台标记+分类+单价+图片 |
| Alert | `platform`, `is_handled` | 平台标记+已处理 |
| ImportBatch | `platform` | 平台标记 |
| SkuCategory | `keywords` | 自学习关键词 |
| SystemConfig | `wechat_push_enabled`, `wechat_sendkey` | 微信推送 |

---

## 二、核心功能

### 1. SKU 自动分类系统
**文件**: `src/services/sku_normalizer.py`

匹配优先级:
1. 标题含关键词（袋/罐/条/盒/混合）→ 直接匹配
2. 标题含量量（300g→袋装, 800g→罐装等）→ 推断匹配
3. 都不含 → 保持未分类

关键修复:
- 条装从袋装规则中独立出来（DEFAULT_CATEGORY_RULES）
- **删除了重复的旧版 match_sku_category 方法**（两个同名方法，旧版覆盖新版导致重量推断不生效）
- COLUMN_PATTERNS 改为实例变量，支持 JdDtsParser 子类覆盖

### 2. 一键应用推荐
**文件**: `src/api/monitor_products.py`

- `POST /{id}/apply-recommendations` — 对未分类商品自动匹配分类
- `GET /{id}/products/counts` — 专用计数端点（total/classified/unclassified）
- `PUT /{id}/sku-categories/{cat_id}` — 单商品分类更新+自学习关键词提取

### 3. 京东适配
**文件**: `src/services/dts_parser.py`

- `JdDtsParser(DtsDataParser)` 继承淘宝解析器，仅覆盖列映射
- 京东列: 商品ID/商品名称/京东价/原价/总销量/店铺名称/店铺ID/店铺类型/商品图片/促销
- 销量解析: `50万+` → 500000, `2.3万` → 23000
- 商品链接自动拼接: `https://item.jd.com/{id}.html`
- 促销列有值 → 广告位

### 4. 平台数据隔离
- 导入时使用 MonitorProduct 自身的 platform，不读 Excel 列
- Product 表 platform 字段归一化（淘宝/天猫 → taobao）
- 前端 PlatformToggle 切换时页面刷新，所有 API 按 platform 筛选

### 5. 自学习关键词
手动设置商品分类时，自动从标题提取单位关键词（如"袋"/"罐"），保存到 SkuCategory.keywords

---

## 三、前端改动

### 商品列表页 (`src/app/admin/monitor-products/[id]/page.tsx`)
- 分类筛选按钮（全部/袋装/罐装/条装/混合装/未分类）— **后端互斥查询**
- 一键推荐按钮 + 计数实时刷新
- 分类列：默认显示名称，点击弹出下拉框选择
- 标题悬浮卡片：图片+价格+推荐分类
- 单克价列（红色 < ¥0.5/g）
- 筛选栏：标题/商品ID/现价/销量/店铺搜索
- 白名单：京东按 shop_name，淘天按 seller_name

### 分析页 (`src/app/admin/analysis/page.tsx`)
- 历史趋势图按钮 + 响应式大弹窗（双轴）
- 图片悬浮放大
- 白名单过滤

### 预警中心 (`src/app/admin/alerts/page.tsx`)
- 新增平台列（橙色淘天/红色京东）
- 批量标记已处理同步已读

### 故障排查 (`src/app/admin/diagnostics/page.tsx`)
- 日志查看器新增复制按钮

---

## 四、已知 Bug 及修复

| Bug | 根因 | 修复 |
|-----|------|------|
| .toFixed() 报错 | psycopg2 DECIMAL→字符串 | Number() 转换 |
| 分类筛选无结果 | sku_category_id 全为 NULL | 后端按标题关键词匹配改为按 ID 查询 |
| 匹配规则不生效 | 两个 match_sku_category 方法 | 删除旧版 |
| 商品列表 404 | list_products 装饰器丢失 | 补回 @router.get |
| 计数不准 | 前端 products 数组 ≠ DB 真值 | 专用 /counts 端点 |
| 手动分类后筛选跳回全部 | 刷新时未传 catFilter 参数 | refreshProducts(catFilter) |
| 京东商品列表为空 | platform 存储值与筛选值不匹配 | 导入时使用 MonitorProduct.platform |

---

## 五、数据库直接操作（已执行）

```sql
-- 平台归一化
UPDATE "Product" SET platform='taobao' WHERE platform IN ('淘宝','天猫','');
-- 京东商品 platform 修正
UPDATE "Product" SET platform='jd' WHERE monitor_product_id=19;
-- 混合装分类创建
INSERT INTO "SkuCategory" (monitor_product_id, name, unit, conversion_factor) VALUES (10,'混合装','组',1);
INSERT INTO "SkuCategory" (monitor_product_id, name, unit, conversion_factor) VALUES (19,'混合装','组',1);
```

## 六、当前数据状态

| 平台 | 总数 | 已分类 | 未分类 |
|------|------|--------|--------|
| 淘天 | 242 | 165 | 77 |
| 京东 | 399 | 397 | 2 |

---

## 七、关键文件清单

| 文件 | 状态 |
|------|------|
| `src/services/sku_normalizer.py` | 修改（+重量推断+条装独立+删除旧方法） |
| `src/services/dts_parser.py` | 修改（+JdDtsParser+COLUMN_PATTERNS 实例化） |
| `src/api/monitor_products.py` | 修改（+apply-recommendations+counts+分类更新+recalc） |
| `src/api/alerts.py` | 修改（+platform+batch-handle 设 is_read） |
| `src/api/notifications.py` | 修改（排除 is_handled） |
| `src/app/admin/monitor-products/[id]/page.tsx` | 大量修改 |
| `src/app/admin/analysis/page.tsx` | 修改 |
| `src/app/admin/alerts/page.tsx` | 修改 |
| `src/app/admin/diagnostics/page.tsx` | 修改 |
| `src/app/layout.tsx` | 修改（+PlatformToggle） |
