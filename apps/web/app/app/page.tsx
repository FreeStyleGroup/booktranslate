import Link from "next/link";
import { redirect } from "next/navigation";

import { apiFetch, unauthorized } from "../lib/api";
import { currentUser } from "../lib/current-user";
import { accessToken, organizationId, renewUrl } from "../lib/session";
import { REVISION_ORIGIN_COLOR, REVISION_ORIGIN_LABEL, plural, thousands } from "./labels";

/* Обзор кабинета.

   Данные берутся одним запросом к сводке (`GET /overview`): кабинет
   открывают чаще всего, и собирать его десятком запросов значит открывать
   три секунды. Без сеанса показывается тот же экран на демонстрационных
   числах — с пометкой, чтобы никто не принял их за свои. Отказ API при
   живом сеансе демонстрацией не прикрывается: отвергнутый токен уводит на
   продление (см. lib/current-user.ts), любой другой отказ показывается
   словами. */

type Overview = {
  projects: number;
  books: number;
  documents: number;
  blocks: number;
  translated: number;
  by_origin: Record<string, number>;
  live_runs: number;
  undecided_terms: number;
  open_issues: number;
  open_critical: number;
  glossary_terms: number;
  catalog_entries: number;
  memory_units: number;
  usage: {
    input_tokens: number;
    output_tokens: number;
    cached_input_tokens: number;
    estimated_usd: number | null;
  };
  recent_books: {
    id: string;
    code: string;
    title: string;
    blocks: number;
    translated: number;
    ready_percent: number;
  }[];
  attention: {
    run_id: string;
    book_id: string;
    chapter_id: string;
    title: string;
    problem: string;
  }[];
};

const DEMO: Overview = {
  projects: 3,
  books: 4,
  documents: 7,
  blocks: 12480,
  translated: 9620,
  by_origin: { model: 6980, memory: 2460, copy: 180 },
  live_runs: 1,
  undecided_terms: 14,
  open_issues: 9,
  open_critical: 1,
  glossary_terms: 420,
  catalog_entries: 96,
  memory_units: 5840,
  usage: {
    input_tokens: 4_200_000,
    output_tokens: 1_900_000,
    cached_input_tokens: 2_100_000,
    estimated_usd: 86.4,
  },
  recent_books: [
    {
      id: "a",
      code: "BK01",
      title: "API Reference v4",
      blocks: 1240,
      translated: 1240,
      ready_percent: 100,
    },
    {
      id: "b",
      code: "BK02",
      title: "Kubernetes Handbook",
      blocks: 8910,
      translated: 6680,
      ready_percent: 75,
    },
    {
      id: "c",
      code: "BK03",
      title: "Admin Guide",
      blocks: 740,
      translated: 222,
      ready_percent: 30,
    },
  ],
  attention: [
    {
      run_id: "a",
      book_id: "b",
      chapter_id: "c",
      title: "CH04 · Scheduling",
      problem: "Без перевода осталось блоков: 3",
    },
  ],
};

type Loaded =
  | { data: Overview; live: boolean; error?: undefined }
  | { data?: undefined; live?: undefined; error: string };

/** Сводка своего пространства — или демонстрационная, если сеанса нет. */
async function load(): Promise<Loaded> {
  const token = await accessToken();

  if (token === undefined) {
    return { data: DEMO, live: false };
  }

  try {
    return {
      data: await apiFetch<Overview>("/overview", {
        token,
        organizationId: await organizationId(),
      }),
      live: true,
    };
  } catch (error) {
    // Токен отвергнут — сеанс кончился раньше печенья. Продление либо
    // выдаст новый, либо выведет ко входу.
    if (unauthorized(error)) {
      redirect(renewUrl("/app"));
    }

    // 🔥 Вошедшему демонстрацию не показывают: он примет чужие числа за
    // свои, а пометку внизу не прочтёт. Отказ API — это отказ, и сказать
    // о нём надо словами.
    return { error: error instanceof Error ? error.message : "Сервис недоступен" };
  }
}

/** API не ответил при живом сеансе: экран говорит об этом, а не показывает
    числа. */
function Unavailable({ reason }: { reason: string }) {
  return (
    <section className="tile soon">
      <span className="soon__mark" aria-hidden="true">
        ⏳
      </span>
      <h2>Сводка сейчас недоступна</h2>
      <p className="lead">
        Сервер не ответил на запрос сводки: {reason}. Обновите страницу через минуту; книги и
        словарь открываются отдельно.
      </p>
    </section>
  );
}

/* Вошедший без организации. Демонстрацию ему показывать нельзя: он её увидит
   и примет чужие числа за свои. Администратор площадки к организации не
   привязан по замыслу — его место в управлении доступом. */
function NoWorkspace({ superuser }: { superuser: boolean }) {
  return (
    <section className="tile soon">
      <span className="soon__mark" aria-hidden="true">
        🏢
      </span>
      <h2>У вас нет рабочего пространства</h2>
      <p className="lead">
        {superuser
          ? "Учётная запись администратора площадки не привязана к организации: её дело — доступ, а не книги."
          : "Учётная запись не состоит ни в одной организации. Попросите администратора прислать приглашение."}
      </p>
      {superuser && (
        <Link className="btn btn--primary" href="/root">
          Управление доступом
        </Link>
      )}
    </section>
  );
}

export default async function DashboardPage() {
  const me = await currentUser("/app");

  if (me !== null && me.memberships.length === 0) {
    return <NoWorkspace superuser={me.user.is_superuser} />;
  }

  const loaded = await load();

  if (loaded.error !== undefined) {
    return <Unavailable reason={loaded.error} />;
  }

  const { data, live } = loaded;

  const ready = data.blocks === 0 ? 0 : Math.round((data.translated * 100) / data.blocks);
  const fromMemory = data.by_origin.memory ?? 0;
  const empty = live && data.books === 0;

  return (
    <>
      <div className="cab__row cab__row--hero">
        <section className="tile welcome">
          <div>
            <h2>Добрый день 👋</h2>
            <p>
              {empty
                ? "Рабочее пространство готово. Заведите книгу — главы, термины и перевод дальше идут по шагам."
                : `Переведено ${ready}% блоков${data.live_runs > 0 ? `, сейчас идёт прогонов: ${thousands(data.live_runs)}` : ""}.`}
            </p>
            <div className="welcome__stats">
              <div className="welcome__stat">
                <b>{ready}%</b>
                <span>блоков переведено</span>
              </div>
              <div className="welcome__stat">
                <b>{thousands(data.live_runs)}</b>
                <span>{plural(data.live_runs, "прогон идёт", "прогона идут", "прогонов идут")}</span>
              </div>
            </div>
          </div>
          <span className="welcome__art" aria-hidden="true">
            🤖
          </span>
        </section>

        <section className="stat stat--blue">
          <span className="stat__mark" aria-hidden="true">
            📕
          </span>
          <div className="stat__value">{thousands(data.books)}</div>
          {/* Два счёта через точку, а не одной фразой: «семь книг в трёх
              проектах» грамматически верно, но читается как раскладка. */}
          <div className="stat__label">
            {plural(data.books, "книга", "книги", "книг")} · {thousands(data.projects)}{" "}
            {plural(data.projects, "проект", "проекта", "проектов")}
          </div>
        </section>

        <section className="stat stat--violet">
          <span className="stat__mark" aria-hidden="true">
            🗂
          </span>
          <div className="stat__value">{thousands(data.undecided_terms)}</div>
          <div className="stat__label">
            {data.undecided_terms === 0
              ? "Нерешённых терминов нет"
              : "Терминов без решения — перевод ждёт"}
          </div>
        </section>
      </div>

      <div className="cab__row cab__row--4">
        <section className="stat stat--green">
          <span className="stat__mark" aria-hidden="true">
            ✅
          </span>
          <div className="stat__value">{thousands(data.translated)}</div>
          <div className="stat__label">Блоков переведено</div>
        </section>

        <section className="stat stat--blue">
          <span className="stat__mark" aria-hidden="true">
            🧠
          </span>
          <div className="stat__value">{thousands(fromMemory)}</div>
          <div className="stat__label">Закрыто готовым переводом</div>
        </section>

        <section className="stat stat--amber">
          <span className="stat__mark" aria-hidden="true">
            🧪
          </span>
          <div className="stat__value">{thousands(data.open_issues)}</div>
          <div className="stat__label">
            {data.open_critical > 0
              ? `Незакрытых ошибок, из них критичных: ${thousands(data.open_critical)}`
              : "Незакрытых ошибок"}
          </div>
        </section>

        <section className="stat stat--violet">
          <span className="stat__mark" aria-hidden="true">
            💸
          </span>
          <div className="stat__value">
            {data.usage.estimated_usd === null ? "—" : `$${data.usage.estimated_usd.toFixed(2)}`}
          </div>
          <div className="stat__label">
            {data.translated === 0 ? "Перевод ещё не запускался" : "Оценка расхода"}
          </div>
        </section>
      </div>

      <div className="cab__row cab__row--split">
        <section className="tile">
          <div className="tile__head">
            <h3>Книги в работе</h3>
            <span className="tile__note">готовность по переведённым блокам</span>
          </div>

          {data.recent_books.length === 0 ? (
            <>
              <p className="tile__empty">
                Пока пусто. Заведите книгу и загрузите её текст — дальше сервис предложит главы.
              </p>
              <div className="tile__foot">
                <Link className="btn btn--primary btn--small" href="/app/books">
                  Завести книгу
                </Link>
              </div>
            </>
          ) : (
            <div className="docs">
              {data.recent_books.map((book) => (
                /* Карточка ведёт к книге только у своих данных: у демонстрационных
                   номера выдуманы, и ссылка привела бы в «не найдено». */
                <BookRow key={book.id} book={book} live={live} />
              ))}
            </div>
          )}
        </section>

        <section className="tile">
          <div className="tile__head">
            <h3>Откуда перевод</h3>
            <span className="tile__note">{thousands(data.translated)}</span>
          </div>
          <Donut parts={data.by_origin} ready={ready} />
          <div className="legend">
            {Object.entries(data.by_origin)
              .filter(([, amount]) => amount > 0)
              .sort(([, first], [, second]) => second - first)
              .map(([origin, amount]) => (
                <div key={origin}>
                  <span
                    className="dot"
                    style={{ background: REVISION_ORIGIN_COLOR[origin] ?? "#94a3b8" }}
                  />
                  <span>{REVISION_ORIGIN_LABEL[origin] ?? origin}</span>
                  <b>{thousands(amount)}</b>
                </div>
              ))}
            {data.translated === 0 && <div>Переведённых блоков пока нет</div>}
          </div>
        </section>
      </div>

      <div className="cab__row cab__row--split">
        <section className="tile">
          <div className="tile__head">
            <h3>Что ждёт решения</h3>
            <span className="tile__note">сорвавшиеся прогоны и блоки без перевода</span>
          </div>

          {data.attention.length === 0 ? (
            <p className="tile__empty">
              {data.translated === 0
                ? "Перевод ещё не запускался: ждать решения нечему."
                : "Всё, что запускали, дошло до конца."}
            </p>
          ) : (
            <div className="rows">
              {data.attention.map((card) =>
                live ? (
                  <Link
                    className="row"
                    key={card.run_id}
                    href={`/app/books/${card.book_id}/chapters/${card.chapter_id}`}
                  >
                    <span className="row__src">{card.title}</span>
                    <span>{card.problem}</span>
                  </Link>
                ) : (
                  <div className="row" key={card.run_id}>
                    <span className="row__src">{card.title}</span>
                    <span>{card.problem}</span>
                  </div>
                ),
              )}
            </div>
          )}
        </section>

        <section className="tile">
          <div className="tile__head">
            <h3>Словарь и каталог</h3>
            <span className="tile__note">накоплено</span>
          </div>
          <div className="terms">
            <div className="term">
              <span aria-hidden="true">📑</span>
              <b>{thousands(data.glossary_terms)}</b>
              <span>решённых терминов</span>
            </div>
            <div className="term">
              <span aria-hidden="true">🔍</span>
              <b>{thousands(data.catalog_entries)}</b>
              <span>справок в каталоге</span>
            </div>
            <div className="term">
              <span aria-hidden="true">🧠</span>
              <b>{thousands(data.memory_units)}</b>
              <span>пар в памяти переводов</span>
            </div>
          </div>

          <div className="tile__foot">
            <Link className="btn btn--ghost btn--small" href="/app/catalog">
              Каталог справок
            </Link>
            <Link className="btn btn--ghost btn--small" href="/app/glossary">
              Словарь
            </Link>
          </div>
        </section>
      </div>

      {!live && (
        <p className="demo-badge">
          <span aria-hidden="true">👀</span> Демонстрационные данные. Войдите, чтобы увидеть свои
        </p>
      )}
    </>
  );
}

/** Строка книги с полосой готовности — ссылкой, если данные свои. */
function BookRow({ book, live }: { book: Overview["recent_books"][number]; live: boolean }) {
  const body = (
    <>
      <div className="doc__top">
        <b>{book.title}</b>
        <span>{book.ready_percent}%</span>
      </div>
      <div className="bar">
        <i style={{ width: `${book.ready_percent}%` }} />
      </div>
      <span className="tile__note">
        {book.code} · {thousands(book.translated)} из {thousands(book.blocks)}{" "}
        {plural(book.blocks, "блока", "блоков", "блоков")}
      </span>
    </>
  );

  if (!live) {
    return <div className="doc">{body}</div>;
  }

  return (
    <Link className="doc doc--link" href={`/app/books/${book.id}`}>
      {body}
    </Link>
  );
}

/* Кольцо долей: откладываются штрихом по окружности — не надо считать
   тригонометрией, и они всегда сходятся. */
function Donut({ parts, ready }: { parts: Record<string, number>; ready: number }) {
  const entries = Object.entries(parts).filter(([, amount]) => amount > 0);
  const total = entries.reduce((sum, [, amount]) => sum + amount, 0);
  const radius = 70;
  const circumference = 2 * Math.PI * radius;

  // Дуги считаются до отрисовки: копить смещение прямо в разметке значило бы
  // менять переменную во время построения дерева.
  const arcs = entries.reduce<{ color: string; dash: number; offset: number }[]>(
    (drawn, [origin, amount]) => {
      const previous = drawn.at(-1);
      const dash = total === 0 ? 0 : (amount / total) * circumference;

      return [
        ...drawn,
        {
          color: REVISION_ORIGIN_COLOR[origin] ?? "#94a3b8",
          dash,
          offset: previous === undefined ? 0 : previous.offset + previous.dash,
        },
      ];
    },
    [],
  );

  return (
    <div className="donut">
      <svg width="190" height="190" viewBox="0 0 190 190" role="img" aria-label="Откуда перевод">
        <g transform="rotate(-90 95 95)">
          <circle
            cx="95"
            cy="95"
            r={radius}
            fill="none"
            stroke="currentColor"
            strokeOpacity="0.08"
            strokeWidth="22"
          />
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
        <b>{ready}%</b>
        <span>переведено</span>
      </div>
    </div>
  );
}
