-- CreateSchema
CREATE SCHEMA IF NOT EXISTS "price_monitor";

-- CreateTable
CREATE TABLE "price_monitor"."User" (
    "id" SERIAL NOT NULL,
    "username" TEXT NOT NULL,
    "password_hash" TEXT NOT NULL,
    "role" TEXT NOT NULL DEFAULT 'user',
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "User_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "price_monitor"."Product" (
    "product_id" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "main_image_url" TEXT,
    "shop_name" TEXT NOT NULL,
    "shop_type" TEXT,
    "shipping_area" TEXT,
    "is_approved" BOOLEAN NOT NULL DEFAULT false,
    "is_whitelist" BOOLEAN NOT NULL DEFAULT false,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "last_updated_at" TIMESTAMP(3) NOT NULL DEFAULT NOW(),
    CONSTRAINT "Product_pkey" PRIMARY KEY ("product_id")
);

-- CreateTable
CREATE TABLE "price_monitor"."ProductHistory" (
    "id" SERIAL NOT NULL,
    "product_id" TEXT NOT NULL,
    "price" DECIMAL(10,2) NOT NULL,
    "sales_volume" INTEGER NOT NULL,
    "recorded_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "ProductHistory_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "price_monitor"."ProductSku" (
    "id" SERIAL NOT NULL,
    "product_id" TEXT NOT NULL,
    "sku_name" TEXT NOT NULL,
    "sku_price" DECIMAL(10,2) NOT NULL,
    "unit_price" DECIMAL(10,2) NOT NULL,
    "sku_image_url" TEXT,
    "recorded_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "ProductSku_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "price_monitor"."SystemConfig" (
    "id" SERIAL NOT NULL,
    "alert_price" DECIMAL(10,2) NOT NULL,
    "work_start_hour" INTEGER NOT NULL DEFAULT 9,
    "work_end_hour" INTEGER NOT NULL DEFAULT 18,
    "sales_growth_threshold" INTEGER NOT NULL DEFAULT 100,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL DEFAULT NOW(),
    "keywords" TEXT NOT NULL DEFAULT '[]',
    "sku_crawl_limit" INTEGER NOT NULL DEFAULT 10,
    "sku_crawl_interval" INTEGER NOT NULL DEFAULT 120,
    CONSTRAINT "SystemConfig_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "User_username_key" ON "price_monitor"."User"("username");

-- CreateIndex
CREATE INDEX "ProductHistory_product_id_recorded_at_idx" ON "price_monitor"."ProductHistory"("product_id", "recorded_at");

-- CreateIndex
CREATE INDEX "ProductSku_product_id_idx" ON "price_monitor"."ProductSku"("product_id");
