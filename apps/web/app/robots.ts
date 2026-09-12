import type { MetadataRoute } from "next";

import { SITE_URL } from "./contacts";

/* Что поисковикам можно, а что нет.

   Закрыты кабинет, служебные маршруты витрины и управление доступом: всё
   это за входом, и поисковику там показывать нечего, кроме страницы
   входа. Страница приглашения тоже закрыта: она открывается одноразовой
   ссылкой из письма. Вход и регистрация открыты — их ищут по названию
   продукта. */

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: ["/app/", "/api/", "/root/", "/join"],
      },
    ],
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
