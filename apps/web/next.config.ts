import type { NextConfig } from "next";

/* Адрес API держим в переменной окружения: витрина деплоится на Vercel,
   а бэкенд живёт на своём сервере — они не обязаны переезжать вместе. */
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

/* Заголовки безопасности.

   `frame-ancestors 'none'` — против подмены нажатий: кабинет и вход нельзя
   открыть в чужом кадре. `form-action 'self'` не даёт увести отправку формы
   на посторонний адрес, `base-uri 'self'` — переписать базу относительных
   ссылок вставленным тегом.

   `script-src` вынужденно допускает встроенные сценарии: тема применяется
   до первой отрисовки коротким сценарием в разметке, иначе у выбравшего
   тёмную кабинет моргает белым. Правильное лекарство — разовый ключ (nonce)
   из промежуточного слоя на каждый ответ; это отдельная работа, и записана
   она как таковая, а не выдана за сделанную. */
const CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  `connect-src 'self'${API_URL === "" ? "" : ` ${API_URL}`}`,
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join("; ");

const SECURITY_HEADERS = [
  { key: "Content-Security-Policy", value: CSP },
  { key: "X-Content-Type-Options", value: "nosniff" },
  // Дублирует frame-ancestors для браузеров, которые до него не доросли.
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
  // Год и поддомены. Заголовок действует только по HTTPS — на локальной
  // разработке браузер его игнорирует.
  { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
];

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Версия сервера в заголовке ответа — бесплатная подсказка тому, кто
  // подбирает уязвимость под конкретную версию.
  poweredByHeader: false,
  env: {
    NEXT_PUBLIC_API_URL: API_URL,
  },
  async headers() {
    return [{ source: "/:path*", headers: SECURITY_HEADERS }];
  },
};

export default nextConfig;
