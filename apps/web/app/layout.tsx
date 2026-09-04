import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "BookTranslate — перевод технической документации",
  description:
    "Платформа перевода технической документации: разбор исходника до перевода, единая терминология, проверяемое качество на каждом сегменте.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru">
      <body>{children}</body>
    </html>
  );
}
