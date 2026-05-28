import Link from 'next/link'

export default function Home() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50">
      <div className="text-center space-y-6">
        <h1 className="text-3xl font-bold text-gray-900">电商低价监控系统</h1>
        <p className="text-gray-500">E-commerce Price Monitor Dashboard</p>
        <div className="flex gap-4 justify-center">
          <Link
            href="/admin/alerts"
            className="rounded-lg bg-blue-600 px-6 py-3 text-white hover:bg-blue-700 transition-colors"
          >
            预警管理
          </Link>
        </div>
      </div>
    </div>
  )
}
