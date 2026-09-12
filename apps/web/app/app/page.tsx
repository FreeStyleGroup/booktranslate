import Link from "next/link";
import { redirect } from "next/navigation";

import { apiFetch, unauthorized } from "../lib/api";
import { currentUser } from "../lib/current-user";
import { accessToken, organizationId, renewUrl } from "../lib/session";
import {
  CHECK_CHIP,
  CHECK_LABEL,
  DOCUMENT_LABEL,
  SEGMENT_COLOR,
  SEGMENT_LABEL,
  plural,
  thousands,
} from "./labels";

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
  documents: number;
  segments: number;
  segments_by_status: Record<string, number>;
  flagged: number;
  undecided_terms: number;
  glossary_terms: number;
  catalog_entries: number;
  memory_units: number;
  usage: {
    input_tokens: number;
    output_tokens: number;
    cached_input_tokens: number;
    estimated_usd: number | null;
    translated_by: string | null;
  };
  recent_documents: {
    id: string;
    title: string;
    status: string;
    segments: number;
    done: number;
    ready_percent: number;
  }[];
  recent_findings: {
    segment_id: string;
    document_id: string;
    document_title: string;
    position: number;
    source_text: string;
    target_text: string | null;
    checks: string[];
  }[];
};

const DEMO: Overview = {
  projects: 3,
  documents: 7,
  segments: 12480,
  segments_by_status: { approved: 5840, machine: 3120, memory: 2460, flagged: 1060 },
  flagged: 1060,
  undecided_terms: 24,
  glossary_terms: 318,
  catalog_entries: 63,
  memory_units: 2460,
  usage: {
    input_tokens: 4120000,
    output_tokens: 1980000,
    cached_input_tokens: 1900000,
    estimated_usd: 19.7,
    translated_by: "claude-opus-5",
  },
  recent_documents: [
    {
      id: "1",
      title: "api-reference-v4.docx",
      status: "review",
      segments: 1240,
      done: 967,
      ready_percent: 78,
    },
    {
      id: "2",
      title: "kubernetes-handbook.epub",
      status: "review",
      segments: 8910,
      done: 4098,
      ready_percent: 46,
    },
    {
      id: "3",
      title: "admin-guide.html",
      status: "review",
      segments: 740,
      done: 681,
      ready_percent: 92,
    },
    {
      id: "4",
      title: "security-policy.docx",
      status: "translating",
      segments: 2180,
      done: 262,
      ready_percent: 12,
    },
  ],
  recent_findings: [
    {
      segment_id: "a",
      document_id: "1",
      document_title: "api-reference-v4.docx",
      position: 218,
      source_text: "The access token expires after 3600 seconds.",
      target_text: "Токен доступа истекает через 360 секунд.",
      checks: ["numbers"],
    },
    {
      segment_id: "b",
      document_id: "1",
      document_title: "api-reference-v4.docx",
      position: 216,
      source_text: "The primary node must be restarted together with its replica set.",
      target_text: "Главный узел перезапускается вместе с группой копий.",
      checks: ["glossary"],
    },
    {
      segment_id: "c",
      document_id: "2",
      document_title: "kubernetes-handbook.epub",
      position: 604,
      source_text: "Enable TLS before exposing the service.",
      target_text: "Включите TLS, прежде чем открывать службу наружу.",
      checks: ["first_use"],
    },
    {
      segment_id: "d",
      document_id: "2",
      document_title: "kubernetes-handbook.epub",
      position: 712,
      source_text: "Timeout: 30 s ± 5 s.",
      target_text: "Таймаут: 30 с ± 3 с.",
      checks: ["numbers"],
    },
    {
      segment_id: "e",
      document_id: "3",
      document_title: "admin-guide.html",
      position: 903,
      source_text: "Refer to {0} for the full configuration example.",
      target_text: "Полный пример настройки приведён в разделе.",
      checks: ["placeholders"],
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
    // Токен отвергнут — сеанс кончился раньше печенья; продление либо
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

/** API не ответил при живом сеансе: экран говорит об этом, а не подменяет
    числа. */
function Unavailable({ reason }: { reason: string }) {
  return (
    <section className="tile soon">
      <span className="soon__mark" aria-hidden="true">
        ⏳
      </span>
      <h2>Сводка сейчас недоступна</h2>
      <p className="lead">
        Сервер не ответил на запрос сводки: {reason}. Обновите страницу через
        минуту; книги и очередь замечаний открываются из меню.
      </p>
    </section>
  );
}

/* Вошедший без организации. Демонстрацию ему показывать нельзя: он вошёл
   и примет чужие числа за свои. Администратор площадки к организациям не
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
          ? "Учётная запись администратора площадки не состоит ни в одной организации, и кабинету нечего показать. Учётные записи и рабочие пространства заводятся в управлении доступом."
          : "Учётная запись не состоит ни в одной организации. Попросите администратора добавить вас в рабочее пространство."}
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

  const approved = data.segments_by_status.approved ?? 0;
  const ready = data.segments === 0 ? 0 : Math.round((approved * 100) / data.segments);
  const fromMemory = data.segments_by_status.memory ?? 0;
  const empty = live && data.documents === 0;

  return (
    <>
      <div className="cab__row cab__row--hero">
        <section className="tile welcome">
          <div>
            <h2>Добрый день 👋</h2>
            <p>
              {empty
                ? "Рабочее пространство готово. Заведите проект и загрузите первую книгу."
                : `Готовность работ — ${ready}%, в очереди ${thousands(data.flagged)} замечаний.`}
            </p>
            <div className="welcome__stats">
              <div className="welcome__stat">
                <b>{thousands(data.flagged)}</b>
                <span>замечаний в очереди</span>
              </div>
              <div className="welcome__stat">
                <b>{ready}%</b>
                <span>принято человеком</span>
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
          <div className="stat__value">{thousands(data.documents)}</div>
          {/* Два счёта через точку, а не одной фразой: «1 книга в 2
              проектах» грамматически верно, но по смыслу ложно — книга
              лежит в одном проекте, а проектов всего два. */}
          <div className="stat__label">
            {plural(data.documents, "книга", "книги", "книг")} · {thousands(data.projects)}{" "}
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
              ? "Все термины решены"
              : "Терминов без решения — перевод ждёт"}
          </div>
        </section>
      </div>

      <div className="cab__row cab__row--4">
        <section className="stat stat--green">
          <span className="stat__mark" aria-hidden="true">
            ✅
          </span>
          <div className="stat__value">{thousands(approved)}</div>
          <div className="stat__label">Принято человеком</div>
        </section>

        <section className="stat stat--blue">
          <span className="stat__mark" aria-hidden="true">
            🧠
          </span>
          <div className="stat__value">{thousands(fromMemory)}</div>
          <div className="stat__label">Закрыто памятью переводов</div>
        </section>

        <section className="stat stat--amber">
          <span className="stat__mark" aria-hidden="true">
            🧪
          </span>
          <div className="stat__value">{thousands(data.flagged)}</div>
          <div className="stat__label">Сегментов с замечаниями</div>
        </section>

        <section className="stat stat--violet">
          <span className="stat__mark" aria-hidden="true">
            💸
          </span>
          <div className="stat__value">
            {data.usage.estimated_usd === null
              ? "—"
              : `$${data.usage.estimated_usd.toFixed(2)}`}
          </div>
          <div className="stat__label">
            {data.usage.translated_by === null
              ? "Перевод ещё не запускался"
              : `Оценка расхода · ${data.usage.translated_by}`}
          </div>
        </section>
      </div>

      <div className="cab__row cab__row--split">
        <section className="tile">
          <div className="tile__head">
            <h3>Документы в работе</h3>
            <span className="tile__note">готовность по принятым сегментам</span>
          </div>

          {data.recent_documents.length === 0 ? (
            <>
              <p className="tile__empty">
                Пока пусто. Загрузите книгу — разбор, терминология и перевод
                дальше идут сами.
              </p>
              <div className="tile__foot">
                <Link className="btn btn--primary btn--small" href="/app/documents">
                  Загрузить книгу
                </Link>
              </div>
            </>
          ) : (
            <div className="docs">
              {data.recent_documents.map((document) => (
                /* Карточка ведёт к документу только у своих данных:
                   у демонстрационных номера выдуманы, и ссылка по ним
                   привела бы в «не найдено». */
                <Doc key={document.id} document={document} live={live} />
              ))}
            </div>
          )}
        </section>

        <section className="tile">
          <div className="tile__head">
            <h3>Состояние сегментов</h3>
            <span className="tile__note">{thousands(data.segments)}</span>
          </div>
          <Donut parts={data.segments_by_status} ready={ready} />
          <div className="legend">
            {Object.entries(data.segments_by_status)
              .filter(([, amount]) => amount > 0)
              .sort(([, first], [, second]) => second - first)
              .map(([status, amount]) => (
                <div key={status}>
                  <span
                    className="dot"
                    style={{ background: SEGMENT_COLOR[status] ?? "#94a3b8" }}
                  />
                  <span>{SEGMENT_LABEL[status] ?? status}</span>
                  <b>{thousands(amount)}</b>
                </div>
              ))}
            {data.segments === 0 && <div>Сегментов пока нет</div>}
          </div>
        </section>
      </div>

      <div className="cab__row cab__row--split">
        <section className="tile">
          <div className="tile__head">
            <h3>Очередь замечаний</h3>
            <span className="tile__note">сначала худшее</span>
          </div>

          {data.recent_findings.length === 0 ? (
            <p className="tile__empty">
              Замечаний нет: всё, что переведено, прошло проверки.
            </p>
          ) : (
            <div className="rows">
              {data.recent_findings.map((finding) => (
                <div className="row" key={finding.segment_id}>
                  <span className="row__no">{finding.position}</span>
                  <span className="row__src">{finding.source_text}</span>
                  <span>{finding.target_text ?? "—"}</span>
                  <span>
                    {finding.checks.slice(0, 1).map((check) => (
                      <span key={check} className={CHECK_CHIP[check] ?? "chip chip--warn"}>
                        {CHECK_LABEL[check] ?? check}
                      </span>
                    ))}
                  </span>
                </div>
              ))}
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
          <span aria-hidden="true">👀</span> Демонстрационные данные: войдите,
          чтобы увидеть свои
        </p>
      )}
    </>
  );
}

/** Строка документа с полосой готовности — ссылкой на его карточку. */
function Doc({
  document,
  live,
}: {
  document: Overview["recent_documents"][number];
  live: boolean;
}) {
  const body = (
    <>
      <div className="doc__top">
        <b>{document.title}</b>
        <span>{document.ready_percent}%</span>
      </div>
      <div className="bar">
        <i style={{ width: `${document.ready_percent}%` }} />
      </div>
      <span className="tile__note">
        {thousands(document.segments)} сегментов ·{" "}
        {DOCUMENT_LABEL[document.status] ?? document.status}
      </span>
    </>
  );

  if (!live) {
    return <div className="doc">{body}</div>;
  }

  return (
    <Link className="doc doc--link" href={`/app/documents/${document.id}`}>
      {body}
    </Link>
  );
}

/* Кольцо состояний: доли откладываются штрихом по окружности — так дуги не
   надо считать тригонометрией и они всегда сходятся. */
function Donut({ parts, ready }: { parts: Record<string, number>; ready: number }) {
  const entries = Object.entries(parts).filter(([, amount]) => amount > 0);
  const total = entries.reduce((sum, [, amount]) => sum + amount, 0);
  const radius = 70;
  const circumference = 2 * Math.PI * radius;

  // Дуги считаются до отрисовки: копить смещение по ходу разметки значит
  // менять переменную во время построения дерева.
  const arcs = entries.reduce<{ color: string; dash: number; offset: number }[]>(
    (drawn, [status, amount]) => {
      const previous = drawn.at(-1);
      const dash = total === 0 ? 0 : (amount / total) * circumference;

      return [
        ...drawn,
        {
          color: SEGMENT_COLOR[status] ?? "#94a3b8",
          dash,
          offset: previous === undefined ? 0 : previous.offset + previous.dash,
        },
      ];
    },
    [],
  );

  return (
    <div className="donut">
      <svg
        width="190"
        height="190"
        viewBox="0 0 190 190"
        role="img"
        aria-label="Состояние сегментов"
      >
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
        <span>принято</span>
      </div>
    </div>
  );
}
