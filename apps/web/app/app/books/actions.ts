"use server";

/* Действия с книгой: завести издание, собрать комплект исходников.

   Серверными действиями, а не запросами из браузера: токен лежит в
   httpOnly-печенье, браузер его не видит, и обращаться с ним к API должен
   сервер витрины.

   Загрузка самого файла сюда не входит — она идёт отдельным маршрутом
   (`app/api/documents/upload/route.ts`): серверное действие принимает тело
   целиком в память и ограничено мегабайтом, а книга — это десятки. */

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { ApiError, apiFetch } from "../../lib/api";
import { accessToken, organizationId } from "../../lib/session";
import type { Book, SourceRole, SourceValidation } from "../../lib/work";

export type Result = { error?: string; done?: boolean };

// Идентификатор из формы уходит в адрес запроса, а серверное действие
// вызывается и в обход отрисованной страницы. Непроверенное значение вида
// «../../projects/…» схлопнется при разборе адреса и превратит запрос в
// обращение по чужому пути. Прав это не добавляет — API проверяет их по
// тому же токену, — но подставлять в адрес что попало нельзя.
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Роли перечислены здесь же: значение приходит из формы, а формы можно
// отправить и мимо страницы. Набор тот же, что у API — там он перечисление
// и в базе, и в схеме.
const ROLES: readonly SourceRole[] = [
  "primary_text",
  "visual_reference",
  "auxiliary",
  "code_source",
];

// Те же пределы, что в API: сказать здесь быстрее, чем получить отказ.
const TITLE_MAX = 500;
const AUTHOR_MAX = 300;
const EDITION_MAX = 200;
const WORD_MAX = 60;

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

function role(value: FormDataEntryValue | null): SourceRole | null {
  return ROLES.find((item) => item === value) ?? null;
}

/** Завести издание в проекте и перейти на его карточку.
 *
 * Код издания не спрашивается: его выдаёт сервер, и он входит в номера
 * замечаний. Языковая пара тоже — она берётся у проекта.
 *
 * Удачное заведение уводит на карточку книги: сразу после этого собирают
 * комплект исходников, и оставлять человека на списке значит заставить его
 * искать там только что заведённую строку. Отказы возвращаются раньше —
 * до перехода, — и форма их показывает.
 */
export async function createBook(_previous: Result, formData: FormData): Promise<Result> {
  const projectId = String(formData.get("project_id") ?? "");
  // Пробелы сводятся здесь так же, как в API: иначе проверка длины здесь
  // и там считала бы разное.
  const title = String(formData.get("title") ?? "")
    .split(/\s+/)
    .filter((word) => word !== "")
    .join(" ");
  const author = String(formData.get("author") ?? "").trim();
  const edition = String(formData.get("edition_label") ?? "").trim();

  if (!UUID.test(projectId)) {
    return { error: "Выберите проект" };
  }

  if (title.length < 2) {
    return { error: "Название книги — хотя бы два знака" };
  }

  if (title.length > TITLE_MAX) {
    return { error: `Название книги — не длиннее ${TITLE_MAX} знаков` };
  }

  if (title.split(" ").some((word) => word.length > WORD_MAX)) {
    return { error: `Слово в названии длиннее ${WORD_MAX} знаков — так не бывает` };
  }

  if (author.length > AUTHOR_MAX) {
    return { error: `Автор — не длиннее ${AUTHOR_MAX} знаков` };
  }

  if (edition.length > EDITION_MAX) {
    return { error: `Пометка издания — не длиннее ${EDITION_MAX} знаков` };
  }

  let book: Book;

  try {
    const { token, organizationId: organization } = await credentials();

    book = await apiFetch<Book>(`/projects/${projectId}/books`, {
      method: "POST",
      token,
      organizationId: organization,
      body: {
        title,
        author: author === "" ? null : author,
        edition_label: edition === "" ? null : edition,
      },
    });
  } catch (error) {
    return failure(error);
  }

  revalidatePath("/app/books");

  redirect(`/app/books/${book.id}`);
}

/** Включить загруженный файл в комплект книги с ролью. */
export async function attachSource(
  _previous: Result,
  formData: FormData,
): Promise<Result> {
  const bookId = String(formData.get("book_id") ?? "");
  const documentId = String(formData.get("document_id") ?? "");
  const chosen = role(formData.get("role"));

  if (!UUID.test(bookId) || !UUID.test(documentId)) {
    return { error: "Запрос повреждён — обновите страницу" };
  }

  if (chosen === null) {
    return { error: "Выберите роль файла в комплекте" };
  }

  try {
    const { token, organizationId: organization } = await credentials();

    await apiFetch(`/books/${bookId}/sources`, {
      method: "POST",
      token,
      organizationId: organization,
      body: { document_id: documentId, role: chosen },
    });
  } catch (error) {
    return failure(error);
  }

  revalidatePath(`/app/books/${bookId}`);
  revalidatePath("/app/documents");

  return { done: true };
}

/** Сменить роль файла в комплекте.
 *
 * Основной источник у книги один. Заменить его можно только в два шага:
 * сперва прежнему назначают другую роль, потом новому — основную. Отказ
 * API на второй основной источник так и уходит словами.
 */
export async function setSourceRole(
  bookId: string,
  documentId: string,
  value: string,
): Promise<Result> {
  const chosen = role(value);

  if (!UUID.test(bookId) || !UUID.test(documentId) || chosen === null) {
    return { error: "Запрос повреждён — обновите страницу" };
  }

  try {
    const { token, organizationId: organization } = await credentials();

    await apiFetch(`/books/${bookId}/sources/${documentId}`, {
      method: "PATCH",
      token,
      organizationId: organization,
      body: { role: chosen },
    });
  } catch (error) {
    return failure(error);
  }

  revalidatePath(`/app/books/${bookId}`);

  return { done: true };
}

export type ValidationResult = { error?: string; validation?: SourceValidation };

/** Проверить файл: читается ли формат, есть ли текст, что он о себе заявляет.
 *
 * Отдельным действием, а не на загрузке: на книге в тысячу страниц чтение
 * занимает время, и держать его внутри запроса на приём файла значит
 * заставлять человека ждать молча.
 */
export async function validateSource(
  bookId: string,
  documentId: string,
): Promise<ValidationResult> {
  if (!UUID.test(bookId) || !UUID.test(documentId)) {
    return { error: "Запрос повреждён — обновите страницу" };
  }

  try {
    const { token, organizationId: organization } = await credentials();

    const validation = await apiFetch<SourceValidation>(
      `/books/${bookId}/sources/${documentId}/validation`,
      { method: "POST", token, organizationId: organization },
    );

    revalidatePath(`/app/books/${bookId}`);

    return { validation };
  } catch (error) {
    return failure(error);
  }
}
