# 电商低价监控系统开发规范

## 项目基本信息
- 项目名：电商低价监控系统
- 服务器工作区路径：/home/lab-admin/price-monitor
- 技术栈：Next.js 14 + FastAPI + PostgreSQL + Prisma
- 核心功能：淘宝商品SKU抓取、低价预警、销量预警、飞书推送

## 工作流（重要）
- **主工作区是服务器本地文件**，所有开发编辑直接在 `/home/lab-admin/price-monitor` 上进行
- GitHub 仓库 `https://github.com/gxw975/price-monitor` 仅用于版本备份、同步和回滚
- 改完代码后推送到 GitHub 备份，**不要从 GitHub 拉取作为主工作区**

## 系统架构
- 前端：Next.js 14 + Tailwind + Shadcn UI
- 后端：FastAPI Python
- 数据库：PostgreSQL + Prisma ORM
- 自动化：OpenCLI + GenericAgent
- 定时任务：cron
- 通知：飞书机器人 Webhook

## 代码规范
- 使用Python 3.10+语法
- 所有函数必须有类型注解
- 错误处理使用try-except，禁止裸except
- 日志使用logging模块，禁止print
- 所有配置从.env文件读取，禁止硬编码

## Git 自定义命令（必须记住）
- `git-feature 功能名`   # 创建功能分支
- `git-save "提交信息"`  # 自动提交推送（服务器改完 → GitHub 备份）
- `gcm && gl`           # 切换 main 并拉取，触发自动部署
- `git-rollback last`   # 回滚上一个版本

## Git提交规范
- 严格遵循Conventional Commits
- 每次提交只包含一个完整的小功能
- 提交信息必须清晰描述变更内容

## 部署规则
- 自动部署脚本：scripts/deploy.sh
- 部署会自动：激活虚拟环境、安装依赖、生成Prisma客户端、应用迁移、重启服务
- 服务管理：systemctl price-monitor
- Supervisor 配置：/home/lab-admin/price-monitor/supervisor.conf
- Supervisor 控制：sudo supervisorctl -c /home/lab-admin/price-monitor/supervisor.conf

## 定时任务（cron）
- 每2小时：SKU抓取 (run_sku_crawl.py)
- 每3小时：预警检测 (check_alerts.py)
- 每日01:00：数据库备份
- 每日02:00：日志清理

## 核心业务规则
- 仅「已审核 + 非白名单」商品参与预警和SKU抓取
- 飞书推送仅在工作时段 9:00-18:00，周末跳过
- 预警24小时去重，避免重复推送
- SKU抓取使用真人浏览器模拟（OpenCLI），保留淘宝登录状态
- OpenCLI profile: zu4794g4（服务器本地 Chrome）

## 常用命令
- 启动开发服务：python src/main.py
- 启动 API 服务：cd /home/lab-admin/price-monitor && PYTHONPATH=src .venv/bin/python3 -m uvicorn main:app --host 127.0.0.1 --port 3001
- 查看日志：tail -f logs/monitor.log
- 重启服务：sudo systemctl restart price-monitor
- 前端构建：npx next build
- Prisma迁移：npx prisma migrate dev --name <名称>
- Prisma生成：npx prisma generate
