"use client";

/* Собрать черновик версии глоссария.

   После сборки — сразу на черновик: собирают его ради того, чтобы
   посмотреть, что в нём и что держит утверждение, и оставлять человека
   на списке значит заставить его искать только что собранное. */

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { ReportError } from "../../../ui/toast";
import { draftVersion } from "./actions";

export function DraftButton({
  bookId,
  chapterId,
  label,
  primary,
}: {
  bookId: string;
  /** Пусто — версия для всей книги. */
  chapterId: string | null;
  label: string;
  primary?: boolean;
}) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();

  function run(): void {
    setError(null);

    start(async () => {
      const answer = await draftVersion(bookId, chapterId);

      if (answer.error !== undefined || answer.versionId === undefined) {
        setError(answer.error ?? "Черновик не собрался — обновите страницу");
        return;
      }

      router.push(`/app/books/${bookId}/terminology/versions/${answer.versionId}`);
    });
  }

  return (
    <>
      <button
        className={primary === true ? "btn btn--primary btn--small" : "btn btn--ghost btn--small"}
        type="button"
        onClick={run}
        disabled={busy}
      >
        {busy ? "Собираем…" : label}
      </button>
      <ReportError error={error} />
    </>
  );
}
