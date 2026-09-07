"use server";

/* Действия администратора площадки.

   Серверные действия, а не запросы из браузера: токен лежит в
   httpOnly-печенье и в браузер не попадает вовсе, а значит и обращаться с
   ним к API должен сервер витрины. */

import { revalidatePath } from "next/cache";

import { ApiError, apiFetch } from "../lib/api";
import { accessToken } from "../lib/session";

type Result = { error?: string };

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
};

export type CreateState = Result & { created?: CreatedUser };

/** Открыть или закрыть доступ. */
export async function changeStatus(formData: FormData): Promise<void> {
  const token = await accessToken();
  const id = String(formData.get("id") ?? "");
  const status = String(formData.get("status") ?? "");

  if (token === undefined || !UUID.test(id) || !STATUSES.has(status)) {
    return;
  }

  try {
    await apiFetch(`/admin/users/${encodeURIComponent(id)}/status`, {
      method: "PATCH",
      token,
      body: { status },
    });
  } catch {
    // Отказ показывать некуда: форма уходит и возвращается перерисовкой
    // страницы, где состояние пользователя и так будет видно настоящее.
  }

  revalidatePath("/root");
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
  const fullName = String(formData.get("full_name") ?? "").trim();
  const role = String(formData.get("role") ?? "owner");

  if (email === "" || organization === "") {
    return { error: "Нужны почта и название рабочего пространства" };
  }

  try {
    const created = await apiFetch<{
      password: string;
      organization_name: string;
      user: { email: string };
    }>("/admin/users", {
      method: "POST",
      token,
      body: {
        email,
        full_name: fullName === "" ? null : fullName,
        organization_name: organization,
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
      },
    };
  } catch (error) {
    if (error instanceof ApiError) {
      return { error: error.message };
    }

    return { error: "Сервис недоступен. Попробуйте ещё раз." };
  }
}
