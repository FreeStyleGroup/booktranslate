"use server";

/* Действия кабинета: завести проект, разобрать документ, удалить его.

   Серверными действиями, а не запросами из браузера: токен лежит в
   httpOnly-печенье, браузер его не видит, и обращаться с ним к API должен
   сервер витрины.

   Загрузка файла сюда не входит — она идёт отдельным маршрутом
   (`app/api/documents/upload/route.ts`). Причина в размере: серверное
   действие принимает тело целиком в память и ограничено мегабайтом, а
   книга — это десятки. */

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { ApiError, apiFetch } from "../lib/api";
import { accessToken, organizationId } from "../lib/session";

export type Result = { error?: string; done?: boolean };

// Идентификатор из формы уходит в адрес запроса, а серверное действие
// вызывается и в обход отрисованной страницы. Непроверенное значение вида
// «../../projects/…» схлопнется при разборе адреса и превратит запрос в
// обращение по чужому пути. Прав это не добавляет — API проверяет их по
// тому же токену, — но подставлять в адрес что попало нельзя.
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Как показать отказ API человеку. */
function failure(error: unknown): Result {
  if (error instanceof ApiError) {
    return { error: error.message };
  }

  return { error: "Сервис недоступен. Попробуйте ещё раз." };
}

async function credentials(): Promise<{ token: string; organizationId: string | undefined }> {
  const token = await accessToken();

  if (token === undefined) {
    throw new ApiError(401, "Сеанс закончился — войдите заново");
  }

  return { token, organizationId: await organizationId() };
}

export async function createProject(_previous: Result, formData: FormData): Promise<Result> {
  const name = String(formData.get("name") ?? "").trim();
  const source = String(formData.get("source_language") ?? "").trim();
  const target = String(formData.get("target_language") ?? "").trim();
  const description = String(formData.get("description") ?? "").trim();

  if (name.length < 2) {
    return { error: "Название проекта — хотя бы два знака" };
  }

  // Пара «с русского на русский» — не перевод, а опечатка в форме. API её
  // тоже отвергнет, но сказать об этом здесь быстрее и понятнее.
  if (source.toLowerCase() === target.toLowerCase()) {
    return { error: "Язык оригинала и язык перевода совпадают" };
  }

  try {
    const { token, organizationId: organization } = await credentials();

    await apiFetch("/projects", {
      method: "POST",
      token,
      organizationId: organization,
      body: {
        name,
        source_language: source,
        target_language: target,
        description: description === "" ? null : description,
      },
    });
  } catch (error) {
    return failure(error);
  }

  revalidatePath("/app/projects");
  revalidatePath("/app/documents");

  return { done: true };
}

/** Разобрать документ на сегменты.
 *
 * `force` — осознанный повтор: разбор заново удаляет существующие сегменты
 * вместе с переводом, поэтому кнопка для него отдельная, а не «попробовать
 * ещё раз».
 */
export async function parseDocument(_previous: Result, formData: FormData): Promise<Result> {
  const id = String(formData.get("id") ?? "");
  const force = formData.get("force") === "yes";

  if (!UUID.test(id)) {
    return { error: "Запрос повреждён — обновите страницу" };
  }

  try {
    const { token, organizationId: organization } = await credentials();

    const document = await apiFetch<{ status: string; error: string | null }>(
      `/documents/${id}/parse${force ? "?force=true" : ""}`,
      { method: "POST", token, organizationId: organization },
    );

    // Разбор отвечает документом, а не отказом: сломанный файл — это
    // ответ 200 со статусом «failed» и причиной в поле. Молча показать
    // такой ответ как удачу значит отправить человека ждать перевода
    // книги, которая не разобралась.
    if (document.status === "failed") {
      return { error: document.error ?? "Файл не разобрался" };
    }

    if (document.error !== null) {
      return { error: document.error };
    }
  } catch (error) {
    return failure(error);
  }

  revalidatePath(`/app/documents/${id}`);
  revalidatePath("/app/documents");
  revalidatePath("/app");

  return { done: true };
}

/** Чем кончилась одна порция перевода. */
export type Chunk = {
  // Сколько сегментов взято ЭТИМ вызовом, а не всего в книге.
  total: number;
  from_memory: number;
  from_provider: number;
  flagged: number;
  provider_calls: number;
  saved_calls: number;
  // Сколько непереведённых осталось. Ноль — книга переведена целиком.
  remaining: number;
  status: string;
  input_tokens: number;
  output_tokens: number;
  estimated_usd: number | null;
};

/* Сколько сегментов брать за вызов.

   Не умолчание API (200): книга переводится синхронно, и порция из двухсот
   сегментов — это до десяти обращений к модели подряд, то есть минуты под
   одним запросом. Обратный прокси режет соединение раньше, чем такая
   порция закончится. Сорок — это две-три пачки: и в срок укладывается, и
   полоса выполнения двигается достаточно часто, чтобы было видно, что
   работа идёт. */
const CHUNK = 40;

/** Перевести очередную порцию книги.
 *
 * Порциями и по вызову с витрины, а не одним запросом: книга на четыреста
 * страниц переводится не минуты. Сделанное фиксируется после каждой пачки,
 * поэтому остановка на середине ничего не теряет — следующий вызов
 * продолжит с того же места.
 */
export async function translateChunk(
  documentId: string,
): Promise<{ error?: string; chunk?: Chunk }> {
  if (!UUID.test(documentId)) {
    return { error: "Запрос повреждён — обновите страницу" };
  }

  try {
    const { token, organizationId: organization } = await credentials();

    const chunk = await apiFetch<Chunk>(
      `/documents/${documentId}/translate?limit=${CHUNK}`,
      { method: "POST", token, organizationId: organization },
    );

    if (chunk.remaining === 0) {
      // Обновляем только на последней порции: перерисовывать страницу после
      // каждой из тридцати — это тридцать сборок страницы на сервере ради
      // числа, которое всё равно показывает сама полоса выполнения.
      revalidatePath(`/app/documents/${documentId}`);
      revalidatePath("/app");
    }

    return { chunk };
  } catch (error) {
    return failure(error);
  }
}

/** Удалить документ и вернуться к списку.
 *
 * Возврат, а не обновление карточки: документа, чью карточку человек
 * смотрел, больше нет, и перерисованная страница показала бы «не найдено»
 * как ошибку — хотя это результат его же действия.
 */
export async function deleteDocument(_previous: Result, formData: FormData): Promise<Result> {
  const id = String(formData.get("id") ?? "");

  if (!UUID.test(id)) {
    return { error: "Запрос повреждён — обновите страницу" };
  }

  try {
    const { token, organizationId: organization } = await credentials();

    await apiFetch(`/documents/${id}`, {
      method: "DELETE",
      token,
      organizationId: organization,
    });
  } catch (error) {
    return failure(error);
  }

  revalidatePath("/app/documents");
  revalidatePath("/app");

  redirect("/app/documents");
}
