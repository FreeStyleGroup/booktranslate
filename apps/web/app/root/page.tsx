import type { Metadata } from "next";

import { apiFetch, type CurrentUser } from "../lib/api";
import { accessToken } from "../lib/session";
import { changeStatus } from "./actions";
import { AdminLogin } from "./admin-login";
import { CreateUser } from "./create-user";
import "./root.css";

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

/** Кто пришёл. Никого — значит форма входа, не ошибка. */
async function currentUser(): Promise<CurrentUser | null> {
  const token = await accessToken();

  if (token === undefined) {
    return null;
  }

  try {
    return await apiFetch<CurrentUser>("/auth/me", { token });
  } catch {
    return null;
  }
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
  searchParams: Promise<{ status?: string; query?: string }>;
}) {
  const me = await currentUser();

  // Обычный пользователь и гость видят одно и то же: раздел не намекает,
  // что он существует и что кто-то до него не дотянулся.
  if (me === null || !me.user.is_superuser) {
    return <AdminLogin />;
  }

  const { status = "", query = "" } = await searchParams;
  const parameters = new URLSearchParams();

  if (status !== "") {
    parameters.set("status", status);
  }

  if (query !== "") {
    parameters.set("query", query);
  }

  const suffix = parameters.toString();
  const list = await apiFetch<UserList>(`/admin/users${suffix === "" ? "" : `?${suffix}`}`, {
    token: await accessToken(),
  });

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

            {list.items.map((user) => (
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
                    <form action={changeStatus}>
                      <input type="hidden" name="id" value={user.id} />
                      <input type="hidden" name="status" value="active" />
                      <button className="btn btn--primary btn--small" type="submit">
                        {user.status === "pending" ? "Одобрить" : "Возобновить"}
                      </button>
                    </form>
                  )}
                  {/* Приостановка и отклонение — одно состояние, но разные
                      поступки, и называться должны по-разному: отклоняют
                      заявку, приостанавливают работающий доступ. Позже сюда
                      же встанет автоматика окончания подписки. */}
                  {user.status !== "suspended" && !user.is_superuser && (
                    <form action={changeStatus}>
                      <input type="hidden" name="id" value={user.id} />
                      <input type="hidden" name="status" value="suspended" />
                      <button className="btn btn--ghost btn--small" type="submit">
                        {user.status === "pending" ? "Отклонить" : "Приостановить"}
                      </button>
                    </form>
                  )}
                </span>
              </div>
            ))}

            {list.items.length === 0 && (
              <p className="adm-table__empty">Ничего не нашлось по этому отбору.</p>
            )}
          </div>
        </section>
      </main>
    </div>
  );
}
