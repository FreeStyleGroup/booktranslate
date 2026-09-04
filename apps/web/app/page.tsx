/* Витрина продукта. Данные ниже — демонстрационные и заданы прямо здесь:
   бэкенда ещё нет, а страница уже должна показывать, как выглядит работа.
   Когда появится API, эти константы заменяются запросом — разметка та же. */

type Verdict = "ok" | "warn" | "danger";

const SEGMENTS: {
  no: number;
  src: string;
  dst: string;
  verdict: Verdict;
  note: string;
}[] = [
  {
    no: 214,
    src: "Tighten the retaining bolts to 42 N·m in a diagonal sequence.",
    dst: "Затяните стопорные болты моментом 42 Н·м крест-накрест.",
    verdict: "ok",
    note: "Проверено",
  },
  {
    no: 215,
    src: "Do not exceed the maximum inlet pressure of 16 bar.",
    dst: "Не превышайте максимальное давление на входе 16 бар.",
    verdict: "ok",
    note: "Проверено",
  },
  {
    no: 216,
    src: "The impeller shaft must be replaced together with the seal kit.",
    dst: "Вал крыльчатки заменяется вместе с комплектом уплотнений.",
    verdict: "warn",
    note: "Термин",
  },
  {
    no: 217,
    src: "Refer to section 7.3 for the wiring diagram of the control unit.",
    dst: "Схема подключения блока управления приведена в разделе 7.3.",
    verdict: "ok",
    note: "Проверено",
  },
  {
    no: 218,
    src: "Failure to observe this warning may result in severe injury.",
    dst: "Несоблюдение предупреждения может привести к тяжёлой травме.",
    verdict: "danger",
    note: "Требует эксперта",
  },
];

const STEPS = [
  {
    title: "Разбор исходника",
    text: "Документ раскладывается на структуру до перевода: разделы, таблицы, подписи к рисункам, единицы измерения, повторы. Видно, из чего он состоит и где риск.",
  },
  {
    title: "Терминология",
    text: "Глоссарий проекта собирается из самого документа и памяти переводов. Одно и то же понятие переводится одинаково во всех томах, а не как получится.",
  },
  {
    title: "Перевод сегментами",
    text: "Модель работает по сегментам с контекстом раздела и глоссарием. Числа, единицы, плейсхолдеры и перекрёстные ссылки переносятся без правки вручную.",
  },
  {
    title: "Проверка качества",
    text: "Каждый сегмент получает оценку: расхождение чисел, нарушение глоссария, протечка исходного языка, длина. Спорное уходит человеку, остальное идёт дальше.",
  },
];

const FEATURES = [
  {
    title: "Форматы техдокументации",
    text: "PDF, DOCX, HTML, Markdown и XLIFF — то, в чём приходят руководства, а не только книги.",
  },
  {
    title: "Память переводов",
    text: "Повторы и близкие совпадения подставляются из предыдущих томов. Второй том дешевле первого.",
  },
  {
    title: "Рабочее место редактора",
    text: "Две колонки, фильтр по проблемным сегментам, правка с сохранением истории и автора.",
  },
  {
    title: "Изолированные рабочие пространства",
    text: "Организация, проекты, роли и разграничение доступа заложены с первого дня, а не привинчиваются потом.",
  },
];

const STATS = [
  { value: "5", label: "форматов на входе" },
  { value: "6", label: "проверок на сегмент" },
  { value: "1", label: "глоссарий на весь проект" },
  { value: "0", label: "правок ради нумерации" },
];

const ROADMAP: { state: "done" | "now" | "next"; text: string }[] = [
  { state: "done", text: "Репозиторий, витрина и автодеплой" },
  { state: "now", text: "Модель данных: организации, проекты, документы, сегменты" },
  { state: "next", text: "Приём документов: PDF, DOCX, HTML, Markdown, XLIFF" },
  { state: "next", text: "Разбор исходника и сборка глоссария проекта" },
  { state: "next", text: "Перевод сегментами и оценки качества" },
  { state: "next", text: "Рабочее место редактора" },
];

const CHIP_CLASS: Record<Verdict, string> = {
  ok: "chip chip--ok",
  warn: "chip chip--warn",
  danger: "chip chip--danger",
};

export default function Home() {
  return (
    <>
      <header className="top">
        <div className="wrap top__inner">
          <div className="logo">
            <span className="logo__mark">BT</span>
            <span>BookTranslate</span>
          </div>
          <nav className="nav">
            <a href="#how">Как устроено</a>
            <a href="#workspace">Рабочее место</a>
            <a href="#features">Возможности</a>
            <a href="#status">Статус</a>
          </nav>
          <a className="btn btn--primary" href="#status">
            Следить за разработкой
          </a>
        </div>
      </header>

      <main>
        <section>
          <div className="wrap hero">
            <div>
              <p className="eyebrow">Перевод технической документации</p>
              <h1>Перевод, который можно проверить построчно</h1>
              <p className="lead">
                Руководство на восемьсот страниц нельзя «прогнать через
                переводчик»: цена ошибки — не стиль, а момент затяжки, давление
                и класс защиты. Платформа разбирает документ до перевода,
                держит единую терминологию по всем томам и показывает, какой
                сегмент проверен машиной, а какой обязан посмотреть человек.
              </p>
              <div className="hero__actions">
                <a className="btn btn--primary" href="#workspace">
                  Посмотреть рабочее место
                </a>
                <a className="btn btn--ghost" href="#how">
                  Как это работает
                </a>
              </div>
              <p className="hero__note">
                Проект в разработке. На этой странице — интерфейс на
                демонстрационных данных.
              </p>
            </div>

            <div className="editor" aria-hidden="true">
              <div className="editor__bar">
                <span className="editor__file">pump-manual-v4.pdf</span>
                <span>раздел 7 · 218 из 1 240 сегментов</span>
              </div>
              <div className="editor__head">
                <span>№</span>
                <span>Исходник</span>
                <span>Перевод</span>
                <span>Проверка</span>
              </div>
              {SEGMENTS.map((s) => (
                <div className="seg" key={s.no}>
                  <span className="seg__no">{s.no}</span>
                  <span className="seg__src">{s.src}</span>
                  <span className="seg__dst">{s.dst}</span>
                  <span>
                    <span className={CHIP_CLASS[s.verdict]}>{s.note}</span>
                  </span>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section id="how">
          <div className="wrap">
            <h2>Четыре шага вместо одного</h2>
            <p className="lead">
              Разница с обычным машинным переводом в том, что происходит до и
              после самого перевода.
            </p>
            <div className="grid grid--4">
              {STEPS.map((step, i) => (
                <article className="card" key={step.title}>
                  <div className="card__num">{i + 1}</div>
                  <h3>{step.title}</h3>
                  <p>{step.text}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section id="workspace">
          <div className="wrap">
            <h2>Рабочее место редактора</h2>
            <p className="lead">
              Редактор видит не сплошной текст, а сегменты с историей: что
              подставила память переводов, что перевела модель, что проверил
              человек. Спорные места собираются в отдельный список — их можно
              разобрать за один проход.
            </p>
            <div className="grid grid--4">
              {STATS.map((stat) => (
                <div className="stat" key={stat.label}>
                  <div className="stat__value">{stat.value}</div>
                  <div className="stat__label">{stat.label}</div>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section id="features">
          <div className="wrap">
            <h2>Что уже спроектировано</h2>
            <div className="grid grid--4">
              {FEATURES.map((f) => (
                <article className="card" key={f.title}>
                  <h3>{f.title}</h3>
                  <p>{f.text}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section id="status" className="status">
          <div className="wrap">
            <h2>Где мы сейчас</h2>
            <p className="lead">
              Страница обновляется вместе с кодом: каждый выпуск в основную
              ветку попадает сюда автоматически.
            </p>
            <ul className="status__list">
              {ROADMAP.map((item) => (
                <li key={item.text}>
                  <span className={`status__dot status__dot--${item.state}`} />
                  <span>{item.text}</span>
                </li>
              ))}
            </ul>
          </div>
        </section>
      </main>

      <footer className="wrap foot">
        <span>BookTranslate · платформа перевода технической документации</span>
        <span>Демонстрационные данные. Разработка идёт.</span>
      </footer>
    </>
  );
}
