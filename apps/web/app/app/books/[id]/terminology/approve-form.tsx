"use client";

/* Утвердить черновик версии глоссария.

   Пустую версию утверждают с основанием: «терминов нет» — решение, и
   через год по нему объясняют, почему книга переводилась без глоссария.
   Поле основания появляется только у пустой версии — у непустой оно
   было бы вопросом без смысла. */

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { ReportError, useToast } from "../../../ui/toast";
import { approveVersion } from "./actions";

export function ApproveForm({
  bookId,
  versionId,
  label,
  empty,
}: {
  bookId: string;
  versionId: string;
  label: string;
  empty: boolean;
}) {
  const router = useRouter();
  const toast = useToast();
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();

  function run(): void {
    setError(null);

    start(async () => {
      const answer = await approveVersion(bookId, versionId, empty ? reason : null);

      if (answer.error !== undefined) {
        setError(answer.error);
        return;
      }

      toast.ok(`Глоссарий ${label} утверждён`);
      router.refresh();
    });
  }

  return (
    <div className="bk-reason">
      {empty && (
        <label className="field">
          <span>Почему у книги нет терминов</span>
          <textarea
            rows={3}
            value={reason}
            maxLength={1000}
            disabled={busy}
            placeholder="Брошюра без специальной терминологии: все повторы — общеупотребительные слова"
            onChange={(event) => setReason(event.target.value)}
          />
        </label>
      )}

      <div className="tile__foot">
        <button className="btn btn--primary btn--small" type="button" onClick={run} disabled={busy}>
          {busy ? "Утверждаем…" : empty ? `Утвердить ${label}: терминов нет` : `Утвердить ${label}`}
        </button>
      </div>

      <ReportError error={error} />
    </div>
  );
}
