import type { Metadata } from "next";

import { SITE_NAME, SITE_URL } from "./contacts";
import { alternates, dictionary } from "./i18n";
import "./globals.css";

const ru = dictionary("ru");

export const metadata: Metadata = {
  // От этого адреса считаются канонические ссылки и адреса в Open Graph:
  // без него Next отдал бы их относительными, а поисковику относительный
  // канонический адрес ни о чём не говорит.
  metadataBase: new URL(SITE_URL),
  title: ru.meta.title,
  description: ru.meta.description,
  applicationName: SITE_NAME,
  alternates: alternates("ru", "/"),
  openGraph: {
    title: ru.meta.title,
    description: ru.meta.ogDescription,
    siteName: SITE_NAME,
    locale: ru.ogLocale,
    type: "website",
  },
  // Подтверждение прав на сайт в Яндекс.Вебмастере. Код — не секрет: он
  // и так виден в разметке каждой страницы, на этом проверка и построена.
  verification: {
    yandex: "163424560b1443f9",
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    // Язык разметки — русский: он основной и живёт на голых адресах.
    // Английская половина сайта помечает себя сама (`app/en/layout.tsx`):
    // `lang` — обычный атрибут, и вложенный узел перекрывает им документ.
    //
    // 🔥 data-scroll-behavior: у страницы плавная прокрутка (globals.css), и
    // при переходе между разделами Next прокручивал к верху с анимацией,
    // которую переход обрывал, — новая страница открывалась сдвинутой под
    // шапку. С атрибутом Next на время перехода выключает плавность.
    <html lang={ru.htmlLang} data-scroll-behavior="smooth">
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
