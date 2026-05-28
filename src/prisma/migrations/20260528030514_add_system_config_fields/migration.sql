-- AlterTable
ALTER TABLE "SystemConfig" ADD COLUMN     "alert_dedup_hours" INTEGER NOT NULL DEFAULT 24,
ADD COLUMN     "check_alert_interval" INTEGER NOT NULL DEFAULT 180,
ADD COLUMN     "crawl_daily_limit" INTEGER NOT NULL DEFAULT 100,
ADD COLUMN     "crawl_fixed_times" TEXT,
ADD COLUMN     "crawl_schedule_type" TEXT NOT NULL DEFAULT 'interval';
