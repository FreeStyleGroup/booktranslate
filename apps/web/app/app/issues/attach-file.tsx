"use client";

/* Приложить снимок к замечанию.

   Отправка идёт обработчиком витрины, а не серверным действием: у действия потолок тела в
   мегабайт, а снимок страницы больше. Подходит ли файл, решает API по его байтам. */

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ReportError, useToast } from "../ui/toast";

export function AttachFile({ issueId }: { issueId: string }) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const router = useRouter();
  const toast = useToast();

  async function send(file: File): Promise<void> {
    setError(null);
    setBusy(true);

    const form = new FormData();
    form.append("file", file);

    try {
      const answer = await fetch(`/api/issues/${issueId}/attachments`, {
        method: "POST",
        body: form,
      });

      if (!answer.ok) {
        const body = (await answer.json().catch(() => ({}))) as { error?: string };

        setError(body.error ?? "Файл не принят");
        return;
      }

      toast.ok("Снимок приложен");
      router.refresh();
    } catch {
      setError("Сервис недоступен. Попробуйте ещё раз.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <label className="field is-file">
        <span>Приложить снимок: PNG, JPEG, WebP или PDF до 10 МБ</span>
        <input
          type="file"
          accept="image/png,image/jpeg,image/webp,application/pdf"
          disabled={busy}
          onChange={(event) => {
            const file = event.target.files?.[0];

            if (file !== undefined) {
              void send(file);
              event.target.value = "";
            }
          }}
        />
      </label>

      <ReportError error={error} />
    </>
  );
}
