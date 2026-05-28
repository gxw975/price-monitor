const { PHASE_DEVELOPMENT_SERVER } = require('next/constants')

module.exports = (phase) => {
  return {
    reactStrictMode: true,
    transpilePackages: [],
    async rewrites() {
      return [
        {
          source: '/api/:path*',
          destination: 'http://127.0.0.1:3001/api/:path*',
        },
      ]
    },
  }
}
