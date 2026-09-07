import Link from "next/link";
import type { ReactNode } from "react";

/* Обрамление страниц входа и регистрации.

   Слева — то же обещание, что на главной: человек, дошедший до формы, не
   должен думать, туда ли он попал. Справа — форма и ничего больше. */
export function AuthShell({
  title,
  lead,
  footer,
  children,
}: {
  title: string;
  lead: string;
  footer: { text: string; href: string; link: string };
  children: ReactNode;
}) {
  return (
    <div className="auth">
      <aside className="auth__side stage">
        <div className="auth__side-inner">
          <Link className="logo" href="/">
            <span className="logo__mark" aria-hidden="true">
              📖
            </span>
            <span>
              BookTranslate<sup className="logo__ai">AI</sup>
            </span>
          </Link>

          <div>
            <h2>Перевод, который можно проверить построчно</h2>
            <ul className="points">
              <li>
                <i aria-hidden="true">🗂</i>
                <span>Термины решаются до перевода и держатся по всей книге</span>
              </li>
              <li>
                <i aria-hidden="true">🧪</i>
                <span>Шесть проверок на каждом сегменте: числа, единицы, термины</span>
              </li>
              <li>
                <i aria-hidden="true">📦</i>
                <span>DOCX, EPUB и HTML возвращаются в своём формате</span>
              </li>
            </ul>
          </div>

          <p className="muted">Данные рабочих пространств изолированы друг от друга.</p>
        </div>
      </aside>

      <main className="auth__main">
        <div className="auth__card">
          <h1>{title}</h1>
          <p className="lead">{lead}</p>
          {children}
          <p className="auth__foot">
            {footer.text} <Link href={footer.href}>{footer.link}</Link>
          </p>
        </div>
      </main>
    </div>
  );
}
