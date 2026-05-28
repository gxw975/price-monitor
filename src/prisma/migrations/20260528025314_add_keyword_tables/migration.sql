-- CreateTable
CREATE TABLE "Keyword" (
    "id" SERIAL NOT NULL,
    "name" TEXT NOT NULL,
    "platform" TEXT NOT NULL DEFAULT 'taobao',
    "is_active" BOOLEAN NOT NULL DEFAULT true,
    "created_by" INTEGER NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "Keyword_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ProductKeyword" (
    "keyword_id" INTEGER NOT NULL,
    "product_id" TEXT NOT NULL,

    CONSTRAINT "ProductKeyword_pkey" PRIMARY KEY ("keyword_id","product_id")
);

-- CreateIndex
CREATE INDEX "Keyword_is_active_createdAt_idx" ON "Keyword"("is_active", "createdAt");

-- CreateIndex
CREATE INDEX "ProductKeyword_product_id_idx" ON "ProductKeyword"("product_id");

-- CreateIndex
CREATE INDEX "ProductKeyword_keyword_id_idx" ON "ProductKeyword"("keyword_id");

-- AddForeignKey
ALTER TABLE "Keyword" ADD CONSTRAINT "Keyword_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ProductKeyword" ADD CONSTRAINT "ProductKeyword_keyword_id_fkey" FOREIGN KEY ("keyword_id") REFERENCES "Keyword"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ProductKeyword" ADD CONSTRAINT "ProductKeyword_product_id_fkey" FOREIGN KEY ("product_id") REFERENCES "Product"("product_id") ON DELETE RESTRICT ON UPDATE CASCADE;
