"use server";

/* Действия с финальными версиями глав и выпусками книги.

   Что можно и что мешает, решает API: здесь только передача. Идентификаторы сверяются, потому что
   серверное действие вызывается и в обход отрисованной страницы. */

import { revalidatePath } from "next/cache";

import { ApiError, apiFetch } from "../../lib/api";
import { accessToken, organizationId } from "../../lib/session";
import type { BookRelease, IssueSeverity } from "../../lib/work";

export type ReleaseResult = { error?: string; done?: boolean; code?: string; created?: boolean };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DAMAGED = "Запрос повреждён — обновите страницу";

function failure(error: unknown): { error: string } {
  if (error instanceof ApiError) {
    return { error: error.message };
  }

  return { error: "Сервис недоступен. Попробуйте ещё раз." };
}

async function send<T>(path: string, method: "POST" | "DELETE", body?: unknown): Promise<T> {
  const token = await accessToken();

  if (token === undefined) {
    throw new ApiError(401, "Сеанс закончился — войдите заново");
  }

  return apiFetch<T>(path, { method, token, organizationId: await organizationId(), body });
}

function refreshChapter(bookId: string, chapterId: string): void {
  revalidatePath(`/app/books/${bookId}/chapters/${chapterId}`);
  revalidatePath(`/app/books/${bookId}/assembly`);
}

export async function createChapterRelease(
  bookId: string,
  chapterId: string,
  major: boolean,
): Promise<ReleaseResult> {
  if (!UUID.test(bookId) || !UUID.test(chapterId)) {
    return { error: DAMAGED };
  }

  try {
    const created = await send<{ code: string }>(`/chapters/${chapterId}/releases`, "POST", {
      major: major === true,
    });

    refreshChapter(bookId, chapterId);

    return { code: created.code };
  } catch (error) {
    return failure(error);
  }
}

export async function approveChapterRelease(
  bookId: string,
  chapterId: string,
  releaseId: string,
): Promise<ReleaseResult> {
  if (![bookId, chapterId, releaseId].every((item) => UUID.test(item))) {
    return { error: DAMAGED };
  }

  try {
    await send(`/chapter-releases/${releaseId}/approve`, "POST");
    refreshChapter(bookId, chapterId);

    return { done: true };
  } catch (error) {
    return failure(error);
  }
}

export async function discardChapterRelease(
  bookId: string,
  chapterId: string,
  releaseId: string,
): Promise<ReleaseResult> {
  if (![bookId, chapterId, releaseId].every((item) => UUID.test(item))) {
    return { error: DAMAGED };
  }

  try {
    await send(`/chapter-releases/${releaseId}`, "DELETE");
    refreshChapter(bookId, chapterId);

    return { done: true };
  } catch (error) {
    return failure(error);
  }
}

/** Собрать выпуск из явно названных версий глав. */
export async function buildBookRelease(
  bookId: string,
  releaseIds: string[],
  major: boolean,
): Promise<ReleaseResult> {
  if (!UUID.test(bookId) || !releaseIds.every((item) => UUID.test(item))) {
    return { error: DAMAGED };
  }

  try {
    const built = await send<BookRelease>(`/books/${bookId}/releases`, "POST", {
      chapter_release_ids: releaseIds,
      major: major === true,
    });

    revalidatePath(`/app/books/${bookId}/assembly`);
    revalidatePath(`/app/books/${bookId}`);

    return { code: built.code, created: built.created };
  } catch (error) {
    return failure(error);
  }
}

export async function renderRelease(bookId: string, releaseId: string): Promise<ReleaseResult> {
  if (!UUID.test(bookId) || !UUID.test(releaseId)) {
    return { error: DAMAGED };
  }

  try {
    await send(`/book-releases/${releaseId}/artifacts`, "POST");
    revalidatePath(`/app/books/${bookId}/releases/${releaseId}`);

    return { done: true };
  } catch (error) {
    return failure(error);
  }
}

/** Страница верна. Страницу не обновляем: следом редактор всё равно уходит на следующую. */
export async function passPage(
  bookId: string,
  releaseId: string,
  artifactId: string,
  pageNo: number,
): Promise<ReleaseResult> {
  if (
    ![bookId, releaseId, artifactId].every((item) => UUID.test(item)) ||
    !Number.isInteger(pageNo) ||
    pageNo < 1
  ) {
    return { error: DAMAGED };
  }

  try {
    await send(`/artifacts/${artifactId}/pages/${pageNo}`, "POST");

    return { done: true };
  } catch (error) {
    return failure(error);
  }
}

export async function registerPageIssue(
  bookId: string,
  releaseId: string,
  artifactId: string,
  pageNo: number,
  severity: IssueSeverity,
  description: string,
): Promise<ReleaseResult> {
  if (
    ![bookId, releaseId, artifactId].every((item) => UUID.test(item)) ||
    !Number.isInteger(pageNo) ||
    pageNo < 1
  ) {
    return { error: DAMAGED };
  }

  try {
    const created = await send<{ issue_code: string }>(
      `/artifacts/${artifactId}/pages/${pageNo}/issue`,
      "POST",
      { severity, description },
    );

    revalidatePath(`/app/books/${bookId}/releases/${releaseId}`);
    revalidatePath("/app/issues");

    return { code: created.issue_code };
  } catch (error) {
    return failure(error);
  }
}

/** Выставить PASS. Все проверки на сервере: здесь только передача. */
export async function passRelease(bookId: string, releaseId: string): Promise<ReleaseResult> {
  if (!UUID.test(bookId) || !UUID.test(releaseId)) {
    return { error: DAMAGED };
  }

  try {
    await send(`/releases/${releaseId}/pass`, "POST");
    revalidatePath(`/app/books/${bookId}/releases/${releaseId}`);
    revalidatePath(`/app/books/${bookId}/assembly`);

    return { done: true };
  } catch (error) {
    return failure(error);
  }
}
