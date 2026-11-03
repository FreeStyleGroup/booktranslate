"use client";

/* Действия над редакциями блока. Текст они не меняют: одно просит новый
   вариант, другое делает готовый вариант текущим. */

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { ReportError, useToast } from "../../../../../../ui/toast";
import { adoptRevision, retranslateBlock, verifyObject, type Result } from "../../../../../actions";

function useAction() {
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const router = useRouter();
  const toast = useToast();

  function run(action: () => Promise<Result>, done: string): void {
    setError(null);

    start(async () => {
      const result = await action();

      if (result.error !== undefined) {
        setError(result.error);
        return;
      }

      toast.ok(done);
      router.refresh();
    });
  }

  return { error, pending, run };
}

export function RetranslateButton({
  bookId,
  chapterId,
  blockId,
  baseRevisionId,
}: {
  bookId: string;
  chapterId: string;
  blockId: string;
  /** Редакция на экране: вариант просят рядом именно с ней. */
  baseRevisionId: string | null;
}) {
  const { error, pending, run } = useAction();

  return (
    <>
      <button
        className="btn btn--ghost btn--small"
        type="button"
        disabled={pending}
        onClick={() =>
          run(
            () => retranslateBlock(bookId, chapterId, blockId, baseRevisionId),
            "Вариант поставлен в очередь: он появится здесь рядом с текущей редакцией",
          )
        }
      >
        {pending ? "Ставим в очередь…" : "Перевести заново"}
      </button>
      <ReportError error={error} />
    </>
  );
}

export function AdoptButton({
  bookId,
  chapterId,
  blockId,
  revisionId,
}: {
  bookId: string;
  chapterId: string;
  blockId: string;
  revisionId: string;
}) {
  const { error, pending, run } = useAction();

  return (
    <>
      <button
        className="btn btn--primary"
        type="button"
        disabled={pending}
        onClick={() =>
          run(
            () => adoptRevision(bookId, chapterId, blockId, revisionId),
            "Редакция стала текущей. Прежняя осталась в истории",
          )
        }
      >
        Сделать текущей
      </button>
      <ReportError error={error} />
    </>
  );
}

export function VerifyObjectButton({
  bookId,
  chapterId,
  objectId,
}: {
  bookId: string;
  chapterId: string;
  objectId: string;
}) {
  const { error, pending, run } = useAction();

  return (
    <>
      <button
        className="btn btn--primary"
        type="button"
        disabled={pending}
        onClick={() =>
          run(() => verifyObject(bookId, chapterId, objectId), "Объект отмечен как проверенный")
        }
      >
        Проверено технически
      </button>
      <ReportError error={error} />
    </>
  );
}
