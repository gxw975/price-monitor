-- CreateTable
CREATE TABLE "Alert" (
    "id" SERIAL NOT NULL,
    "product_id" TEXT NOT NULL,
    "alert_type" TEXT NOT NULL,
    "message" TEXT NOT NULL,
    "is_sent" BOOLEAN NOT NULL DEFAULT false,
    "sent_at" TIMESTAMP(3),
    "is_read" BOOLEAN NOT NULL DEFAULT false,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "Alert_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "Alert_product_id_created_at_idx" ON "Alert"("product_id", "created_at");

-- CreateIndex
CREATE INDEX "Alert_alert_type_created_at_idx" ON "Alert"("alert_type", "created_at");

-- CreateIndex
CREATE INDEX "Alert_is_read_created_at_idx" ON "Alert"("is_read", "created_at");
