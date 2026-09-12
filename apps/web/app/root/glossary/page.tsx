import type { Metadata } from "next";
import Link from "next/link";

import { currentUser } from "../../lib/current-user";
import type { SharedTerm } from "../../lib/work";
import { GLOSSARY_KIND, thousands } from "../../app/labels";
import { SignOut } from "../../sign-out";
import { AdminLogin } from "../admin-login";
import { adminLoad, moment } from "../admin";
import "../root.css";
import { RemoveSharedForm, ReviewedForm } from "./forms";

export const metadata: Metadata = {
  title: "Словари — BookTranslate",
  description: "Загрузки словарей пространств и общий словарь площадки.",
  robots: { index: false, follow: false },
};

/* Словари — глазами администратора площадки.

   Лента загрузок: кто, когда и какой словарь принёс. Состав и кнопка
   «в общий словарь» открыты только там, где пространство дало
   разрешение; без него виден факт загрузки и числа, но не слова. Ниже —
   сам общий словарь, по тематикам. */

type Upload = {
  id: string;
  organization_id: string;
  organization_name: string;
  uploaded_by: string | null;
  filename: string;
  origin: string;
  source_language: string;
  target_language: string;
  total: number;
  added: number;
  updated: number;
  skipped: number;
  shared: boolean;
  subject: string | null;
  reviewed_at: string | null;
  reviewed_by: string | null;
  created_at: string;
};

type Subject = { id: string; title: string };
type UploadList = { items: Upload[]; unreviewed: number; subjects: Subject[] };
type SharedList = { total: number; items: SharedTerm[]; subjects: Subject[] };

const PAGE = 100;

export default async function AdminGlossaryPage({
  searchParams,
}: {
  searchParams: Promise<{ subject?: string; query?: string }>;
}) {
  const me = await currentUser("/root/glossary");

  if (me === null || !me.user.is_superuser) {
    return <AdminLogin />;
  }

  const { subject = "", query = "" } = await searchParams;
  const parameters = new URLSearchParams({ limit: String(PAGE) });

  if (subject !== "") {
    parameters.set("subject", subject);
  }

  if (query !== "") {
    parameters.set("query", query);
  }

  const [uploads, shared] = await Promise.all([
    adminLoad<UploadList>(`/admin/glossary/uploads?limit=${PAGE}`, "/root/glossary"),
    adminLoad<SharedList>(`/admin/glossary/shared?${parameters.toString()}`, "/root/glossary"),
  ]);

  if (uploads.error !== undefined) {
    return <AdminLogin unreachable />;
  }

  const titles = new Map(uploads.data.subjects.map((item) => [item.id, item.title]));

  return (
    <div className="root">
      <header className="root__top">
        <div className="root__brand">
          <span aria-hidden="true">📑</span>
          <span>
            Словари
            <small>{me.user.email}</small>
          </span>
        </div>

        <div className="root__counts">
          <span className="tag tag--pending">Новых загрузок: {uploads.data.unreviewed}</span>
          {shared.data !== undefined && (
            <span className="tag tag--active">В общем словаре: {shared.data.total}</span>
          )}
          <Link className="btn btn--ghost btn--small" href="/root">
            Доступ
          </Link>
          <SignOut className="btn btn--ghost btn--small" />
        </div>
      </header>

      <main className="root__body">
        <section className="adm-panel">
          <div className="adm-panel__head">
            <h2>Загрузки словарей</h2>
            <span className="muted">
              Состав виден только по загрузкам с разрешением пространства
            </span>
          </div>

          <div className="adm-table adm-table--uploads" role="table">
            <div className="adm-table__head" role="row">
              <span>Пространство</span>
              <span>Файл</span>
              <span>Записей</span>
              <span>Разрешение</span>
              <span>Загружен</span>
              <span />
            </div>

            {uploads.data.items.map((upload) => (
              <div
                className={upload.reviewed_at === null ? "adm-table__row is-new" : "adm-table__row"}
                role="row"
                key={upload.id}
              >
                <span>
                  <b>{upload.organization_name}</b>
                  <small>{upload.uploaded_by ?? "—"}</small>
                </span>
                <span>
                  <b>{upload.filename}</b>
                  <small>
                    {upload.origin} · {upload.source_language} → {upload.target_language}
                  </small>
                </span>
                <span className="adm-table__soft">
                  {thousands(upload.added + upload.updated)}
                  {upload.skipped > 0 && ` (пропущено ${thousands(upload.skipped)})`}
                </span>
                <span>
                  {upload.shared ? (
                    <span className="tag tag--active">Отдан площадке</span>
                  ) : (
                    <span className="tag tag--suspended">Не отдан</span>
                  )}
                  <small>
                    {upload.subject === null
                      ? "тематика не указана"
                      : (titles.get(upload.subject) ?? upload.subject)}
                  </small>
                </span>
                <span className="adm-table__soft">
                  {moment(upload.created_at)}
                  {upload.reviewed_by !== null && (
                    <small>просмотрел {upload.reviewed_by}</small>
                  )}
                </span>
                <span className="adm-table__actions">
                  {upload.shared && (
                    <Link
                      className="btn btn--primary btn--small"
                      href={`/root/glossary/${upload.id}`}
                    >
                      Открыть
                    </Link>
                  )}
                  <ReviewedForm upload={upload.id} reviewed={upload.reviewed_at !== null} />
                </span>
              </div>
            ))}

            {uploads.data.items.length === 0 && (
              <p className="adm-table__empty">Словарей ещё никто не загружал.</p>
            )}
          </div>
        </section>

        <section className="adm-panel">
          <div className="adm-panel__head">
            <h2>Общий словарь</h2>
            <span className="muted">
              Подсказывает пространствам своей тематики; их решения важнее
            </span>
          </div>

          {shared.error !== undefined ? (
            <p className="adm-table__empty">{shared.error}</p>
          ) : (
            <>
              <form className="root__filters" method="get">
                <input
                  type="search"
                  name="query"
                  defaultValue={query}
                  placeholder="Термин или перевод"
                  aria-label="Поиск по общему словарю"
                />
                <select
                  className="adm-select"
                  name="subject"
                  defaultValue={subject}
                  aria-label="Тематика"
                >
                  <option value="">Все тематики</option>
                  {shared.data.subjects.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.title}
                    </option>
                  ))}
                </select>
                <button className="btn btn--ghost btn--small" type="submit">
                  Показать
                </button>
              </form>

              <div className="adm-table adm-table--shared" role="table">
                <div className="adm-table__head" role="row">
                  <span>Тематика</span>
                  <span>Термин</span>
                  <span>Перевод</span>
                  <span>Разряд</span>
                  <span>Добавлен</span>
                  <span />
                </div>

                {shared.data.items.map((term) => (
                  <div className="adm-table__row" role="row" key={term.id}>
                    <span className="adm-table__soft">
                      {titles.get(term.subject) ?? term.subject}
                      <small>
                        {term.source_language} → {term.target_language}
                      </small>
                    </span>
                    <span>
                      <b>{term.source_term}</b>
                      {term.note !== null && term.note !== "" && <small>{term.note}</small>}
                    </span>
                    <span>{term.target_term}</span>
                    <span className="adm-table__soft">{GLOSSARY_KIND[term.kind]}</span>
                    <span className="adm-table__soft">{moment(term.created_at)}</span>
                    <span className="adm-table__actions">
                      <RemoveSharedForm id={term.id} term={term.source_term} />
                    </span>
                  </div>
                ))}

                {shared.data.items.length === 0 && (
                  <p className="adm-table__empty">
                    {subject !== "" || query !== ""
                      ? "По этому отбору ничего нет."
                      : "Общий словарь пуст: одобрите термины из загрузок с разрешением."}
                  </p>
                )}
              </div>

              {shared.data.total > shared.data.items.length && (
                <p className="muted adm-more">
                  Показаны первые {thousands(shared.data.items.length)} из{" "}
                  {thousands(shared.data.total)} — сузьте отбор.
                </p>
              )}
            </>
          )}
        </section>
      </main>
    </div>
  );
}
