-- AlterTable
ALTER TABLE "SystemConfig" ADD COLUMN     "feishu_webhook" TEXT,
ADD COLUMN     "push_enabled_channels" TEXT NOT NULL DEFAULT '["feishu"]',
ADD COLUMN     "wechat_webhook" TEXT;
