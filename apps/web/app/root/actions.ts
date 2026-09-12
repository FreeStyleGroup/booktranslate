"use server";

/* Действия администратора площадки.

   Серверные действия, а не запросы из браузера: токен лежит в
   httpOnly-печенье и в браузер не попадает вовсе, а значит и обращаться с
   ним к API должен сервер витрины. */

import { revalidatePath } from "next/cache";

import { ApiError, apiFetch } from "../lib/api";
import { accessToken } from "../lib/session";

export type Result = { error?: string };

// Идентификатор из формы уходит в адрес запроса, а серверное действие можно
// вызвать и в обход отрисованной страницы. Непроверенное значение вида
// «../../projects/…» схлопнется при разборе адреса и превратит запрос в
// обращение по чужому пути. Прав это не добавляет — API проверяет их по
// тому же токену, — но подставлять в адрес что попало нельзя.
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Состояние — из списка, а не любая строка: опечатка должна остановиться
// здесь, а не уехать в API.
const STATUSES = new Set(["active", "suspended"]);

export type CreatedUser = {
  email: string;
  password: string;
  organization: string;
  organizationId: string;
};

export type CreateState = Result & { created?: CreatedUser };

/** Открыть или закрыть доступ. Отказ возвращается форме: молча
    перерисованная строка с прежним состоянием выглядит как «кнопка не
    сработала», и администратор жмёт её снова и снова. */
export async function changeStatus(_previous: Result, formData: FormData): Promise<Result> {
  const token = await accessToken();
  const id = String(formData.get("id") ?? "");
  const status = String(formData.get("status") ?? "");

  if (token === undefined) {
    return { error: "Сеанс закончился — войдите заново" };
  }

  if (!UUID.test(id) || !STATUSES.has(status)) {
    return { error: "Запрос повреждён — обновите страницу" };
  }

  try {
    await apiFetch(`/admin/users/${encodeURIComponent(id)}/status`, {
      method: "PATCH",
      token,
      body: { status },
    });
  } catch (error) {
    if (error instanceof ApiError) {
      return { error: error.message };
    }

    return { error: "Сервис недоступен. Попробуйте ещё раз." };
  }

  revalidatePath("/root");

  return {};
}

const ROLES = new Set(["owner", "admin", "manager", "translator", "reviewer", "viewer"]);

/** Сменить роль в пространстве. Единственный способ дать владельца
    пространству, заведённому с ролью ниже: внутри команды его назначает
    только владелец, а его там нет. */
export async function changeMemberRole(
  userId: string,
  organizationId: string,
  role: string,
): Promise<Result> {
  const token = await accessToken();

  if (token === undefined) {
    return { error: "Сеанс закончился — войдите заново" };
  }

  if (!UUID.test(userId) || !UUID.test(organizationId) || !ROLES.has(role)) {
    return { error: "Запрос повреждён — обновите страницу" };
  }

  try {
    await apiFetch(`/admin/users/${userId}/memberships/${organizationId}`, {
      method: "PATCH",
      token,
      body: { role },
    });
  } catch (error) {
    if (error instanceof ApiError) {
      return { error: error.message };
    }

    return { error: "Сервис недоступен. Попробуйте ещё раз." };
  }

  revalidatePath("/root");

  return {};
}

export type EditState = Result & { at?: number };

/** Поправить почту или имя. Меняется только присланное. */
export async function updateUser(_previous: EditState, formData: FormData): Promise<EditState> {
  const token = await accessToken();
  const id = String(formData.get("id") ?? "");
  const email = String(formData.get("email") ?? "").trim();
  const fullName = String(formData.get("full_name") ?? "").trim();

  if (token === undefined) {
    return { error: "Сеанс закончился — войдите заново" };
  }

  if (!UUID.test(id)) {
    return { error: "Запрос повреждён — обновите страницу" };
  }

  if (email === "") {
    return { error: "Почта не может быть пустой" };
  }

  try {
    await apiFetch(`/admin/users/${id}`, {
      method: "PATCH",
      token,
      body: { email, full_name: fullName === "" ? null : fullName },
    });
  } catch (error) {
    if (error instanceof ApiError) {
      return { error: error.message };
    }

    return { error: "Сервис недоступен. Попробуйте ещё раз." };
  }

  revalidatePath("/root");

  return { at: Date.now() };
}

export type PublishState = Result & { published?: number; at?: number };

/** Одобрить отмеченные термины загрузки в общий словарь под тематикой. */
export async function publishTerms(
  _previous: PublishState,
  formData: FormData,
): Promise<PublishState> {
  const token = await accessToken();

  if (token === undefined) {
    return { error: "Сеанс закончился — войдите заново" };
  }

  const upload = String(formData.get("upload") ?? "");
  const subject = String(formData.get("subject") ?? "").trim();
  const ids = formData.getAll("term").map(String).filter((id) => UUID.test(id));

  if (!UUID.test(upload)) {
    return { error: "Запрос повреждён — обновите страницу" };
  }

  if (subject === "") {
    return { error: "Выберите тематику: без неё термин попадёт не в те книги" };
  }

  if (ids.length === 0) {
    return { error: "Отметьте хотя бы один термин" };
  }

  try {
    const answer = await apiFetch<{ published: number }>("/admin/glossary/shared", {
      method: "POST",
      token,
      body: { term_ids: ids, subject },
    });

    revalidatePath("/root/glossary");
    revalidatePath(`/root/glossary/${upload}`);

    return { published: answer.published, at: Date.now() };
  } catch (error) {
    if (error instanceof ApiError) {
      return { error: error.message };
    }

    return { error: "Сервис недоступен. Попробуйте ещё раз." };
  }
}

/** Отметить загрузку просмотренной: она уходит из «новых». */
export async function markReviewed(_previous: Result, formData: FormData): Promise<Result> {
  const token = await accessToken();
  const upload = String(formData.get("upload") ?? "");

  if (token === undefined) {
    return { error: "Сеанс закончился — войдите заново" };
  }

  if (!UUID.test(upload)) {
    return { error: "Запрос повреждён — обновите страницу" };
  }

  try {
    await apiFetch(`/admin/glossary/uploads/${upload}/reviewed`, { method: "POST", token });
  } catch (error) {
    if (error instanceof ApiError) {
      return { error: error.message };
    }

    return { error: "Сервис недоступен. Попробуйте ещё раз." };
  }

  revalidatePath("/root");
  revalidatePath("/root/glossary");
  revalidatePath(`/root/glossary/${upload}`);

  return {};
}

/** Снять запись из общего словаря. Принявшие её пространства свой термин
    не теряют: он их решение. */
export async function removeShared(_previous: Result, formData: FormData): Promise<Result> {
  const token = await accessToken();
  const id = String(formData.get("id") ?? "");

  if (token === undefined) {
    return { error: "Сеанс закончился — войдите заново" };
  }

  if (!UUID.test(id)) {
    return { error: "Запрос повреждён — обновите страницу" };
  }

  try {
    await apiFetch(`/admin/glossary/shared/${id}`, { method: "DELETE", token });
  } catch (error) {
    if (error instanceof ApiError) {
      return { error: error.message };
    }

    return { error: "Сервис недоступен. Попробуйте ещё раз." };
  }

  revalidatePath("/root/glossary");

  return {};
}

/** Завести учётную запись и получить выданный пароль. */
export async function createUser(
  _previous: CreateState,
  formData: FormData,
): Promise<CreateState> {
  const token = await accessToken();

  if (token === undefined) {
    return { error: "Сеанс закончился — войдите заново" };
  }

  const email = String(formData.get("email") ?? "").trim();
  const organization = String(formData.get("organization_name") ?? "").trim();
  const organizationId = String(formData.get("organization_id") ?? "").trim();
  const fullName = String(formData.get("full_name") ?? "").trim();
  const role = String(formData.get("role") ?? "owner");

  // Пространство задаётся либо названием (заводится новое), либо
  // идентификатором существующего — так к работающей команде добавляют
  // коллегу. Идентификатор проверяется здесь по той же причине, что и в
  // changeStatus: в API он уйдёт как есть.
  if (organizationId !== "" && !UUID.test(organizationId)) {
    return { error: "Идентификатор рабочего пространства — UUID вида 8-4-4-4-12" };
  }

  if (email === "" || (organization === "" && organizationId === "")) {
    return {
      error: "Нужны почта и рабочее пространство: название нового или идентификатор существующего",
    };
  }

  try {
    const created = await apiFetch<{
      password: string;
      organization_id: string;
      organization_name: string;
      user: { email: string };
    }>("/admin/users", {
      method: "POST",
      token,
      body: {
        email,
        full_name: fullName === "" ? null : fullName,
        organization_name: organization === "" ? null : organization,
        organization_id: organizationId === "" ? null : organizationId,
        role,
      },
    });

    revalidatePath("/root");

    // Пароль возвращается один раз за всю его жизнь: в базе только хеш.
    return {
      created: {
        email: created.user.email,
        password: created.password,
        organization: created.organization_name,
        organizationId: created.organization_id,
      },
    };
  } catch (error) {
    if (error instanceof ApiError) {
      return { error: error.message };
    }

    return { error: "Сервис недоступен. Попробуйте ещё раз." };
  }
}
