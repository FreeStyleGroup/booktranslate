import { accessToken } from "../lib/session";

/* Обзор кабинета.

   Числа ниже — демонстрационные: сводки по организации в API пока нет, а
   собирать её десятком запросов со страницы значит получить кабинет,
   который открывается три секунды. Пометка о демонстрации показывается
   честно, пока сводка не появится. */

const WEEKS = [
  { label: "Нед 1", segments: 320, cost: 0.9 },
  { label: "Нед 2", segments: 610, cost: 1.7 },
  { label: "Нед 3", segments: 480, cost: 1.2 },
  { label: "Нед 4", segments: 940, cost: 2.6 },
  { label: "Нед 5", segments: 1180, cost: 3.1 },
  { label: "Нед 6", segments: 860, cost: 2.2 },
  { label: "Нед 7", segments: 1420, cost: 3.8 },
  { label: "Нед 8", segments: 1610, cost: 4.1 },
];

const STATES = [
  { label: "Принято человеком", value: 5840, color: "#2f6bff" },
  { label: "Перевод модели", value: 3120, color: "#8b5cf6" },
  { label: "Из памяти", value: 2460, color: "#12b981" },
  { label: "С замечаниями", value: 1060, color: "#f0a63a" },
];

const FINDINGS: {
  no: number;
  src: string;
  dst: string;
  chip: "warn" | "danger" | "info";
  note: string;
}[] = [
  {
    no: 218,
    src: "Failure to observe this warning may result in severe injury.",
    dst: "Несоблюдение предупреждения может привести к тяжёлой травме.",
    chip: "danger",
    note: "Числа",
  },
  {
    no: 216,
    src: "The impeller shaft must be replaced together with the seal kit.",
    dst: "Вал крыльчатки заменяется вместе с комплектом уплотнений.",
    chip: "warn",
    note: "Термин",
  },
  {
    no: 604,
    src: "Set the PLC to manual mode before service.",
    dst: "Переведите ПЛК в ручной режим перед обслуживанием.",
    chip: "info",
    note: "Раскрытие",
  },
  {
    no: 712,
    src: "Torque: 42 N·m ± 2 N·m.",
    dst: "Момент затяжки: 42 Н·м ± 2 Н·м.",
    chip: "warn",
    note: "Единицы",
  },
  {
    no: 903,
    src: "Refer to {0} for the wiring diagram.",
    dst: "Схема подключения приведена в разделе.",
    chip: "danger",
    note: "Подстановка",
  },
];

const DOCUMENTS = [
  { name: "pump-manual-v4.docx", done: 78, total: "1 240 сегментов" },
  { name: "hydraulics-handbook.epub", done: 46, total: "8 910 сегментов" },
  { name: "control-unit-guide.html", done: 92, total: "740 сегментов" },
  { name: "safety-instructions.docx", done: 12, total: "2 180 сегментов" },
];

const OPEN_TERMS = [
  { term: "basis risk", freq: 9, hint: "справка найдена" },
  { term: "impeller wear ring", freq: 7, hint: "ждёт решения" },
  { term: "slippage", freq: 6, hint: "справка найдена" },
  { term: "hold-down bolt", freq: 5, hint: "ждёт решения" },
];

const CHIP: Record<"warn" | "danger" | "info", string> = {
  warn: "chip chip--warn",
  danger: "chip chip--danger",
  info: "chip chip--info",
};

export default async function DashboardPage() {
  const signed = (await accessToken()) !== undefined;

  return (
    <>
      <div className="cab__row cab__row--hero">
        <section className="tile welcome">
          <div>
            <h2>Добрый день 👋</h2>
            <p>За неделю принято 1 610 сегментов — на 14% больше прошлой.</p>
            <div className="welcome__stats">
              <div className="welcome__stat">
                <b>128</b>
                <span>замечаний в очереди</span>
              </div>
              <div className="welcome__stat">
                <b>78%</b>
                <span>готовность книги</span>
              </div>
            </div>
          </div>
          <span className="welcome__art" aria-hidden="true">
            🤖
          </span>
        </section>

        <section className="stat stat--blue">
          <span className="stat__mark" aria-hidden="true">
            📚
          </span>
          <div className="stat__value">
            7 <span className="stat__delta stat__delta--up">+2</span>
          </div>
          <div className="stat__label">Документов в работе</div>
        </section>

        <section className="stat stat--violet">
          <span className="stat__mark" aria-hidden="true">
            🗂
          </span>
          <div className="stat__value">
            24 <span className="stat__delta stat__delta--down">−11</span>
          </div>
          <div className="stat__label">Терминов без решения</div>
        </section>
      </div>

      <div className="cab__row cab__row--4">
        <section className="stat stat--green">
          <span className="stat__mark" aria-hidden="true">
            ✅
          </span>
          <div className="stat__value">
            5 840 <span className="stat__delta stat__delta--up">+9%</span>
          </div>
          <div className="stat__label">Принято человеком</div>
        </section>

        <section className="stat stat--blue">
          <span className="stat__mark" aria-hidden="true">
            🧠
          </span>
          <div className="stat__value">
            2 460 <span className="stat__delta">21%</span>
          </div>
          <div className="stat__label">Закрыто памятью переводов</div>
        </section>

        <section className="stat stat--amber">
          <span className="stat__mark" aria-hidden="true">
            🧪
          </span>
          <div className="stat__value">
            128 <span className="stat__delta stat__delta--down">−34</span>
          </div>
          <div className="stat__label">Сегментов с замечаниями</div>
        </section>

        <section className="stat stat--violet">
          <span className="stat__mark" aria-hidden="true">
            💸
          </span>
          <div className="stat__value">
            $19,7 <span className="stat__delta">за месяц</span>
          </div>
          <div className="stat__label">Оценка расхода на модель</div>
        </section>
      </div>

      <div className="cab__row cab__row--split">
        <section className="tile">
          <div className="tile__head">
            <h3>Перевод по неделям</h3>
            <div className="switch">
              <span className="is-active">Сегменты</span>
              <span>Расход</span>
            </div>
          </div>
          <AreaChart values={WEEKS.map((week) => week.segments)} />
          <div className="chart__axis">
            {WEEKS.map((week) => (
              <span key={week.label}>{week.label}</span>
            ))}
          </div>
        </section>

        <section className="tile">
          <div className="tile__head">
            <h3>Состояние сегментов</h3>
            <span className="tile__note">12 480</span>
          </div>
          <Donut />
          <div className="legend">
            {STATES.map((state) => (
              <div key={state.label}>
                <span className="dot" style={{ background: state.color }} />
                <span>{state.label}</span>
                <b>{state.value.toLocaleString("ru-RU")}</b>
              </div>
            ))}
          </div>
        </section>
      </div>

      <div className="cab__row cab__row--split">
        <section className="tile">
          <div className="tile__head">
            <h3>Очередь замечаний</h3>
            <span className="tile__note">сначала худшее</span>
          </div>
          <div className="rows">
            {FINDINGS.map((finding) => (
              <div className="row" key={finding.no}>
                <span className="row__no">{finding.no}</span>
                <span className="row__src">{finding.src}</span>
                <span>{finding.dst}</span>
                <span>
                  <span className={CHIP[finding.chip]}>{finding.note}</span>
                </span>
              </div>
            ))}
          </div>
        </section>

        <section className="tile">
          <div className="tile__head">
            <h3>Документы</h3>
            <span className="tile__note">готовность</span>
          </div>
          <div className="docs">
            {DOCUMENTS.map((document) => (
              <div className="doc" key={document.name}>
                <div className="doc__top">
                  <b>{document.name}</b>
                  <span>{document.done}%</span>
                </div>
                <div className="bar">
                  <i style={{ width: `${document.done}%` }} />
                </div>
                <span className="tile__note">{document.total}</span>
              </div>
            ))}
          </div>
        </section>
      </div>

      <div className="cab__row cab__row--split">
        <section className="tile">
          <div className="tile__head">
            <h3>Термины без решения</h3>
            <span className="tile__note">перевод не начнётся, пока они здесь</span>
          </div>
          <div className="terms">
            {OPEN_TERMS.map((item) => (
              <div className="term" key={item.term}>
                <span aria-hidden="true">🗂</span>
                <b>{item.term}</b>
                <span>
                  {item.freq}× · {item.hint}
                </span>
              </div>
            ))}
          </div>
        </section>

        <section className="tile">
          <div className="tile__head">
            <h3>Каталог справок</h3>
            <span className="tile__note">за месяц</span>
          </div>
          <div className="terms">
            <div className="term">
              <span aria-hidden="true">🔍</span>
              <b>63 справки</b>
              <span>найдено в сети</span>
            </div>
            <div className="term">
              <span aria-hidden="true">♻️</span>
              <b>184 повтора</b>
              <span>взято из каталога бесплатно</span>
            </div>
            <div className="term">
              <span aria-hidden="true">🔗</span>
              <b>58 решений</b>
              <span>с сохранённым источником</span>
            </div>
          </div>
        </section>
      </div>

      {!signed && (
        <p className="demo-badge">
          <span aria-hidden="true">👀</span> Демонстрационные данные: войдите,
          чтобы увидеть свои
        </p>
      )}
    </>
  );
}

/* График рисуется разметкой, а не библиотекой: одна кривая и заливка не
   стоят зависимости, которая тянет своё дерево модулей и требует
   клиентского кода там, где хватает статической картинки. */
function AreaChart({ values }: { values: number[] }) {
  const width = 760;
  const height = 220;
  const top = 16;
  const bottom = height - 16;
  const peak = Math.max(...values);

  const points = values.map((value, index) => ({
    x: (index / (values.length - 1)) * width,
    y: bottom - (value / peak) * (bottom - top),
  }));

  const line = points
    .map((point, index) => `${index === 0 ? "M" : "L"}${point.x.toFixed(1)} ${point.y.toFixed(1)}`)
    .join(" ");

  return (
    <svg
      className="chart"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label="Переведено сегментов по неделям"
    >
      <defs>
        <linearGradient id="area" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#2f6bff" stopOpacity="0.28" />
          <stop offset="100%" stopColor="#2f6bff" stopOpacity="0" />
        </linearGradient>
      </defs>

      {[0.25, 0.5, 0.75].map((share) => (
        <line
          key={share}
          x1="0"
          x2={width}
          y1={top + (bottom - top) * share}
          y2={top + (bottom - top) * share}
          stroke="currentColor"
          strokeOpacity="0.08"
          strokeDasharray="4 6"
        />
      ))}

      <path d={`${line} L${width} ${bottom} L0 ${bottom} Z`} fill="url(#area)" />
      <path d={line} fill="none" stroke="#2f6bff" strokeWidth="2.5" strokeLinejoin="round" />

      {points.map((point) => (
        <circle key={point.x} cx={point.x} cy={point.y} r="3.5" fill="#2f6bff" />
      ))}
    </svg>
  );
}

/* Кольцо состояний: доли откладываются штрихом по окружности — так дуги
   не надо считать тригонометрией и они всегда сходятся. */
function Donut() {
  const total = STATES.reduce((sum, state) => sum + state.value, 0);
  const radius = 70;
  const circumference = 2 * Math.PI * radius;

  // Дуги считаются до отрисовки: накапливать смещение по ходу разметки
  // значит менять переменную во время построения дерева — то, о чём React
  // просит не думать.
  const arcs = STATES.reduce<{ color: string; dash: number; offset: number }[]>(
    (drawn, state) => {
      const previous = drawn.at(-1);
      const dash = (state.value / total) * circumference;

      return [
        ...drawn,
        {
          color: state.color,
          dash,
          offset: previous === undefined ? 0 : previous.offset + previous.dash,
        },
      ];
    },
    [],
  );

  return (
    <div className="donut">
      <svg width="190" height="190" viewBox="0 0 190 190" role="img" aria-label="Состояние сегментов">
        <g transform="rotate(-90 95 95)">
          {arcs.map((arc) => (
            <circle
              key={arc.color}
              cx="95"
              cy="95"
              r={radius}
              fill="none"
              stroke={arc.color}
              strokeWidth="22"
              strokeLinecap="butt"
              strokeDasharray={`${arc.dash} ${circumference - arc.dash}`}
              strokeDashoffset={-arc.offset}
            />
          ))}
        </g>
      </svg>
      <div className="donut__value">
        <b>78%</b>
        <span>готово</span>
      </div>
    </div>
  );
}
