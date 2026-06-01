# CLAUDE.md - 电商低价监控系统

## 永久约束（不可违反）

### 浏览器操作
1. **禁止无头浏览器**：任何情况下不得使用 headless 模式
2. **禁止虚拟显示器**：不得使用 Xvfb、Xvnc 等虚拟帧缓冲。Chrome 必须在真实物理显示器上运行
3. **禁止带特殊参数启浏览器**：不得使用 `--no-sandbox`、`--disable-blink-features=AutomationControlled`、`--disable-gpu` 等自动化标志启动浏览器
4. **必须模拟真人**：所有浏览器操作必须以模拟真人为目标（鼠标轨迹自然、操作间隔合理、不瞬移）
5. **必须用 GA**：涉及网页交互、滑块验证、DTS操作等复杂浏览器任务，优先使用 GA（Generic Agent）。GA 有成功的真人模拟经验

### 操作环境
- 主工作区：`/home/lab-admin/price-monitor`
- Chrome 必须在 DISPLAY=:0（真实显示器 1280x800）上运行
- 不得自行启动或杀死 Chrome（需要时请用户协助）
- Chrome 远程调试端口：9222

### 核心公理（来自项目交接文档）
- 仅已审核+非白名单商品参与预警和SKU抓取
- 飞书推送仅工作日9:00-18:00
- 预警24小时去重
- 管理员/主管可写，员工只读
- opencli绝对路径：`/usr/local/bin/opencli`
- 飞书API v2格式：`msg_type`
- 日志使用logging模块，禁止print
- 配置从.env读取，禁止硬编码

### 关键文件
- 后端主入口：`src/main.py`
- GA服务：`src/services/ga_service.py`
- CDP抓取器：`src/services/cdp_crawler.py`
- 验证码求解：`src/services/captcha_solver.py`
- 商品服务：`src/services/product_service.py`
- SKU抓取：`src/services/sku_service.py`
- 前端关键词页：`src/app/admin/keywords/page.tsx`
- GA安装路径：`/home/lab-admin/GenericAgent/`
- GA模型：deepseek-v4-pro（配置在 `mykey.py`）
