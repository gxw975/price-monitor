import { defineConfig } from 'prisma/config'

export default defineConfig({
  schema: 'src/prisma/schema.prisma',
  datasource: {
    url: process.env.DATABASE_URL || 'postgresql://openclaw:openclaw123@localhost:5432/openclaw?schema=price_monitor',
  },
  migrations: {
    path: 'src/prisma/migrations',
  },
})
