import type { Metadata } from "next";

import { dictionary } from "../i18n";
import { JoinPage } from "../join-page";

const t = dictionary("ru");

export const metadata: Metadata = {
  title: t.join.metaTitle,
  description: t.join.metaDescription,
  // Страница открывается одноразовой ссылкой из письма — в поиске ей
  // делать нечего, и языкового двойника для поиска у неё тоже нет.
  robots: { index: false, follow: false },
};

export default function Join({ searchParams }: { searchParams: Promise<{ token?: string }> }) {
  return <JoinPage lang="ru" searchParams={searchParams} />;
}
