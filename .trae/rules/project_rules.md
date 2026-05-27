# 电商低价监控系统开发规范

## 代码规范
- 使用Python 3.10+语法
- 所有函数必须有类型注解
- 错误处理使用try-except，禁止裸except
- 日志使用logging模块，禁止print
- 所有配置从.env文件读取，禁止硬编码

## Git提交规范
- 严格遵循Conventional Commits
- 每次提交只包含一个完整的小功能
- 提交信息必须清晰描述变更内容

## 常用命令
- 启动开发服务：python src/main.py
- 查看日志：tail -f logs/monitor.log
- 重启服务：sudo systemctl restart price-monitor
