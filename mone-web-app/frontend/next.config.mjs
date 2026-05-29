/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,

  webpack: (config) => {
    // Disable webpack filesystem cache because OneDrive can lock/move
    // .next/server chunk files during development on Windows.
    config.cache = false;
    return config;
  },
};

export default nextConfig;
