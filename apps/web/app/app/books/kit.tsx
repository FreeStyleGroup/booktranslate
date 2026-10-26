"use client";

/* Комплект исходников книги.

   Таблицей с сортировкой здесь было бы нечего делать: файлов в комплекте
   единицы, а порядок у них свой — основной источник первым, его задаёт
   API. Поэтому список, а не `DataTable`.

   Клиентский компонент целиком, а не только кнопки в строках: отказ на
   смену роли показывается один раз под списком. Разложенный по строкам,
   он просил бы у каждой свой уголок под сообщение — и в тесной строке
   это сообщение оказалось бы в три слова: «нельзя». */

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import type { BookSource, SourceRole, SourceValidation } from "../../lib/work";
import {
  FORMAT_LABEL,
  SOURCE_ROLE_CHIP,
  SOURCE_ROLE_HINT,
  SOURCE_ROLE_LABEL,
  fileSize,
  plural,
  shortHash,
  thousands,
  when,
} from "../labels";
import { CopyId } from "../ui/copy-id";
import { useToast } from "../ui/toast";
import { setSourceRole, validateSource } from "./actions";

const ROLES: SourceRole[] = ["primary_text", "visual_reference", "auxiliary", "code_source"];

export function Kit({
  bookId,
  sources,
  canManage,
}: {
  bookId: string;
  sources: BookSource[];
  /** Наблюдателю роли не менять и проверок не запускать: API откажет, и
   *  показывать ему управление значило бы обещать то, чего нет. */
  canManage: boolean;
}) {
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const router = useRouter();
  const say = useToast();

  function changeRole(documentId: string, role: string): void {
    setError(null);

    start(async () => {
      const result = await setSourceRole(bookId, documentId, role);

      if (result.error !== undefined) {
        setError(result.error);
        return;
      }

      // Обновление страницы, а не правка списка на месте: роль меняет и
      // порядок строк, и предупреждение о разных изданиях над списком —
      // пересчитать это здесь значило бы повторить правила сервера.
      router.refresh();
    });
  }

  function check(documentId: string): void {
    setError(null);

    start(async () => {
      const result = await validateSource(bookId, documentId);

      if (result.error !== undefined) {
        setError(result.error);
        return;
      }

      // Результат виден в строке после обновления, но сказать о запуске
      // надо: на книге в тысячу страниц проверка идёт несколько секунд, и
      // без ответа человек нажимает второй раз.
      say("Файл проверен");
      router.refresh();
    });
  }

  return (
    <>
      <div className="bk-kit">
        {sources.map((source) => (
          <article className="bk-src" key={source.id}>
            <div className="bk-src__top">
              <span className="bk-src__name">
                <b>{source.title}</b>
                <span className="tile__note">
                  {FORMAT_LABEL[source.source_format] ?? source.source_format} ·{" "}
                  {fileSize(source.size_bytes)}
                  {source.original_filename !== null && ` · ${source.original_filename}`}
                </span>
              </span>

              {canManage ? (
                <label className="field bk-src__role">
                  <span>Роль в комплекте</span>
                  <select
                    value={source.source_role ?? ""}
                    disabled={pending}
                    onChange={(event) => changeRole(source.id, event.target.value)}
                  >
                    {/* Роли нет только у файла, загруженного в проект мимо
                        книги. Пункт нужен, чтобы список не показывал
                        чужое значение выбранным. */}
                    {source.source_role === null && <option value="">Не назначена</option>}
                    {ROLES.map((role) => (
                      <option key={role} value={role}>
                        {SOURCE_ROLE_LABEL[role]}
                      </option>
                    ))}
                  </select>
                  <small>
                    {source.source_role === null
                      ? "файл в комплекте, но его место ещё не назначено"
                      : SOURCE_ROLE_HINT[source.source_role]}
                  </small>
                </label>
              ) : source.source_role === null ? (
                <span className="chip chip--warn">Роль не назначена</span>
              ) : (
                /* Основной источник помечен иначе, чем остальные: на него
                   смотрят первым, и в списке из пяти файлов он не должен
                   выглядеть как любой другой. */
                <span className={SOURCE_ROLE_CHIP[source.source_role] ?? "chip chip--info"}>
                  {SOURCE_ROLE_LABEL[source.source_role]}
                </span>
              )}
            </div>

            <div className="bk-src__facts">
              <span className="tile__note">Контрольная сумма</span>
              {source.content_hash === null ? (
                <span className="tile__note">—</span>
              ) : (
                <CopyId
                  value={source.content_hash}
                  title="контрольную сумму"
                  label={shortHash(source.content_hash)}
                />
              )}

              <Verdict validation={source.validation} />

              {canManage && (
                <button
                  className="btn btn--ghost btn--small"
                  type="button"
                  disabled={pending}
                  onClick={() => check(source.id)}
                >
                  {source.validation === null ? "Проверить файл" : "Проверить заново"}
                </button>
              )}
            </div>

            {source.validation !== null && source.validation.warnings.length > 0 && (
              <ul className="bk-src__warn">
                {source.validation.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            )}
          </article>
        ))}
      </div>

      {error !== null && (
        <p className="form__error" role="alert">
          {error}
        </p>
      )}
    </>
  );
}

/** Итог проверки файла одной строкой.
 *
 * «Не проверен» — тоже итог, и сказан он прямо: молчание на этом месте
 * человек прочитает как «проверено, и всё хорошо».
 */
function Verdict({ validation }: { validation: SourceValidation | null }) {
  if (validation === null) {
    return <span className="chip chip--info">Не проверен</span>;
  }

  if (!validation.format_ok) {
    return <span className="chip chip--danger">Формат не читается</span>;
  }

  if (!validation.has_text_layer) {
    // Чаще всего это скан: страницы есть, текста на них нет. Переводить
    // такой файл нечем, и сказать об этом надо до начала работы.
    return <span className="chip chip--warn">Текста не нашлось</span>;
  }

  return (
    <>
      <span className="chip chip--ok">Текст есть</span>
      <span className="tile__note">{declared(validation)}</span>
    </>
  );
}

/** Что файл сообщает о себе: объём и объявленные название с автором. */
function declared(validation: SourceValidation): string {
  const parts: string[] = [];

  if (validation.page_count !== null) {
    parts.push(
      `${thousands(validation.page_count)} ${plural(
        validation.page_count,
        "страница",
        "страницы",
        "страниц",
      )}`,
    );
  }

  if (validation.meta_title === null) {
    // Отсутствие сведений — не ошибка: у простого текста и разметки
    // объявленных названия с автором нет вовсе.
    parts.push("сведений о себе не содержит");
  } else {
    const author = validation.meta_author === null ? "" : `, ${validation.meta_author}`;
    parts.push(`заявлено «${validation.meta_title}»${author}`);
  }

  parts.push(`проверен ${when(validation.updated_at)}`);

  return parts.join(" · ");
}
