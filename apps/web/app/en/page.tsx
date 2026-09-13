import type { Metadata } from "next";

import { SITE_NAME } from "../contacts";
import { alternates, dictionary } from "../i18n";
import { Landing } from "../landing";

const t = dictionary("en");

// Заголовок, описание и Open Graph задаются заново, а не наследуются:
// корневая разметка описывает сайт по-русски, и английская страница,
// оставленная с ней, ушла бы в поиск с русским описанием.
export const metadata: Metadata = {
  title: t.meta.title,
  description: t.meta.description,
  alternates: alternates("en", "/"),
  openGraph: {
    title: t.meta.title,
    description: t.meta.ogDescription,
    siteName: SITE_NAME,
    locale: t.ogLocale,
    type: "website",
  },
};

export default function EnglishHome() {
  return <Landing lang="en" />;
}
