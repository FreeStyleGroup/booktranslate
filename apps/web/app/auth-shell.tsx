import Link from "next/link";
import type { ReactNode } from "react";

import { CONTACT_EMAIL } from "./contacts";
import { dictionary } from "./i18n";
import { localePath, type Locale } from "./i18n/config";

/* Обрамление страниц входа и регистрации.

   Слева — то же обещание, что на главной: человек, дошедший до формы, не
   должен думать, туда ли он попал. Справа — форма и ничего больше. */
export function AuthShell({
  lang,
  path,
  title,
  lead,
  footer,
  children,
}: {
  lang: Locale;
  /** Свой адрес без языковой приставки — чтобы увести на ту же страницу
   *  на другом языке. Шапки с переключателем здесь нет, а приходят сюда и
   *  по прямой ссылке. */
  path: string;
  title: string;
  lead: string;
  footer: { text: string; href: string; link: string };
  children: ReactNode;
}) {
  const t = dictionary(lang);
  const home = localePath(lang, "/");
  const other: Locale = lang === "ru" ? "en" : "ru";

  return (
    <div className="auth">
      <aside className="auth__side stage">
        <div className="auth__side-inner">
          <Link className="logo" href={home}>
            <span className="logo__mark" aria-hidden="true">
              📖
            </span>
            <span>
              BookTranslate<sup className="logo__ai">AI</sup>
            </span>
          </Link>

          <div>
            <h2>{t.auth.promise}</h2>
            <ul className="points">
              {t.auth.points.map((point) => (
                <li key={point.text}>
                  <i aria-hidden="true">{point.icon}</i>
                  <span>{point.text}</span>
                </li>
              ))}
            </ul>
          </div>

          <p className="muted">{t.auth.isolation}</p>
        </div>
      </aside>

      <main className="auth__main">
        {/* Логотип для узких экранов: там боковая колонка скрыта вместе
            со своим логотипом, и страница входа оставалась без единого
            признака, куда человек попал. */}
        <Link className="logo auth__logo" href={home}>
          <span className="logo__mark" aria-hidden="true">
            📖
          </span>
          <span>
            BookTranslate<sup className="logo__ai">AI</sup>
          </span>
        </Link>

        <div className="auth__card">
          <h1>{title}</h1>
          <p className="lead">{lead}</p>
          {children}
          <p className="auth__foot">
            {footer.text} <Link href={footer.href}>{footer.link}</Link>
          </p>
        </div>

        {/* Две подписи одним блоком: колонка — сетка, и каждая строка,
            поставленная в неё отдельно, получает свой ряд во всю высоту и
            уезжает от формы на полэкрана. */}
        <div className="auth__bottom">
          {/* Адрес почты под формой: тому, кто не может войти, нужен живой
              человек, а не ещё одна кнопка. */}
          <p className="auth__contact">
            {t.auth.trouble} <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>
          </p>

          {/* Свой шапки у страниц входа нет, а приходят на них и по прямой
              ссылке: без этой строки вернуться к своему языку нечем. */}
          <p className="auth__contact">
            <Link href={localePath(other, path)} hrefLang={other}>
              {t.auth.otherLanguage}
            </Link>
          </p>
        </div>
      </main>
    </div>
  );
}
