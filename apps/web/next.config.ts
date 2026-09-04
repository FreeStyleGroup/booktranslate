import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  /* Адрес API держим в переменной окружения: витрина деплоится на Vercel,
     а бэкенд живёт на своём сервере — они не обязаны переезжать вместе. */
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL ?? "",
  },
};

export default nextConfig;
