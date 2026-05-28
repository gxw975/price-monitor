#!/bin/bash
set -e

echo "========================================"
echo "开始自动部署电商低价监控系统"
echo "========================================"

# 安装Python依赖
echo "安装Python依赖..."
if [ -f requirements.txt ]; then
    ./venv/bin/pip install -r requirements.txt
fi

# 安装Node.js依赖
echo "安装Node.js依赖..."
if [ -f package.json ]; then
    npm install
fi

# 生成Prisma客户端
echo "生成Prisma客户端..."
npx prisma generate

# 应用数据库迁移
echo "应用数据库迁移..."
npx prisma migrate deploy

# 重启服务
echo "重启systemd服务..."
sudo systemctl restart price-monitor

# 健康检查
echo "等待服务启动..."
sleep 5

echo "检查服务状态..."
if sudo systemctl is-active --quiet price-monitor; then
    echo "✅ 部署成功！服务已正常运行"
    exit 0
else
    echo "❌ 部署失败！服务未启动"
    exit 1
fi
