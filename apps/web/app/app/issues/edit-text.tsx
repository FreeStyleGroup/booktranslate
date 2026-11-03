"use client";

/* Исправление текста по замечанию.

   Новая редакция, а не правка старой: черновик остаётся в истории. Форма помнит, какую редакцию
   человек видел: если текст успел измениться, сервер ответит конфликтом, страница обновится, и
   сравнивать придётся заново. Ключ формы — редакция, поэтому новый текст подставится сам. */

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import type { IssueEditable } from "../../lib/work";
import { ReportError, useToast } from "../ui/toast";
import { editIssue } from "./actions";

export function EditText({
  issueId,
  code,
  items,
}: {
  issueId: string;
  code: string;
  items: IssueEditable[];
}) {
  if (items.length === 0) {
    return null;
  }

  return (
    <section className="tile">
      <div className="tile__head">
        <h3>Исправить текст</h3>
        <span className="tile__note">основание: {code}</span>
      </div>

      <p className="tile__note">
        Появится новая редакция, прежняя останется в истории. Замечание перейдёт в «исправлено», но
        само не закроется: исправление проверит следующий шаг.
      </p>

      {items.map((item) => (
        <EditOne key={item.revision_id} issueId={issueId} item={item} />
      ))}
    </section>
  );
}

function EditOne({ issueId, item }: { issueId: string; item: IssueEditable }) {
  const [text, setText] = useState(item.text);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const router = useRouter();
  const toast = useToast();

  function save(note: string): void {
    setError(null);

    start(async () => {
      const result = await editIssue(issueId, item.block_id, item.revision_id, text, note);

      if (result.error !== undefined) {
        setError(result.error);
        // Отказ мог быть конфликтом: на странице должен оказаться нынешний текст.
        router.refresh();
        return;
      }

      toast.ok("Исправление записано");
      router.refresh();
    });
  }

  return (
    <form
      className="is-form"
      onSubmit={(event) => {
        event.preventDefault();
        save(String(new FormData(event.currentTarget).get("note") ?? ""));
      }}
    >
      <p className="tile__note">
        {item.block_code} · редакция {item.revision_no}
      </p>

      <div className="is-pair">
        <div>
          <h4>Было</h4>
          <p className="bk-block-text">{item.text}</p>
        </div>
        <label className="field">
          <span>Станет</span>
          <textarea
            value={text}
            required
            maxLength={100000}
            rows={Math.min(12, Math.max(3, Math.ceil(item.text.length / 60)))}
            onChange={(event) => setText(event.target.value)}
          />
        </label>
      </div>

      <label className="field">
        <span>Комментарий к исправлению, если нужен</span>
        <input name="note" type="text" maxLength={4000} />
      </label>

      <div className="wk-actions">
        <button
          className="btn btn--primary"
          type="submit"
          disabled={pending || text.trim() === "" || text.trim() === item.text}
        >
          {pending ? "Записываем…" : "Записать исправление"}
        </button>
      </div>

      <ReportError error={error} />
    </form>
  );
}
