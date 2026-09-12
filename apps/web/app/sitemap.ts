import type { MetadataRoute } from "next";

import { SITE_URL } from "./contacts";

/* Карта сайта. Открытых страниц три, и дата у них — дата сборки: страницы
   статические, и меняются они только вместе с выкатом. */

export default function sitemap(): MetadataRoute.Sitemap {
  const built = new Date();

  return [
    { url: `${SITE_URL}/`, lastModified: built, changeFrequency: "weekly", priority: 1 },
    { url: `${SITE_URL}/register`, lastModified: built, changeFrequency: "monthly", priority: 0.6 },
    { url: `${SITE_URL}/login`, lastModified: built, changeFrequency: "monthly", priority: 0.3 },
  ];
}
