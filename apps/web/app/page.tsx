/* Главная страница продукта.

   Примеры интерфейса ниже заданы прямо здесь: это иллюстрации к тексту, а не
   чьи-то данные. Когда страница начнёт показывать реальный проект, константы
   заменятся запросом — разметка останется та же. */

import type { Metadata } from "next";

import { CONTACT_EMAIL, TAGLINE } from "./contacts";
import { LangSwitch } from "./lang-switch";
import { MobileMenu } from "./mobile-menu";
import { ThemeToggle } from "./theme-toggle";
import { Reveal } from "./reveal";
import { SiteSchema } from "./site-schema";

// Остальное — заголовок, описание, Open Graph — наследуется от корневой
// разметки; здесь только адрес, по которому эту страницу считать главной.
export const metadata: Metadata = {
  alternates: { canonical: "/" },
};

type Verdict = "ok" | "warn" | "danger" | "info";

const CHIP: Record<Verdict, string> = {
  ok: "chip chip--ok",
  warn: "chip chip--warn",
  danger: "chip chip--danger",
  info: "chip chip--info",
};

const SEGMENTS: {
  no: number;
  src: string;
  dst: string;
  verdict: Verdict;
  note: string;
}[] = [
  {
    no: 214,
    src: "Send the request with the header Idempotency-Key set to a UUID.",
    dst: "Отправьте запрос с заголовком Idempotency-Key, содержащим UUID.",
    verdict: "ok",
    note: "Проверено",
  },
  {
    no: 215,
    src: "Do not exceed the maximum pool size of 32 connections.",
    dst: "Не превышайте предельный размер пула — 32 соединения.",
    verdict: "ok",
    note: "Из памяти",
  },
  {
    no: 216,
    src: "The primary node must be restarted together with its replica set.",
    dst: "Главный узел перезапускается вместе с набором реплик.",
    verdict: "warn",
    note: "Термин",
  },
  {
    no: 217,
    src: "Refer to section 7.3 for the full list of environment variables.",
    dst: "Полный список переменных окружения приведён в разделе 7.3.",
    verdict: "ok",
    note: "Проверено",
  },
  {
    // Число в переводе не то, что в исходнике: ровно та ошибка, которую
    // ищет проверка чисел, и ровно та, которую человек не замечает.
    no: 218,
    src: "The access token expires after 3600 seconds.",
    dst: "Токен доступа истекает через 360 секунд.",
    verdict: "danger",
    note: "Числа",
  },
];

const OUTCOMES = [
  {
    icon: "📖",
    title: "Тот же файл, другой язык",
    text: "DOCX, EPUB и HTML переписываются по месту: оформление, картинки, таблицы, оглавление и стили остаются на своих местах. Верстать заново не придётся.",
  },
  {
    icon: "🗂",
    title: "Одна терминология на всю книгу",
    text: "Термины решаются до перевода и держатся во всех главах и во всех томах серии. Не «корпус» в одной главе и «кожух» в другой.",
  },
  {
    icon: "🧪",
    title: "Видно, что перечитать",
    text: "Каждый сегмент проходит шесть проверок. Спорное помечено и собрано в отдельную очередь — вычитывать всю книгу подряд не нужно.",
  },
];

const STEPS = [
  {
    icon: "📥",
    title: "Загружаете книгу",
    text: "DOCX, EPUB, HTML, Markdown или текст. Документ раскладывается на сегменты — заголовки, абзацы, пункты списков, ячейки таблиц — и структура запоминается.",
  },
  {
    icon: "🗂",
    title: "Договариваетесь о терминах",
    text: "Система собирает то, что в книге повторяется, и показывает списком. Вы решаете один раз; пока остаются нерешённые слова, перевод не начинается.",
  },
  {
    icon: "🔍",
    title: "Незнакомое ищется само",
    text: "По непонятному слову приходит справка: определение, принятый в отрасли перевод, расшифровка сокращения и адреса источников. Найденное остаётся в вашем каталоге.",
  },
  {
    icon: "🤖",
    title: "Перевод с ограничениями",
    text: "Модель получает сегмент, соседние абзацы, заголовок раздела и термины — как требование, а не как подсказку. Повторы и совпадения с памятью не переводятся заново.",
  },
  {
    icon: "🧪",
    title: "Проверка и правка",
    text: "Числа, единицы, подстановки, употребление терминов, раскрытие сокращений. Правка одного сегмента расходится по всем его повторам; принимает работу человек.",
  },
  {
    icon: "📦",
    title: "Забираете книгу",
    text: "Готовый файл того же формата. Недопереведённый документ не отдаётся молча — вы увидите, сколько блоков осталось незакрытыми.",
  },
];

const AUDIENCE = [
  {
    icon: "🎓",
    title: "Студентам и исследователям",
    lead: "Учебник, монография, статья, диплом, глава книги.",
    points: [
      "Термины вашей области решаются один раз и держатся по всей работе",
      "Формулы, обозначения и ссылки на источники не разъезжаются",
      "Справка по незнакомому слову — с адресом, откуда это известно",
      "Расход виден по каждому запуску: никаких сюрпризов в конце",
    ],
  },
  {
    icon: "🏭",
    title: "Компаниям и бюро переводов",
    lead: "Тома документации, серии руководств, локализация продукта.",
    points: [
      "Единая терминология по всем томам и по всем переводчикам",
      "Память переводов: второй том серии обходится дешевле первого",
      "Роли, разграничение доступа и изоляция данных заказчиков",
      "Отчёт по документу: что закрыто памятью, что ушло модели, сколько стоило",
    ],
  },
];

const FEATURES = [
  {
    icon: "🧠",
    title: "Память переводов",
    text: "Повторы внутри книги и совпадения с прошлыми заказами подставляются без обращения к модели. Одинаковое звучит одинаково.",
  },
  {
    icon: "✍️",
    title: "Правка расходится по повторам",
    text: "Поправив предупреждение один раз, вы правите его во всех сорока местах — кроме тех, что уже принял человек.",
  },
  {
    icon: "🔗",
    title: "Источник у каждого решения",
    text: "Адрес, по которому термин посмотрели, сохраняется вместе с решением. Спор о термине через месяц не начинается заново.",
  },
];

const CANDIDATES: {
  term: string;
  freq: number;
  verdict: Verdict;
  note: string;
}[] = [
  { term: "replica set", freq: 34, verdict: "ok", note: "набор реплик" },
  { term: "rate limit", freq: 21, verdict: "ok", note: "ограничение частоты" },
  { term: "TLS", freq: 18, verdict: "info", note: "раскрыть при первом" },
  { term: "cold start", freq: 9, verdict: "warn", note: "ждёт решения" },
  { term: "RFC 7519", freq: 4, verdict: "ok", note: "не переводится" },
];

const CHECKS = [
  "Числа, единицы измерения и обозначения — потерянные и появившиеся",
  "Подстановки и разметка внутри текста: {0}, %s, теги",
  "Употребление терминов из словаря в заданной форме",
  "Раскрытие сокращения при первом употреблении в документе",
  "Непереведённые куски: перевод, совпавший с исходником",
  "Пустой перевод там, где в исходнике есть текст",
];

const FORMATS = [
  { name: "DOCX", input: "принимаем", output: "переписывается по месту" },
  { name: "EPUB", input: "принимаем", output: "переписывается по месту" },
  { name: "HTML", input: "принимаем", output: "переписывается по месту" },
  { name: "Markdown", input: "принимаем", output: "Markdown или текст" },
  { name: "TXT", input: "принимаем", output: "текст" },
];

const BILL = [
  { name: "Сегментов в книге", value: "12 480" },
  { name: "Закрыто памятью и повторами", value: "3 902" },
  { name: "Ушло модели", value: "8 578" },
  { name: "Прочитано из кэша — десятая часть цены", value: "1,9 млн токенов" },
];

const FAQ = [
  {
    q: "Это заменит переводчика?",
    a: "Нет, и не пытается. Машина закрывает то, что человек делает медленно и с ошибками: держит термины одинаковыми на восьмистах страницах, сверяет числа и единицы, подставляет повторы. Решение по спорному месту остаётся за человеком, и работа считается сделанной только после его приёмки.",
  },
  {
    q: "Что будет с формулами, обозначениями и артикулами?",
    a: "Они переносятся без изменений — это отдельное правило перевода и отдельная проверка на выходе. Обозначения (σ, σᵤ, LT1) можно завести в словарь самостоятельными записями: подменённый индекс не читается как опечатка, он меняет смысл формулы.",
  },
  {
    q: "У нас свой глоссарий. Его можно загрузить?",
    a: "Да: CSV, TSV, TBX и рабочие реестры терминологии в DOCX. Загруженное не перезаписывает то, что заводил человек, — такие записи попадают в пропущенные с причиной, а не теряются молча.",
  },
  {
    q: "Сколько занимает перевод книги?",
    a: "Дольше всего идёт не перевод, а решение по терминам — это работа человека, и ускорять её за счёт качества бессмысленно. Сам перевод считается пачками сегментов; повторы и совпадения с памятью не пересчитываются вовсе.",
  },
  {
    q: "Что с конфиденциальностью?",
    a: "Данные организаций изолированы друг от друга на уровне модели данных, а не настроек интерфейса. Внешний поиск справок по умолчанию выключен — он ходит в интернет. Провайдер перевода выбирается настройкой, включая собственное развёртывание модели там, где текст нельзя отдавать наружу.",
  },
  {
    q: "Можно перевести только одну главу?",
    a: "Да. Документ переводится по частям, повторный запуск не трогает то, что вы уже поправили и приняли. Память переводов при этом накапливается — следующая глава и следующая книга пойдут дешевле и согласованнее.",
  },
];

export default function Home() {
  return (
    <>
      <SiteSchema faq={FAQ} features={[...OUTCOMES, ...FEATURES].map((item) => item.title)} />

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
              <a href="#how">Как работает</a>
              <a href="#terms">Терминология</a>
              <a href="#who">Кому</a>
              <a href="#formats">Форматы</a>
              <a href="#price">Стоимость</a>
              <a href="#faq">Вопросы</a>
            </nav>
            <LangSwitch />
            <ThemeToggle className="top__theme" />
            {/* На узких экранах эти две кнопки уезжают в меню: вместе с
                логотипом и темой они в полосу не помещаются. */}
            <a className="btn btn--ghost btn--small top__enter" href="/login">
              Войти
            </a>
            <a className="btn btn--primary btn--small top__enter" href="/register">
              Регистрация <i aria-hidden="true">↗</i>
            </a>
            <MobileMenu />
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
                <span aria-hidden="true">🤖</span> Профессиональный перевод
                технических книг и документации
              </p>
              <h1>
                Перевод, который можно{" "}
                <span className="accent">проверить построчно</span>{" "}
                <span className="emoji" aria-hidden="true">
                  🔥
                </span>
              </h1>
              <p className="lead">
                Книгу на восемьсот страниц нельзя просто «прогнать через
                переводчик»: цена ошибки здесь не стиль, а срок жизни токена,
                предел частоты и имя поля в запросе. Сначала разбираем документ и
                договариваемся о терминах, потом переводим, потом проверяем — и
                собираем обратно в тот же файл, со всем оформлением.
              </p>
              <p className="flow">
                <b>
                  <span aria-hidden="true">📚</span> Книга
                </b>
                <i aria-hidden="true">→</i>
                <b>
                  <span aria-hidden="true">🗂</span> Термины
                </b>
                <i aria-hidden="true">→</i>
                <b>
                  <span aria-hidden="true">🤖</span> Перевод
                </b>
                <i aria-hidden="true">→</i>
                <b>
                  <span aria-hidden="true">🧪</span> Проверка
                </b>
                <i aria-hidden="true">→</i>
                <b>
                  <span aria-hidden="true">📖</span> Файл
                </b>
              </p>
              <div className="hero__actions">
                <a className="btn btn--primary" href="#start">
                  Перевести книгу <i aria-hidden="true">↗</i>
                </a>
                <a className="btn btn--ghost" href="#how">
                  Как это работает
                </a>
              </div>
              <p className="hero__note">
                Для дипломной работы и для серии руководств на десять томов —
                порядок работы один и тот же.
              </p>
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
                    <span className="panel__file">api-reference-v4.docx</span>
                    <span>раздел 7 · 218 из 1 240</span>
                  </div>
                  <div className="panel__head">
                    <span>№</span>
                    <span>Исходник</span>
                    <span>Перевод</span>
                    <span>Проверка</span>
                  </div>
                  {SEGMENTS.map((segment) => (
                    <div className="seg" key={segment.no}>
                      <span className="seg__no">{segment.no}</span>
                      <span className="seg__src">{segment.src}</span>
                      <span className="seg__dst">{segment.dst}</span>
                      <span>
                        <span className={CHIP[segment.verdict]}>
                          {segment.note}
                        </span>
                      </span>
                    </div>
                  ))}
                  <div className="panel__foot">
                    <span aria-hidden="true">✍️</span>
                    <span>
                      Правка сегмента 216 разошлась ещё по 39 таким же местам
                    </span>
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
                <h2>Что вы получаете</h2>
                <p className="lead">
                  Не «текст на другом языке», а готовую к работе книгу: в своём
                  формате, со своей терминологией и с понятным списком мест,
                  которые стоит перечитать.
                </p>
              </div>
              <div className="grid grid--3">
                {OUTCOMES.map((item) => (
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
                  <span aria-hidden="true">⚙️</span> Порядок работы
                </p>
                <h2>Шесть шагов вместо одного</h2>
                <p className="lead">
                  Разница с обычным машинным переводом — в том, что происходит
                  до и после самого перевода. Именно там живут ошибки, которые
                  читатель находит первым.
                </p>
              </div>
              <div className="grid grid--3">
                {STEPS.map((step, index) => (
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
                <span aria-hidden="true">🗂</span> Терминология
              </p>
              <h2>Сначала договориться, потом переводить</h2>
              <p className="lead">
                Слово, отданное модели на усмотрение, в сорока местах книги
                будет названо по-разному — а текст останется гладким, поэтому
                заметит это только читатель. Поэтому список того, что в книге
                повторяется, собирается заранее и решается один раз.
              </p>
              <ul className="points">
                <li>
                  <i aria-hidden="true">🚦</i>
                  <span>
                    <b>Перевод не начнётся</b>, пока в списке остаются
                    нерешённые слова. Обойти можно, но это осознанный шаг.
                  </span>
                </li>
                <li>
                  <i aria-hidden="true">🔍</i>
                  <span>
                    <b>Незнакомое ищется в сети</b> — с определением, принятым
                    переводом и адресами источников.
                  </span>
                </li>
                <li>
                  <i aria-hidden="true">♻️</i>
                  <span>
                    <b>Один раз на всю работу.</b> Выяснив, что такое basis
                    risk, вы знаете это и в следующей книге, и через год.
                  </span>
                </li>
                <li>
                  <i aria-hidden="true">🧾</i>
                  <span>
                    <b>Решаете вы.</b> Найденное — предложение, а не требование
                    к переводу.
                  </span>
                </li>
              </ul>
            </Reveal>

            <Reveal>
              <div className="panel panel--flat">
                <div className="panel__bar">
                  <span className="panel__file">Кандидаты в словарь</span>
                  <span>5 из 187</span>
                </div>
                {CANDIDATES.map((item) => (
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
                  <span className="entry__term">basis risk</span>
                  <span className="entry__arrow" aria-hidden="true">
                    →
                  </span>
                  <span className="entry__target">базисный риск</span>
                  <span className={CHIP.info}>справка из каталога</span>
                </div>
                <p>
                  Риск расхождения цены базового актива и производного
                  инструмента при хеджировании: базис меняется, и хедж
                  перестаёт быть полным.
                </p>
                <p className="entry__src">
                  <span aria-hidden="true">🔗</span> Источник сохраняется вместе
                  с решением
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
                  <span aria-hidden="true">🎓</span> Кому это нужно
                </p>
                <h2>И для студентов, и для серьёзных компаний</h2>
                <p className="lead">
                  Задача одна и та же: чтобы термины держались, числа не
                  разъезжались, а файл открылся таким же, каким был. Разница
                  только в объёме и в том, сколько человек над этим работает.
                </p>
              </div>
              <div className="grid grid--2">
                {AUDIENCE.map((item) => (
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
                <span aria-hidden="true">🧪</span> Качество
              </p>
              <h2>Шесть проверок на каждом сегменте</h2>
              <p className="lead">
                Проверки не оценивают красоту слога — они ловят то, что в
                технической книге стоит дорого и не бросается в глаза при
                чтении.
              </p>
              <ul className="points">
                {CHECKS.map((check) => (
                  <li key={check}>
                    <i aria-hidden="true">✓</i>
                    <span>{check}</span>
                  </li>
                ))}
              </ul>
            </Reveal>

            <Reveal>
              <div className="grid">
                {FEATURES.map((feature) => (
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
                <span aria-hidden="true">📦</span> Форматы
              </p>
              <h2>Книга возвращается книгой</h2>
              <p className="lead">
                EPUB — это не текст, а архив: обложка, стили, шрифты, картинки,
                опись и оглавление. Собрать такое заново из переведённых абзацев
                нельзя, поэтому оригинал переписывается по месту, а всё
                остальное переносится как есть.
              </p>
              <p className="muted">
                Любой из форматов можно забрать простым текстом или в
                Markdown — например чтобы вычитать в привычном редакторе.
              </p>
            </Reveal>

            <Reveal>
              <div className="panel panel--flat">
                <div className="panel__head panel__head--formats">
                  <span>Формат</span>
                  <span>Приём</span>
                  <span>Выгрузка</span>
                </div>
                {FORMATS.map((format) => (
                  <div className="seg seg--formats" key={format.name}>
                    <span className="seg__dst">{format.name}</span>
                    <span className="seg__src">{format.input}</span>
                    <span className="seg__src">{format.output}</span>
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
                <span aria-hidden="true">💸</span> Стоимость
              </p>
              <h2>Видно, за что заплачено</h2>
              <p className="lead">
                Каждый запуск отчитывается: сколько сегментов закрыто памятью и
                повторами, сколько ушло модели и во сколько это обошлось.
                Хранятся токены, а не рубли: цены меняются, а потраченное на эту
                книгу — исторический факт.
              </p>
              <p className="muted">
                Одинаковое предупреждение, встречающееся сорок раз, переводится
                один раз — не ради экономии, а чтобы в книге оно звучало
                одинаково. То, что за него платят один раз, — приятное
                следствие.
              </p>
            </Reveal>

            <Reveal>
              <div className="bill">
                {BILL.map((row) => (
                  <div className="bill__row" key={row.name}>
                    <span>{row.name}</span>
                    <b>{row.value}</b>
                  </div>
                ))}
                <div className="bill__row bill__row--total">
                  <span>Оценка стоимости запуска</span>
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
                <h2>Частые вопросы</h2>
              </div>
              <div className="faq">
                {FAQ.map((item) => (
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
              <h2>Начать перевод</h2>
              <p className="lead">
                Пришлите книгу или руководство — заведём рабочее пространство,
                разберём документ и покажем список терминов ещё до того, как
                будет потрачен первый рубль.
              </p>
              <div className="hero__actions">
                {/* Регистрация, а не письмо: заявка через форму заводит
                    рабочее пространство и попадает к администратору, а
                    письмо в ящик теряется и ничего в системе не создаёт. */}
                <a className="btn btn--primary" href="/register">
                  Зарегистрироваться <i aria-hidden="true">↗</i>
                </a>
                <a className="btn btn--ghost" href="#how">
                  Ещё раз про порядок работы
                </a>
              </div>
            </Reveal>
          </div>
        </section>
      </main>

      <footer className="wrap foot">
        <span>BookTranslate · {TAGLINE}</span>
        <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>
      </footer>
    </>
  );
}
