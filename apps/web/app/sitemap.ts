import type { MetadataRoute } from "next";

import { SITE_URL } from "./contacts";
import { localePath } from "./i18n/config";

/* Карта сайта. Открытых страниц три, и у каждой два языка; дата у них —
   дата сборки: страницы статические, и меняются они только вместе с
   выкатом.

   🔥 У каждой записи перечислены её языковые двойники (`alternates`).
   Без них поисковик считает русскую и английскую страницы разными
   документами с похожим содержимым и показывает одну из двух на свой
   выбор — обычно не ту, на языке которой ищут. */

const PAGES: { path: string; changeFrequency: "weekly" | "monthly"; priority: number }[] = [
  { path: "/", changeFrequency: "weekly", priority: 1 },
  { path: "/register", changeFrequency: "monthly", priority: 0.6 },
  { path: "/login", changeFrequency: "monthly", priority: 0.3 },
];

export default function sitemap(): MetadataRoute.Sitemap {
  const built = new Date();

  return PAGES.flatMap((page) => {
    const languages = {
      ru: `${SITE_URL}${localePath("ru", page.path)}`,
      en: `${SITE_URL}${localePath("en", page.path)}`,
    };

    return [
      {
        url: languages.ru,
        lastModified: built,
        changeFrequency: page.changeFrequency,
        priority: page.priority,
        alternates: { languages },
      },
      {
        url: languages.en,
        lastModified: built,
        changeFrequency: page.changeFrequency,
        // Английская половина новее и меньше весит в поиске: приоритет
        // ниже русской, но не ноль — это полноценные страницы.
        priority: page.priority * 0.9,
        alternates: { languages },
      },
    ];
  });
}
