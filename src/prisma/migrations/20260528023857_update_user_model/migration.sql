-- AlterTable: rename columns to match updated Prisma schema
ALTER TABLE "User" RENAME COLUMN "password_hash" TO "password";
ALTER TABLE "User" RENAME COLUMN "created_at" TO "createdAt";
ALTER TABLE "User" ALTER COLUMN "role" SET DEFAULT 'staff';
