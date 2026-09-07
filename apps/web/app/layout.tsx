import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "BookTranslate — профессиональный перевод технических книг",
  description:
    "Профессиональный перевод технических книг и документации: терминология решается до перевода, каталог справок по незнакомым словам, проверки на каждом сегменте и сборка обратно в исходный файл. Для студентов и для компаний.",
  openGraph: {
    title: "BookTranslate — профессиональный перевод технических книг",
    description:
      "Термины решаются до перевода, числа и обозначения не разъезжаются, книга собирается обратно в свой формат со всем оформлением.",
    locale: "ru_RU",
    type: "website",
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
