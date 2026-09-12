import type { Metadata } from "next";

import { SITE_DESCRIPTION, SITE_NAME, SITE_TITLE, SITE_URL } from "./contacts";
import "./globals.css";

export const metadata: Metadata = {
  // От этого адреса считаются канонические ссылки и адреса в Open Graph:
  // без него Next отдал бы их относительными, а поисковику относительный
  // канонический адрес ни о чём не говорит.
  metadataBase: new URL(SITE_URL),
  title: SITE_TITLE,
  description: SITE_DESCRIPTION,
  applicationName: SITE_NAME,
  openGraph: {
    title: SITE_TITLE,
    description:
      "Термины решаются до перевода, числа и обозначения не разъезжаются, книга собирается обратно в свой формат со всем оформлением.",
    siteName: SITE_NAME,
    locale: "ru_RU",
    type: "website",
  },
  // Подтверждение прав на сайт в Яндекс.Вебмастере. Код — не секрет: он
  // и так виден в разметке каждой страницы, на этом проверка и построена.
  verification: {
    yandex: "163424560b1443f9",
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru">
      <head>
        {/* Тема проставляется до первой отрисовки: иначе выбравший тёмную
            каждый раз видит вспышку светлой. Скрипт крошечный и намеренно
            синхронный — асинхронный отработал бы уже после вспышки. */}
        <script
          dangerouslySetInnerHTML={{
            __html:
              'try{var t=localStorage.getItem("bt-theme");' +
              'if(t==="dark"||t==="light")document.documentElement.dataset.theme=t}catch(e){}',
          }}
        />
        {/* Блоки появляются по мере прокрутки — их прячет и показывает
            скрипт. Без скрипта прятать нечем и незачем: страница обязана
            остаться читаемой целиком. */}
        <noscript>
          <style>{`.reveal > *, .reveal .grid > *, .reveal .points > * {
            opacity: 1 !important;
            transform: none !important;
          }`}</style>
        </noscript>
      </head>
      <body>{children}</body>
    </html>
  );
}
