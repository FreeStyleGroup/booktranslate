import type { MetadataRoute } from "next";

import { SITE_DESCRIPTION, SITE_NAME, TAGLINE } from "./contacts";

/* Манифест веб-приложения: по нему браузер предлагает поставить кабинет
   на рабочий стол или экран телефона и рисует его без адресной строки.

   Точка входа — кабинет, а не главная: ставит себе приложение тот, кто в
   нём работает, и открывать ему каждый раз рекламную страницу незачем.
   Без сеанса кабинет сам отправит на вход.

   Иконки двух назначений. `any` — со скруглёнными углами, как рисует сам
   значок. `maskable` — на всю площадь: Android обрезает такую по своей
   форме, и у значка со своими скруглениями получилась бы рамка внутри
   рамки. Рисунок в ней стоит в безопасной зоне — центральных 80 %. */

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: `${SITE_NAME} — ${TAGLINE}`,
    short_name: SITE_NAME,
    description: SITE_DESCRIPTION,
    lang: "ru",
    start_url: "/app",
    scope: "/",
    display: "standalone",
    background_color: "#ffffff",
    theme_color: "#2f6bff",
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icons/maskable-192.png", sizes: "192x192", type: "image/png", purpose: "maskable" },
      { src: "/icons/maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
