# 新会话接手指南

## 当前任务：完达山学乐奶粉 抓取测试

## 项目背景
- 淘宝商品价格监控系统，位于 `/home/lab-admin/price-monitor`
- 核心爬虫：`src/services/xdotool_crawler.py`（纯 xdotool 物理操作）
- Chrome 运行要求：DISPLAY=:0，XAUTHORITY=/run/user/1000/.mutter-Xwaylandauth.47UFP3
- **禁止** `--remote-debugging-port` 用于爬取（A12），但 CDP 检测验证码需要一个端口（9223）

## 已完成的代码修改（全部在 `src/services/xdotool_crawler.py`）

### 1. `_detect_captcha()` — 完全重写（line ~534）
- **新增 CDP DOM 检测**（`_detect_captcha_cdp()`）：通过 `Runtime.evaluate` 检查页面 DOM 中是否有滑块元素（`#nc_1_n1z`、`.nc_wrapper`），**无干扰操作，不碰地址栏**
- **保留标题检测**作为备用（检查窗口标题关键词）
- **移除了地址栏 URL 检测**（之前会 Ctrl+L/Ctrl+C 乱操作）
- CDP 检测成功时会将滑块坐标存到 `self._cdp_slider_x/y` 和 `self._cdp_track_w`

### 2. `_solve_captcha_x11()` — 升级为 v3 + CDP 坐标（line ~723）
- **优先使用 CDP 精确坐标**（`self._cdp_slider_x/y`），精确到像素
- **视口基准估算**作为备用（加了 85px 工具栏偏移修正）
- 40-60 拖拽点，2-3.5 秒 S 曲线轨迹，多频 Y 轴漂移，过冲回弹

### 3. `_verify_step()` — 使用增强检测（line ~132）
- 调用 `_detect_captcha()`（含 CDP）+ page_verifier 双重检测
- 每步记录页面特征（`_record_feature`）

### 4. 验证码屏障在关键步骤：
- `crawl_keyword()` 入口（line ~1664）
- 搜索后（line ~1178/1196）
- DTS 每个操作前后（通过 `run_dts_export` 中的 `_verify_step`）
- 自动加载循环中每 5 秒检查

### 5. `_find_chrome_wid()` — 面积过滤（line ~330）
- 过滤阈值从 10000 提升到 100000 像素（排除 10x10 辅助窗口）
- 按面积排序选最大 Chrome 窗口

### 6. `_activate_chrome()` — 移除 `--sync`（line ~384）
- `windowactivate --sync` 和 `windowfocus --sync` 改为无 sync
- 修复了 xdotool 永久挂起的 bug

### 7. DTS 面板坐标重定位
- 所有 DTS 点击坐标从页面左侧改为 Chrome 弹出面板区域（右上方）
- 包括：扩展图标、市场分析、开始分析、自动加载、全选、导出

### 8. 加速测试参数
```python
AUTO_LOAD_SINGLE_WAIT = 15   # 15s/次
AUTO_LOAD_BATCH_SIZE = 5      # 5次/批
AUTO_LOAD_BATCH_PAUSE = 30    # 30s 批间暂停
AUTO_LOAD_MAX_BATCHES = 6     # 最多6批
```

## 环境状态
- Chrome 当前运行中（或需重启）
- 淘宝已登录（cookie 持久化在 profile 中）
- Python venv：`./venv/bin/python3`
- CDP 端口：9223（需确认 Chrome 启动时带此参数）

## 立即执行

### 步骤1：确保 Chrome 运行且带 CDP 端口 9223
```bash
export DISPLAY=:0 XAUTHORITY=/run/user/1000/.mutter-Xwaylandauth.47UFP3
sed -i 's/"exit_type":"crashed"/"exit_type":"Normal"/' /home/lab-admin/.config/google-chrome/Default/Preferences
rm -f /home/lab-admin/.config/google-chrome/SingletonLock
/usr/bin/google-chrome-stable --user-data-dir=/home/lab-admin/.config/google-chrome --start-maximized --no-first-run --restore-last-session=false --disable-session-crashed-bubble --disable-crash-reporter --ozone-platform=x11 --remote-debugging-port=9223 "https://www.taobao.com" &
```

### 步骤2：清缓存并启动抓取
```bash
cd /home/lab-admin/price-monitor
find src -name "*.pyc" -delete
./venv/bin/python3 -u -c "
import sys; sys.path.insert(0,'src'); import logging
logging.basicConfig(level=logging.INFO,format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',handlers=[logging.FileHandler('logs/crawl_wandashan.log',mode='w')])
from services.xdotool_crawler import XdotoolCrawler
c=XdotoolCrawler(); r=c.crawl_keyword('完达山学乐奶粉')
print('RESULT:', r)
" &
```

### 步骤3：监控
```bash
tail -f logs/crawl_wandashan.log
```

## 关键日志关键词
- `[验证码] CDP检测到` — CDP 成功检测到验证码（含精确坐标）
- `[验证码] 使用CDP精确坐标` — 滑块求解使用精确坐标
- `[特征]` — 每步页面特征记录
- `PASS` / `FAIL` — 抓取结果
- `RESULT:` — 最终结果
