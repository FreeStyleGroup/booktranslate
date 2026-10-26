"use client";

/* Главы книги с действиями над границами.

   Клиентский компонент целиком: отказ API показывается один раз над
   списком, а не в углу каждой карточки, — в тесной строке он сжался бы
   до «нельзя». После удачного действия страница перечитывается с
   сервера: разделение и слияние переписывают места соседних глав, и
   пересчитывать их здесь значило бы повторить правила сервера.

   Разделы главы свёрнуты: на экране главное — главы и их состояние, а
   подзаголовки нужны тогда, когда главу собираются делить. */

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import type { BookStructure, Chapter, ChapterSection } from "../../../../lib/work";
import {
  BOUNDARY_CHIP,
  BOUNDARY_LABEL,
  KIND_LABEL,
  ORIGIN_LABEL,
  thousands,
  when,
  whereIs,
} from "../../../labels";
import { CopyId } from "../../../ui/copy-id";
import { useToast } from "../../../ui/toast";
import { changeStructure, renameChapter, type Result } from "../../actions";

type Change = Parameters<typeof changeStructure>[1];

export function Structure({
  bookId,
  structure,
  canManage,
}: {
  bookId: string;
  structure: BookStructure;
  /** Наблюдателю управление не показывается: API ему откажет. */
  canManage: boolean;
}) {
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const router = useRouter();
  const say = useToast();

  const { chapters } = structure;
  const drafts = chapters.filter((chapter) => chapter.boundary_status === "draft").length;

  function run(action: () => Promise<Result>, done: string): void {
    setError(null);

    start(async () => {
      const result = await action();

      if (result.error !== undefined) {
        setError(result.error);
        return;
      }

      say(done);
      router.refresh();
    });
  }

  function change(step: Change, done: string): void {
    run(() => changeStructure(bookId, step), done);
  }

  return (
    <>
      {canManage && (
        <section className="tile bk-tools">
          <div>
            <h3>{chapters.length === 0 ? "Разметка глав" : "Границы глав"}</h3>
            <p className="tile__note">
              {chapters.length === 0
                ? "Сервис предложит главы по основному источнику: по заголовкам, а без них — по файлам EPUB или страницам PDF. Ничего не утверждается само."
                : drafts > 0
                  ? "Проверьте границы, разделите или объедините главы и утвердите. Код главы выдаётся при утверждении, по порядку книги."
                  : "Все главы утверждены. Изменение границ вернёт главу в черновик и поднимет версию её границ."}
            </p>
          </div>

          <span className="wk-actions">
            {structure.can_propose && (
              <button
                className={chapters.length === 0 ? "btn btn--primary" : "btn btn--ghost"}
                type="button"
                disabled={pending}
                onClick={() => change({ step: "propose" }, "Главы предложены")}
              >
                {chapters.length === 0 ? "Предложить главы" : "Предложить заново"}
              </button>
            )}

            {drafts > 0 && (
              <button
                className="btn btn--primary"
                type="button"
                disabled={pending}
                onClick={() => change({ step: "approve-all" }, "Границы утверждены")}
              >
                Утвердить все
              </button>
            )}
          </span>
        </section>
      )}

      {error !== null && (
        <p className="form__error" role="alert">
          {error}
        </p>
      )}

      {chapters.length === 0 ? (
        !canManage && (
          <section className="tile">
            <p className="tile__empty">Главы этой книги ещё не размечены.</p>
          </section>
        )
      ) : (
        <ol className="bk-chapters">
          {chapters.map((chapter, index) => (
            <ChapterCard
              key={chapter.id}
              chapter={chapter}
              isLast={index === chapters.length - 1}
              // Утверждать по порядку: выше не должно быть черновиков.
              canApprove={chapters
                .slice(0, index)
                .every((above) => above.boundary_status === "approved")}
              canManage={canManage}
              pending={pending}
              onChange={change}
              onRename={(title) =>
                run(() => renameChapter(bookId, chapter.id, title), "Название сохранено")
              }
            />
          ))}
        </ol>
      )}
    </>
  );
}

function ChapterCard({
  chapter,
  isLast,
  canApprove,
  canManage,
  pending,
  onChange,
  onRename,
}: {
  chapter: Chapter;
  isLast: boolean;
  canApprove: boolean;
  canManage: boolean;
  pending: boolean;
  onChange: (step: Change, done: string) => void;
  onRename: (title: string) => void;
}) {
  const [renaming, setRenaming] = useState(false);
  const draft = chapter.boundary_status === "draft";
  const where = whereIs(chapter.locator);

  return (
    <li className={draft ? "bk-chapter is-draft" : "bk-chapter"}>
      <div className="bk-chapter__top">
        <span className="bk-chapter__no" aria-label={`Место в книге: ${chapter.ordinal}`}>
          {chapter.ordinal}
        </span>

        <div className="bk-chapter__name">
          {renaming ? (
            <form
              className="bk-rename"
              onSubmit={(event) => {
                event.preventDefault();
                const title = new FormData(event.currentTarget).get("title");
                onRename(String(title ?? ""));
                setRenaming(false);
              }}
            >
              <label className="field">
                <span>Название главы</span>
                <input
                  name="title"
                  type="text"
                  required
                  maxLength={500}
                  defaultValue={chapter.title ?? ""}
                  autoComplete="off"
                  // Форма появляется по нажатию «Переименовать» — фокус
                  // туда, куда человек и собирался печатать.
                  autoFocus
                />
              </label>
              <span className="wk-actions">
                <button className="btn btn--primary btn--small" type="submit" disabled={pending}>
                  Сохранить
                </button>
                <button
                  className="btn btn--ghost btn--small"
                  type="button"
                  onClick={() => setRenaming(false)}
                >
                  Отмена
                </button>
              </span>
            </form>
          ) : (
            <b>{chapter.title ?? "Без названия"}</b>
          )}

          <span className="tile__note">
            {[
              where,
              ORIGIN_LABEL[chapter.origin] ?? chapter.origin,
              composition(chapter.inventory),
            ]
              .filter((part) => part !== null && part !== "")
              .join(" · ")}
          </span>
        </div>

        <span className="bk-chapter__side">
          {chapter.code === null ? (
            // Код появится при утверждении — и это сказано, а не пусто.
            <span className="tile__note">код при утверждении</span>
          ) : (
            <CopyId value={chapter.code} title="код главы" />
          )}

          <span className={BOUNDARY_CHIP[chapter.boundary_status] ?? "chip chip--info"}>
            {BOUNDARY_LABEL[chapter.boundary_status] ?? chapter.boundary_status}
          </span>
        </span>
      </div>

      <div className="bk-chapter__facts tile__note">
        {chapter.boundary_version > 1 && (
          // Версия видна только когда она не первая: ради неё и стоит —
          // показать, что границы менялись после утверждения.
          <span>границы v{chapter.boundary_version}</span>
        )}
        {chapter.approved_at !== null && (
          // У черновика дата — прежнего утверждения: границы с тех пор
          // менялись, и «утверждена» рядом с «черновиком» было бы неправдой.
          <span>
            {draft ? "прежние границы утверждены" : "утверждена"} {when(chapter.approved_at)}
          </span>
        )}
      </div>

      {chapter.sections.length > 1 && (
        <details className="bk-sections">
          <summary>
            Разделы главы — {thousands(chapter.sections.length)}
          </summary>

          <ul>
            {chapter.sections.map((section, index) => (
              <SectionRow
                key={section.start}
                section={section}
                top={chapter.sections[0].level}
                // Делить можно по началу любого раздела, кроме первого:
                // по первому глава и так начинается.
                canSplit={canManage && index > 0}
                pending={pending}
                onSplit={() =>
                  onChange(
                    { step: "split", chapterId: chapter.id, at: section.start },
                    "Глава разделена",
                  )
                }
              />
            ))}
          </ul>
        </details>
      )}

      {canManage && (
        <div className="wk-actions bk-chapter__actions">
          {draft && (
            <button
              className="btn btn--primary btn--small"
              type="button"
              disabled={pending || !canApprove}
              // Почему нельзя — словами рядом, а не догадкой по серой кнопке.
              title={canApprove ? undefined : "Сначала утвердите главы выше"}
              onClick={() =>
                onChange({ step: "approve", chapterId: chapter.id }, "Границы утверждены")
              }
            >
              Утвердить границы
            </button>
          )}

          {!isLast && (
            <button
              className="btn btn--ghost btn--small"
              type="button"
              disabled={pending}
              onClick={() =>
                onChange({ step: "merge", chapterId: chapter.id }, "Главы объединены")
              }
            >
              Объединить со следующей
            </button>
          )}

          {!renaming && (
            <button
              className="btn btn--ghost btn--small"
              type="button"
              disabled={pending}
              onClick={() => setRenaming(true)}
            >
              Переименовать
            </button>
          )}

          {draft && !canApprove && (
            <span className="tile__note">сначала утвердите главы выше</span>
          )}
        </div>
      )}
    </li>
  );
}

function SectionRow({
  section,
  top,
  canSplit,
  pending,
  onSplit,
}: {
  section: ChapterSection;
  top: number | null;
  canSplit: boolean;
  pending: boolean;
  onSplit: () => void;
}) {
  // Отступ — от уровня первого раздела главы: подзаголовок второго уровня
  // в главе второго уровня стоит вровень, а не со сдвигом.
  const depth = section.level !== null && top !== null ? Math.max(0, section.level - top) : 0;
  const where = whereIs(section.locator);

  return (
    <li className="bk-section" style={{ paddingLeft: `${depth * 18}px` }}>
      <span className="bk-section__name">
        {section.title ?? (where !== null ? `Текст с ${where}` : "Текст до первого заголовка")}
        <span className="tile__note">
          {where !== null && section.title !== null ? ` · ${where}` : ""} ·{" "}
          {composition(section.kinds)}
        </span>
      </span>

      {canSplit && (
        <button
          className="btn btn--ghost btn--small"
          type="button"
          disabled={pending}
          onClick={onSplit}
        >
          Разделить здесь
        </button>
      )}
    </li>
  );
}

/** «Абзацы: 12, Заголовки: 3» — самое многочисленное первым: по нему видно,
 *  что за глава, ещё до того, как её открыли. */
function composition(kinds: Record<string, number>): string {
  return Object.entries(kinds)
    .sort(([, left], [, right]) => right - left)
    .map(([kind, count]) => `${KIND_LABEL[kind] ?? kind}: ${thousands(count)}`)
    .join(", ");
}
