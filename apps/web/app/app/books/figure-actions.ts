"use server";

/* Действия с переводом рисунков. Что можно, решает API; идентификаторы сверяются здесь, потому что
   серверное действие вызывается и в обход отрисованной страницы. */

import { revalidatePath } from "next/cache";

import { ApiError, apiFetch } from "../../lib/api";
import { accessToken, organizationId } from "../../lib/session";

export type FigureResult = { error?: string; done?: boolean };

export type RegionDraft = {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  source_text: string;
  target_text: string;
};

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DAMAGED = "Запрос повреждён — обновите страницу";

function failure(error: unknown): FigureResult {
  if (error instanceof ApiError) {
    return { error: error.message };
  }

  return { error: "Сервис недоступен. Попробуйте ещё раз." };
}

async function send(path: string, method: "POST" | "PUT", body?: unknown): Promise<void> {
  const token = await accessToken();

  if (token === undefined) {
    throw new ApiError(401, "Сеанс закончился — войдите заново");
  }

  await apiFetch(path, { method, token, organizationId: await organizationId(), body });
}

function refresh(bookId: string, chapterId: string): void {
  const chapter = `/app/books/${bookId}/chapters/${chapterId}`;

  revalidatePath(chapter);
  revalidatePath(`${chapter}/figures`);
}

export async function translateFigures(bookId: string, chapterId: string): Promise<FigureResult> {
  if (!UUID.test(bookId) || !UUID.test(chapterId)) {
    return { error: DAMAGED };
  }

  try {
    await send(`/chapters/${chapterId}/figures/translate`, "POST");
    refresh(bookId, chapterId);

    return { done: true };
  } catch (error) {
    return failure(error);
  }
}

export async function saveRegions(
  bookId: string,
  chapterId: string,
  translationId: string,
  regions: RegionDraft[],
): Promise<FigureResult> {
  if (![bookId, chapterId, translationId].every((item) => UUID.test(item))) {
    return { error: DAMAGED };
  }

  try {
    await send(`/figure-translations/${translationId}/regions`, "PUT", {
      regions: regions.map((item) => ({
        id: String(item.id),
        x: Number(item.x),
        y: Number(item.y),
        w: Number(item.w),
        h: Number(item.h),
        source_text: String(item.source_text),
        target_text: String(item.target_text),
      })),
    });
    refresh(bookId, chapterId);

    return { done: true };
  } catch (error) {
    return failure(error);
  }
}

export async function approveFigure(
  bookId: string,
  chapterId: string,
  translationId: string,
): Promise<FigureResult> {
  if (![bookId, chapterId, translationId].every((item) => UUID.test(item))) {
    return { error: DAMAGED };
  }

  try {
    await send(`/figure-translations/${translationId}/approve`, "POST");
    refresh(bookId, chapterId);

    return { done: true };
  } catch (error) {
    return failure(error);
  }
}

export async function keepFigureOriginal(
  bookId: string,
  chapterId: string,
  objectId: string,
  index: number,
): Promise<FigureResult> {
  if (![bookId, chapterId, objectId].every((item) => UUID.test(item)) || !Number.isInteger(index)) {
    return { error: DAMAGED };
  }

  try {
    await send(`/objects/${objectId}/images/${index}/keep-original`, "POST", {});
    refresh(bookId, chapterId);

    return { done: true };
  } catch (error) {
    return failure(error);
  }
}
