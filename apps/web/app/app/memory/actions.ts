"use server";

/* Память переводов: поправить пару, снять пару.

   Серверные действия: токен живёт в httpOnly-печенье и в браузер не
   попадает. Отказ API уходит на страницу словами. */

import { revalidatePath } from "next/cache";

import { ApiError, apiFetch } from "../../lib/api";
import { accessToken, organizationId } from "../../lib/session";

export type Result = { error?: string };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

async function call<T>(path: string, method: string, body?: unknown): Promise<T> {
  const token = await accessToken();

  if (token === undefined) {
    throw new ApiError(401, "Сеанс закончился — войдите заново");
  }

  return apiFetch<T>(path, {
    method,
    token,
    organizationId: await organizationId(),
    body,
  });
}

function failure(error: unknown): Result {
  if (error instanceof ApiError) {
    return { error: error.message };
  }

  return { error: "Сервис недоступен. Попробуйте ещё раз." };
}

/** Поправить перевод пары. Поправленная становится человеческой. */
export async function updateUnit(id: string, targetText: string): Promise<Result> {
  if (!UUID.test(id)) {
    return { error: "Запрос повреждён — обновите страницу" };
  }

  if (targetText.trim() === "") {
    return { error: "Перевод не может быть пустым" };
  }

  try {
    await call(`/memory/${id}`, "PATCH", { target_text: targetText.trim() });
    revalidatePath("/app/memory");

    return {};
  } catch (error) {
    return failure(error);
  }
}

/** Снять пару: следующий такой же текст уйдёт в модель заново. */
export async function deleteUnit(id: string): Promise<Result> {
  if (!UUID.test(id)) {
    return { error: "Запрос повреждён — обновите страницу" };
  }

  try {
    await call(`/memory/${id}`, "DELETE");
    revalidatePath("/app/memory");

    return {};
  } catch (error) {
    return failure(error);
  }
}
