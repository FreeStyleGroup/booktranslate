import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { apiFetch, unauthorized } from "../lib/api";
import { currentUser } from "../lib/current-user";
import { accessToken, renewUrl } from "../lib/session";
import { SignOut } from "../sign-out";
import { AdminLogin } from "./admin-login";
import { CreateUser } from "./create-user";
import "./root.css";
import { StatusForm } from "./status-form";

export const metadata: Metadata = {
  title: "Управление доступом — BookTranslate",
  description: "Заявки на доступ, учётные записи и рабочие пространства.",
  // Служебный раздел в поиске не нужен.
  robots: { index: false, follow: false },
};

type AdminUser = {
  id: string;
  email: string;
  full_name: string | null;
  status: "pending" | "active" | "suspended";
  is_superuser: boolean;
  created_at: string;
  last_login_at: string | null;
  status_changed_at: string | null;
  status_changed_by: string | null;
  organizations: string[];
};

type UserList = {
  items: AdminUser[];
  counts: { pending: number; active: number; suspended: number };
};

const STATUS_LABEL: Record<AdminUser["status"], string> = {
  pending: "Ждёт решения",
  active: "Доступ открыт",
  suspended: "Доступ закрыт",
};

const FILTERS: { value: string; label: string }[] = [
  { value: "", label: "Все" },
  { value: "pending", label: "Ждут решения" },
  { value: "active", label: "С доступом" },
  { value: "suspended", label: "Закрытые" },
];

/* Страница списка. API отдаёт не больше 500 за раз и умеет смещение;
   спрашиваем на одного больше, чем показываем, — так видно, есть ли
   следующая страница, без отдельного запроса за общим числом. */
const PAGE = 50;

/** Адрес той же выборки с другим смещением. */
function pageHref(status: string, query: string, offset: number): string {
  const parameters = new URLSearchParams();

  if (status !== "") {
    parameters.set("status", status);
  }

  if (query !== "") {
    parameters.set("query", query);
  }

  if (offset > 0) {
    parameters.set("offset", String(offset));
  }

  const suffix = parameters.toString();

  return suffix === "" ? "/root" : `/root?${suffix}`;
}

/** Смещение из адреса: только целое от нуля, остальное — как без него. */
function parseOffset(value: string | undefined): number {
  const parsed = Number.parseInt(value ?? "", 10);

  return Number.isInteger(parsed) && parsed > 0 ? parsed : 0;
}

function moment(value: string | null): string {
  if (value === null) {
    return "—";
  }

  return new Date(value).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Только дата: в строке «кто и когда менял» время лишнее и рвёт вёрстку. */
function day(value: string | null): string {
  if (value === null) {
    return "—";
  }

  return new Date(value).toLocaleDateString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

export default async function RootPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string; query?: string; offset?: string }>;
}) {
  const me = await currentUser("/root");

  // Обычный пользователь и гость видят одно и то же: раздел не намекает,
  // что он существует и что кто-то до него не дотянулся.
  if (me === null || !me.user.is_superuser) {
    return <AdminLogin />;
  }

  const { status = "", query = "", offset: offsetParam } = await searchParams;
  const offset = parseOffset(offsetParam);
  const parameters = new URLSearchParams();

  if (status !== "") {
    parameters.set("status", status);
  }

  if (query !== "") {
    parameters.set("query", query);
  }

  parameters.set("limit", String(PAGE + 1));
  parameters.set("offset", String(offset));

  let list: UserList;

  try {
    list = await apiFetch<UserList>(`/admin/users?${parameters.toString()}`, {
      token: await accessToken(),
    });
  } catch (error) {
    if (unauthorized(error)) {
      redirect(renewUrl(pageHref(status, query, offset)));
    }

    // Недоступный API — не повод показать страницу ошибки на весь экран:
    // администратор должен видеть, что дело в связи, а не в его правах.
    return <AdminLogin unreachable />;
  }

  const more = list.items.length > PAGE;
  const items = list.items.slice(0, PAGE);

  // Общее число известно только без поиска: счётчики считаются по
  // состояниям, а не по строке запроса.
  const total =
    query !== ""
      ? null
      : status === ""
        ? list.counts.pending + list.counts.active + list.counts.suspended
        : (list.counts[status as keyof UserList["counts"]] ?? null);

  return (
    <div className="root">
      <header className="root__top">
        <div className="root__brand">
          <span aria-hidden="true">🛡️</span>
          <span>
            Управление доступом
            <small>{me.user.email}</small>
          </span>
        </div>

        <div className="root__counts">
          <span className="tag tag--pending">Ждут решения: {list.counts.pending}</span>
          <span className="tag tag--active">С доступом: {list.counts.active}</span>
          <span className="tag tag--suspended">Закрыты: {list.counts.suspended}</span>
          <SignOut className="btn btn--ghost btn--small" />
        </div>
      </header>

      <main className="root__body">
        <CreateUser />

        <section className="adm-panel">
          <form className="root__filters" method="get">
            <input
              type="search"
              name="query"
              defaultValue={query}
              placeholder="Почта или имя"
              aria-label="Поиск по пользователям"
            />
            <div className="root__tabs">
              {FILTERS.map((filter) => (
                <button
                  key={filter.label}
                  type="submit"
                  name="status"
                  value={filter.value}
                  className={status === filter.value ? "is-active" : ""}
                >
                  {filter.label}
                </button>
              ))}
            </div>
          </form>

          <div className="adm-table" role="table">
            <div className="adm-table__head" role="row">
              <span>Пользователь</span>
              <span>Рабочие пространства</span>
              <span>Зарегистрирован</span>
              <span>Последний вход</span>
              <span>Состояние</span>
              <span />
            </div>

            {items.map((user) => (
              <div className="adm-table__row" role="row" key={user.id}>
                <span>
                  <b>{user.full_name ?? user.email}</b>
                  <small>{user.email}</small>
                </span>
                <span className="adm-table__soft">
                  {user.organizations.length === 0 ? "—" : user.organizations.join(", ")}
                </span>
                <span className="adm-table__soft">{moment(user.created_at)}</span>
                <span className="adm-table__soft">{moment(user.last_login_at)}</span>
                <span>
                  <span className={`tag tag--${user.status}`}>{STATUS_LABEL[user.status]}</span>
                  {user.status_changed_by !== null && (
                    <small title={`${user.status_changed_by}, ${moment(user.status_changed_at)}`}>
                      {user.status_changed_by}, {day(user.status_changed_at)}
                    </small>
                  )}
                </span>
                <span className="adm-table__actions">
                  {user.status !== "active" && (
                    <StatusForm
                      id={user.id}
                      status="active"
                      label={user.status === "pending" ? "Одобрить" : "Возобновить"}
                      primary
                    />
                  )}
                  {/* Приостановка и отклонение — одно состояние, но разные
                      поступки, и называться должны по-разному: отклоняют
                      заявку, приостанавливают работающий доступ. Позже сюда
                      же встанет автоматика окончания подписки. */}
                  {user.status !== "suspended" && !user.is_superuser && (
                    <StatusForm
                      id={user.id}
                      status="suspended"
                      label={user.status === "pending" ? "Отклонить" : "Приостановить"}
                    />
                  )}
                </span>
              </div>
            ))}

            {items.length === 0 && (
              <p className="adm-table__empty">
                {offset > 0
                  ? "На этой странице пусто — список стал короче."
                  : "Ничего не нашлось по этому отбору."}
              </p>
            )}
          </div>

          {(offset > 0 || more) && (
            <nav className="adm-pager" aria-label="Страницы списка">
              <span className="muted">
                Показаны {offset + 1}–{offset + items.length}
                {total !== null && ` из ${total}`}
              </span>
              <div className="adm-pager__links">
                {offset > 0 && (
                  <Link
                    className="btn btn--ghost btn--small"
                    href={pageHref(status, query, Math.max(0, offset - PAGE))}
                  >
                    ← Назад
                  </Link>
                )}
                {more && (
                  <Link
                    className="btn btn--ghost btn--small"
                    href={pageHref(status, query, offset + PAGE)}
                  >
                    Дальше →
                  </Link>
                )}
              </div>
            </nav>
          )}
        </section>
      </main>
    </div>
  );
}
