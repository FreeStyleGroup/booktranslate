"use server";

/* Действия редактуры и финальной сверки.

   Отметка всегда называет то, что человек видел: редакцию блока или сумму объекта. Если текст успел
   измениться, API откажет, и смотреть придётся заново. Значения из браузера проверяются здесь же:
   серверное действие вызывается и в обход отрисованной страницы. */

import { revalidatePath } from "next/cache";

import { ApiError, apiFetch } from "../../lib/api";
import { accessToken, organizationId } from "../../lib/session";
import type { EditReason, ReviewKind, ReviewMark } from "../../lib/work";

export type ReviewResult = { error?: string; id?: string; done?: boolean };
export type PreviewResult = { error?: string; violations?: string[] };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const HASH = /^[0-9a-f]{64}$/;

const KINDS: readonly ReviewKind[] = ["technical", "literary", "final_compare"];
const REASONS: readonly EditReason[] = ["style", "calque", "readability"];
const MARKS: readonly ReviewMark[] = ["ok", "issue"];

const DAMAGED = "Запрос повреждён — обновите страницу";

function failure(error: unknown): { error: string } {
  if (error instanceof ApiError) {
    return { error: error.message };
  }

  return { error: "Сервис недоступен. Попробуйте ещё раз." };
}

async function send<T>(path: string, body?: unknown): Promise<T> {
  const token = await accessToken();

  if (token === undefined) {
    throw new ApiError(401, "Сеанс закончился — войдите заново");
  }

  return apiFetch<T>(path, {
    method: "POST",
    token,
    organizationId: await organizationId(),
    body,
  });
}

function refresh(bookId: string, chapterId: string, runId?: string): void {
  const chapter = `/app/books/${bookId}/chapters/${chapterId}`;

  revalidatePath(chapter);

  if (runId !== undefined) {
    revalidatePath(`${chapter}/review/${runId}`);
  }
}

/** Начать работу по главе. Порядок работ держит API. */
export async function startReview(
  bookId: string,
  chapterId: string,
  kind: ReviewKind,
): Promise<ReviewResult> {
  if (!UUID.test(bookId) || !UUID.test(chapterId) || !KINDS.includes(kind)) {
    return { error: DAMAGED };
  }

  try {
    const created = await send<{ id: string }>(`/chapters/${chapterId}/reviews`, { kind });

    refresh(bookId, chapterId);

    return { id: created.id };
  } catch (error) {
    return failure(error);
  }
}

/** Отметить один блок. Массовой отметки нет ни здесь, ни в API.
 *
 * Страницу здесь не обновляем: следом редактор всё равно переходит к следующему месту, а лишняя
 * отрисовка — это ещё пачка запросов на каждую отметку.
 */
export async function markReviewBlock(
  bookId: string,
  chapterId: string,
  runId: string,
  blockId: string,
  revisionId: string,
  result: ReviewMark,
): Promise<ReviewResult> {
  if (
    ![bookId, chapterId, runId, blockId, revisionId].every((item) => UUID.test(item)) ||
    !MARKS.includes(result)
  ) {
    return { error: DAMAGED };
  }

  try {
    await send(`/review-runs/${runId}/blocks`, {
      block_id: blockId,
      revision_id: revisionId,
      result,
    });

    return { done: true };
  } catch (error) {
    return failure(error);
  }
}

export async function markReviewObject(
  bookId: string,
  chapterId: string,
  runId: string,
  objectId: string,
  contentHash: string,
  result: ReviewMark,
): Promise<ReviewResult> {
  if (
    ![bookId, chapterId, runId, objectId].every((item) => UUID.test(item)) ||
    !HASH.test(contentHash) ||
    !MARKS.includes(result)
  ) {
    return { error: DAMAGED };
  }

  try {
    await send(`/review-runs/${runId}/objects`, {
      object_id: objectId,
      content_hash: contentHash,
      result,
    });

    return { done: true };
  } catch (error) {
    return failure(error);
  }
}

/** Что правка изменит из защищённого. Ничего не сохраняет. */
export async function previewLiteraryEdit(
  runId: string,
  blockId: string,
  baseRevisionId: string,
  text: string,
): Promise<PreviewResult> {
  if (![runId, blockId, baseRevisionId].every((item) => UUID.test(item))) {
    return { error: DAMAGED };
  }

  try {
    const found = await send<{ violations: string[] }>(`/review-runs/${runId}/edit/preview`, {
      block_id: blockId,
      base_revision_id: baseRevisionId,
      text,
    });

    return { violations: found.violations };
  } catch (error) {
    return failure(error);
  }
}

/** Сохранить литературную правку: новая редакция, прежняя остаётся в истории. */
export async function saveLiteraryEdit(
  bookId: string,
  chapterId: string,
  runId: string,
  edit: {
    blockId: string;
    baseRevisionId: string;
    text: string;
    reason: EditReason;
    note: string;
    issueId: string | null;
    acceptViolation: boolean;
  },
): Promise<ReviewResult> {
  if (
    ![bookId, chapterId, runId, edit.blockId, edit.baseRevisionId].every((item) =>
      UUID.test(item),
    ) ||
    (edit.issueId !== null && !UUID.test(edit.issueId)) ||
    !REASONS.includes(edit.reason)
  ) {
    return { error: DAMAGED };
  }

  try {
    const note = edit.note.trim();

    await send(`/review-runs/${runId}/edit`, {
      block_id: edit.blockId,
      base_revision_id: edit.baseRevisionId,
      text: edit.text,
      reason: edit.reason,
      note: note === "" ? null : note,
      issue_id: edit.issueId,
      accept_violation: edit.acceptViolation === true,
    });
    refresh(bookId, chapterId, runId);

    return { done: true };
  } catch (error) {
    return failure(error);
  }
}

/** Завершить работу. Покрытие и незакрытые замечания проверяет API. */
export async function completeReview(
  bookId: string,
  chapterId: string,
  runId: string,
): Promise<ReviewResult> {
  if (![bookId, chapterId, runId].every((item) => UUID.test(item))) {
    return { error: DAMAGED };
  }

  try {
    await send(`/review-runs/${runId}/complete`);
    refresh(bookId, chapterId, runId);

    return { done: true };
  } catch (error) {
    return failure(error);
  }
}
