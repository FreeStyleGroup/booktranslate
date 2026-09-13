import type { Metadata } from "next";

import { alternates } from "./i18n";
import { Landing } from "./landing";

// Остальное — заголовок, описание, Open Graph — наследуется от корневой
// разметки; здесь только адреса: канонический и двойник на другом языке.
export const metadata: Metadata = {
  alternates: alternates("ru", "/"),
};

export default function Home() {
  return <Landing lang="ru" />;
}
