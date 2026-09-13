/* Главная страница продукта — одна на оба языка.
 *
 * Всё, что человек читает, приходит из словаря (`app/i18n`) — включая
 * пример разбора книги: на русской странице книгу переводят с английского
 * на русский, на английской наоборот. Здесь остаётся только то, что
 * текстом не является: цвета плашек и значки.
 *
 * Ссылки строятся через `localePath`, а не пишутся строкой: «/login» на
 * английской странице увёл бы человека обратно в русскую половину, и
 * заметить это можно, только пройдя весь путь до конца.
 */

import { CONTACT_EMAIL } from "./contacts";
import { dictionary } from "./i18n";
import { localePath, type Locale } from "./i18n/config";
import type { DemoMark, DemoVerdict } from "./i18n/ru";
import { LangSwitch } from "./lang-switch";
import { MobileMenu } from "./mobile-menu";
import { ThemeToggle } from "./theme-toggle";
import { Reveal } from "./reveal";
import { SiteSchema } from "./site-schema";

const CHIP: Record<DemoVerdict, string> = {
  ok: "chip chip--ok",
  warn: "chip chip--warn",
  danger: "chip chip--danger",
  info: "chip chip--info",
};

/** Цвет плашки проверки. Её текст лежит в словаре под тем же ключом. */
const MARKS: Record<DemoMark, DemoVerdict> = {
  checked: "ok",
  memory: "ok",
  term: "warn",
  numbers: "danger",
};

/** Форматы: имена — данные, а «принимаем» и «переписывается по месту» —
 *  слова, и они приходят из словаря по этим ключам. */
const FORMATS: {
  name: string;
  input: "accepted";
  output: "inPlace" | "asWord" | "asText" | "plainText";
}[] = [
  { name: "DOCX", input: "accepted", output: "inPlace" },
  { name: "EPUB", input: "accepted", output: "inPlace" },
  { name: "HTML", input: "accepted", output: "inPlace" },
  { name: "PDF", input: "accepted", output: "asWord" },
  { name: "Markdown", input: "accepted", output: "asText" },
  { name: "TXT", input: "accepted", output: "plainText" },
];

/** Значки шагов в строке «Книга → Термины → …»: данные, не текст. */
const FLOW_ICONS = ["📚", "🗂", "🤖", "🧪", "📖"];

export function Landing({ lang }: { lang: Locale }) {
  const t = dictionary(lang);
  const href = (path: string): string => localePath(lang, path);

  return (
    <>
      <SiteSchema
        lang={lang}
        faq={t.faq.items}
        features={[...t.outcomes.items, ...t.quality.features].map((item) => item.title)}
      />

      <header className="top">
        <div className="wrap top__inner">
          <div className="logo">
            <span className="logo__mark" aria-hidden="true">
              📖
            </span>
            <span>
              BookTranslate<sup className="logo__ai">AI</sup>
            </span>
          </div>
          <div className="top__pill">
            <nav className="nav">
              <a href="#how">{t.nav.how}</a>
              <a href="#terms">{t.nav.terms}</a>
              <a href="#who">{t.nav.who}</a>
              <a href="#formats">{t.nav.formats}</a>
              <a href="#price">{t.nav.price}</a>
              <a href="#faq">{t.nav.faq}</a>
            </nav>
            <LangSwitch label={t.nav.language} />
            <ThemeToggle className="top__theme" label={t.nav.theme} />
            {/* На узких экранах эти две кнопки уезжают в меню: вместе с
                логотипом и темой они в полосу не помещаются. */}
            <a className="btn btn--ghost btn--small top__enter" href={href("/login")}>
              {t.nav.login}
            </a>
            <a className="btn btn--primary btn--small top__enter" href={href("/register")}>
              {t.nav.register} <i aria-hidden="true">↗</i>
            </a>
            <MobileMenu lang={lang} nav={t.nav} />
          </div>
        </div>
      </header>

      <main className="page">
        <section>
          <div className="aurora" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
          <div className="hero__grid" aria-hidden="true" />
          <div className="wrap hero">
            <Reveal>
              <p className="eyebrow">
                <span aria-hidden="true">🤖</span> {t.hero.eyebrow}
              </p>
              <h1>
                {t.hero.titleBefore} <span className="accent">{t.hero.titleAccent}</span>{" "}
                <span className="emoji" aria-hidden="true">
                  🔥
                </span>
              </h1>
              <p className="lead">{t.hero.lead}</p>
              <p className="flow">
                {t.hero.flow.map((step, index) => (
                  <Step
                    key={step}
                    icon={FLOW_ICONS[index] ?? ""}
                    title={step}
                    last={index === t.hero.flow.length - 1}
                  />
                ))}
              </p>
              <div className="hero__actions">
                <a className="btn btn--primary" href="#start">
                  {t.hero.start} <i aria-hidden="true">↗</i>
                </a>
                <a className="btn btn--ghost" href="#how">
                  {t.hero.more}
                </a>
              </div>
              <p className="hero__note">{t.hero.note}</p>
            </Reveal>

            <div className="showcase">
              <div className="showcase__inner">
                <div className="panel">
                  <div className="panel__bar">
                    <span className="panel__dots" aria-hidden="true">
                      <span />
                      <span />
                      <span />
                    </span>
                    <span className="panel__file">{t.demo.file}</span>
                    <span>{t.demo.place}</span>
                  </div>
                  <div className="panel__head">
                    <span>{t.demo.number}</span>
                    <span>{t.demo.source}</span>
                    <span>{t.demo.target}</span>
                    <span>{t.demo.check}</span>
                  </div>
                  {t.demo.segments.map((segment) => (
                    <div className="seg" key={segment.no}>
                      <span className="seg__no">{segment.no}</span>
                      <span className="seg__src">{segment.src}</span>
                      <span className="seg__dst">{segment.dst}</span>
                      <span>
                        <span className={CHIP[MARKS[segment.mark]]}>
                          {t.demo.verdicts[segment.mark]}
                        </span>
                      </span>
                    </div>
                  ))}
                  <div className="panel__foot">
                    <span aria-hidden="true">✍️</span>
                    <span>{t.demo.foot}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="surface">
          <div className="wrap">
            <Reveal>
              <div className="section__head section__head--center">
                <h2>{t.outcomes.title}</h2>
                <p className="lead">{t.outcomes.lead}</p>
              </div>
              <div className="grid grid--3">
                {t.outcomes.items.map((item) => (
                  <article className="card" key={item.title}>
                    <div className="card__mark" aria-hidden="true">
                      {item.icon}
                    </div>
                    <h3>{item.title}</h3>
                    <p>{item.text}</p>
                  </article>
                ))}
              </div>
            </Reveal>
          </div>
        </section>

        <div className="divider" aria-hidden="true">
          <span>📚</span>
        </div>

        <section id="how">
          <div className="wrap">
            <Reveal>
              <div className="section__head section__head--center">
                <p className="eyebrow">
                  <span aria-hidden="true">⚙️</span> {t.steps.eyebrow}
                </p>
                <h2>{t.steps.title}</h2>
                <p className="lead">{t.steps.lead}</p>
              </div>
              <div className="grid grid--3">
                {t.steps.items.map((step, index) => (
                  <article className="card" key={step.title}>
                    <div className="card__mark" aria-hidden="true">
                      {step.icon}
                    </div>
                    <span className="card__num">0{index + 1}</span>
                    <h3>{step.title}</h3>
                    <p>{step.text}</p>
                  </article>
                ))}
              </div>
            </Reveal>
          </div>
        </section>

        <section id="terms" className="stage">
          <div className="wrap split">
            <Reveal className="split__text">
              <p className="eyebrow">
                <span aria-hidden="true">🗂</span> {t.terminology.eyebrow}
              </p>
              <h2>{t.terminology.title}</h2>
              <p className="lead">{t.terminology.lead}</p>
              <ul className="points">
                {t.terminology.points.map((point) => (
                  <li key={point.strong}>
                    <i aria-hidden="true">{point.icon}</i>
                    <span>
                      <b>{point.strong}</b>
                      {point.rest}
                    </span>
                  </li>
                ))}
              </ul>
            </Reveal>

            <Reveal>
              <div className="panel panel--flat">
                <div className="panel__bar">
                  <span className="panel__file">{t.terminology.candidates}</span>
                  <span>{t.terminology.candidatesCount}</span>
                </div>
                {t.terminology.candidateList.map((item) => (
                  <div className="seg seg--terms" key={item.term}>
                    <span className="seg__dst">{item.term}</span>
                    <span className="seg__no">{item.freq}×</span>
                    <span>
                      <span className={CHIP[item.verdict]}>{item.note}</span>
                    </span>
                  </div>
                ))}
              </div>

              <div className="entry">
                <div className="entry__top">
                  <span className="entry__term">{t.terminology.entryTerm}</span>
                  <span className="entry__arrow" aria-hidden="true">
                    →
                  </span>
                  <span className="entry__target">{t.terminology.entryTarget}</span>
                  <span className={CHIP.info}>{t.terminology.entryBadge}</span>
                </div>
                <p>{t.terminology.entryText}</p>
                <p className="entry__src">
                  <span aria-hidden="true">🔗</span> {t.terminology.entrySource}
                </p>
              </div>
            </Reveal>
          </div>
        </section>

        <div className="divider" aria-hidden="true">
          <span>🤖</span>
        </div>

        <section id="who">
          <div className="wrap">
            <Reveal>
              <div className="section__head section__head--center">
                <p className="eyebrow">
                  <span aria-hidden="true">🎓</span> {t.audience.eyebrow}
                </p>
                <h2>{t.audience.title}</h2>
                <p className="lead">{t.audience.lead}</p>
              </div>
              <div className="grid grid--2">
                {t.audience.items.map((item) => (
                  <article className="card" key={item.title}>
                    <div className="card__mark" aria-hidden="true">
                      {item.icon}
                    </div>
                    <h3>{item.title}</h3>
                    <p className="card__lead">{item.lead}</p>
                    <ul className="points">
                      {item.points.map((point) => (
                        <li key={point}>
                          <i aria-hidden="true">·</i>
                          <span>{point}</span>
                        </li>
                      ))}
                    </ul>
                  </article>
                ))}
              </div>
            </Reveal>
          </div>
        </section>

        <div className="divider" aria-hidden="true">
          <span>📖</span>
        </div>

        <section className="surface">
          <div className="wrap split split--flip">
            <Reveal className="split__text">
              <p className="eyebrow">
                <span aria-hidden="true">🧪</span> {t.quality.eyebrow}
              </p>
              <h2>{t.quality.title}</h2>
              <p className="lead">{t.quality.lead}</p>
              <ul className="points">
                {t.quality.checks.map((check) => (
                  <li key={check}>
                    <i aria-hidden="true">✓</i>
                    <span>{check}</span>
                  </li>
                ))}
              </ul>
            </Reveal>

            <Reveal>
              <div className="grid">
                {t.quality.features.map((feature) => (
                  <article className="card" key={feature.title}>
                    <div className="card__mark" aria-hidden="true">
                      {feature.icon}
                    </div>
                    <h3>{feature.title}</h3>
                    <p>{feature.text}</p>
                  </article>
                ))}
              </div>
            </Reveal>
          </div>
        </section>

        <section id="formats" className="stage">
          <div className="wrap split">
            <Reveal className="split__text">
              <p className="eyebrow">
                <span aria-hidden="true">📦</span> {t.formats.eyebrow}
              </p>
              <h2>{t.formats.title}</h2>
              <p className="lead">{t.formats.lead}</p>
              <p className="muted">{t.formats.note}</p>
            </Reveal>

            <Reveal>
              <div className="panel panel--flat">
                <div className="panel__head panel__head--formats">
                  <span>{t.formats.columns.format}</span>
                  <span>{t.formats.columns.input}</span>
                  <span>{t.formats.columns.output}</span>
                </div>
                {FORMATS.map((format) => (
                  <div className="seg seg--formats" key={format.name}>
                    <span className="seg__dst">{format.name}</span>
                    <span className="seg__src">{t.formats[format.input]}</span>
                    <span className="seg__src">{t.formats[format.output]}</span>
                  </div>
                ))}
              </div>
            </Reveal>
          </div>
        </section>

        <section id="price">
          <div className="wrap split split--flip">
            <Reveal className="split__text">
              <p className="eyebrow">
                <span aria-hidden="true">💸</span> {t.price.eyebrow}
              </p>
              <h2>{t.price.title}</h2>
              <p className="lead">{t.price.lead}</p>
              <p className="muted">{t.price.note}</p>
            </Reveal>

            <Reveal>
              <div className="bill">
                {t.price.bill.map((row) => (
                  <div className="bill__row" key={row.name}>
                    <span>{row.name}</span>
                    <b>{row.value}</b>
                  </div>
                ))}
                <div className="bill__row bill__row--total">
                  <span>{t.price.total}</span>
                  <b>≈ $13</b>
                </div>
              </div>
            </Reveal>
          </div>
        </section>

        <section id="faq" className="surface">
          <div className="wrap">
            <Reveal>
              <div className="section__head section__head--center">
                <h2>{t.faq.title}</h2>
              </div>
              <div className="faq">
                {t.faq.items.map((item) => (
                  <details key={item.q}>
                    <summary>{item.q}</summary>
                    <p>{item.a}</p>
                  </details>
                ))}
              </div>
            </Reveal>
          </div>
        </section>

        <section id="start" className="stage">
          <div className="wrap wrap--narrow cta">
            <Reveal>
              <h2>{t.cta.title}</h2>
              <p className="lead">{t.cta.lead}</p>
              <div className="hero__actions">
                {/* Регистрация, а не письмо: заявка через форму заводит
                    рабочее пространство и попадает к администратору, а
                    письмо в ящик теряется и ничего в системе не создаёт. */}
                <a className="btn btn--primary" href={href("/register")}>
                  {t.cta.register} <i aria-hidden="true">↗</i>
                </a>
                <a className="btn btn--ghost" href="#how">
                  {t.cta.again}
                </a>
              </div>
            </Reveal>
          </div>
        </section>
      </main>

      <footer className="wrap foot">
        <span>BookTranslate · {t.meta.tagline}</span>
        <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>
      </footer>
    </>
  );
}

/** Звено строки «Книга → Термины → …» вместе со стрелкой после него. */
function Step({ icon, title, last }: { icon: string; title: string; last: boolean }) {
  return (
    <>
      <b>
        <span aria-hidden="true">{icon}</span> {title}
      </b>
      {!last && <i aria-hidden="true">→</i>}
    </>
  );
}
