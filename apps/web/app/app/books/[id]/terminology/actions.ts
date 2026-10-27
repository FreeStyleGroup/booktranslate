"use server";

/* Версии глоссария: собрать черновик и утвердить его.

   Серверными действиями, а не запросами из браузера: токен лежит в
   httpOnly-печенье. Отказ API — «кандидатов без решения: 4» —
   возвращается словами и показывается у кнопки. */

import { revalidatePath } from "next/cache";

import { ApiError, apiFetch } from "../../../../lib/api";
import { accessToken, organizationId } from "../../../../lib/session";
import type { GlossaryVersion } from "../../../../lib/work";

export type Result = { error?: string; versionId?: string };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Те же пределы основания «терминов нет», что в API.
const REASON_MIN = 10;
const REASON_MAX = 1000;

function failure(error: unknown): Result {
  if (error instanceof ApiError) {
    return { error: error.message };
  }

  return { error: "Сервис недоступен. Попробуйте ещё раз." };
}

async function call<T>(path: string, body: unknown): Promise<T> {
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

function revalidateBook(bookId: string): void {
  revalidatePath(`/app/books/${bookId}/terminology`, "layout");
  revalidatePath(`/app/books/${bookId}`, "layout");
}

/** Собрать черновик версии — для книги или одной главы. */
export async function draftVersion(bookId: string, chapterId: string | null): Promise<Result> {
  if (!UUID.test(bookId) || (chapterId !== null && !UUID.test(chapterId))) {
    return { error: "Запрос повреждён — обновите страницу" };
  }

  try {
    const version = await call<GlossaryVersion>(`/books/${bookId}/glossary-versions`, {
      chapter_id: chapterId,
    });

    revalidateBook(bookId);

    return { versionId: version.id };
  } catch (error) {
    return failure(error);
  }
}

/** Утвердить черновик. Пустую версию — только с основанием. */
export async function approveVersion(
  bookId: string,
  versionId: string,
  reason: string | null,
): Promise<Result> {
  if (!UUID.test(bookId) || !UUID.test(versionId)) {
    return { error: "Запрос повреждён — обновите страницу" };
  }

  const clean =
    reason === null
      ? null
      : reason
          .split(/\s+/)
          .filter((word) => word !== "")
          .join(" ");

  if (clean !== null && clean.length < REASON_MIN) {
    return { error: `Основание — хотя бы ${REASON_MIN} знаков: почему у книги нет терминов` };
  }

  if (clean !== null && clean.length > REASON_MAX) {
    return { error: `Основание — не длиннее ${REASON_MAX} знаков` };
  }

  try {
    await call(`/glossary-versions/${versionId}/approval`, { empty_reason: clean });
  } catch (error) {
    return failure(error);
  }

  revalidateBook(bookId);

  return { versionId };
}
