import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { currentUser } from "../../../lib/current-user";
import type { GlossaryTerm } from "../../../lib/work";
import { thousands } from "../../../app/labels";
import { SignOut } from "../../../sign-out";
import { AdminLogin } from "../../admin-login";
import { adminLoad, moment } from "../../admin";
import "../../root.css";
import { ReviewedForm } from "../forms";
import { PublishForm } from "../publish-form";

export const metadata: Metadata = {
  title: "Загрузка словаря — BookTranslate",
  robots: { index: false, follow: false },
};

/* Состав одной загрузки — для одобрения в общий словарь.

   Страница открывается только по загрузке с разрешением: на остальные
   API отвечает отказом, и здесь он показывается словами. */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type Upload = {
  id: string;
  organization_name: string;
  uploaded_by: string | null;
  filename: string;
  origin: string;
  source_language: string;
  target_language: string;
  added: number;
  updated: number;
  skipped: number;
  shared: boolean;
  subject: string | null;
  reviewed_at: string | null;
  created_at: string;
};

type Detail = {
  upload: Upload;
  terms: GlossaryTerm[];
  subjects: { id: string; title: string }[];
};

export default async function AdminUploadPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  if (!UUID.test(id)) {
    notFound();
  }

  const here = `/root/glossary/${id}`;
  const me = await currentUser(here);

  if (me === null || !me.user.is_superuser) {
    return <AdminLogin />;
  }

  const detail = await adminLoad<Detail>(`/admin/glossary/uploads/${id}`, here);

  return (
    <div className="root">
      <header className="root__top">
        <div className="root__brand">
          <span aria-hidden="true">📑</span>
          <span>
            Загрузка словаря
            <small>{me.user.email}</small>
          </span>
        </div>

        <div className="root__counts">
          <Link className="btn btn--ghost btn--small" href="/root/glossary">
            ← К словарям
          </Link>
          <SignOut className="btn btn--ghost btn--small" />
        </div>
      </header>

      <main className="root__body">
        {detail.error !== undefined ? (
          <section className="adm-panel">
            <p className="adm-table__empty">{detail.error}</p>
          </section>
        ) : (
          <section className="adm-panel">
            <div className="adm-panel__head">
              <h2>
                {detail.data.upload.organization_name} · {detail.data.upload.filename}
              </h2>
              <span className="muted">
                {detail.data.upload.origin} · {detail.data.upload.source_language} →{" "}
                {detail.data.upload.target_language} · {moment(detail.data.upload.created_at)}
                {detail.data.upload.uploaded_by !== null && ` · ${detail.data.upload.uploaded_by}`}
              </span>
            </div>

            <div className="adm-upload__meta">
              <span className="tag tag--active">Отдан площадке</span>
              <span className="muted">
                Записей {thousands(detail.data.upload.added + detail.data.upload.updated)}
                {detail.data.upload.skipped > 0 &&
                  `, пропущено ${thousands(detail.data.upload.skipped)}`}
                . Снятые из словаря пространством здесь не показаны.
              </span>
              <ReviewedForm
                upload={detail.data.upload.id}
                reviewed={detail.data.upload.reviewed_at !== null}
              />
            </div>

            {detail.data.terms.length === 0 ? (
              <p className="adm-table__empty">В этой загрузке не осталось действующих терминов.</p>
            ) : (
              <PublishForm
                upload={detail.data.upload.id}
                terms={detail.data.terms}
                subjects={detail.data.subjects}
                suggested={detail.data.upload.subject}
              />
            )}
          </section>
        )}
      </main>
    </div>
  );
}
