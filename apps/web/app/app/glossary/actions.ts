"use server";

/* Словарь: завести, поправить, снять, принять подсказку.

   Серверные действия, а не запросы из браузера: токен живёт в
   httpOnly-печенье и в браузер не попадает. Отказ API уходит на страницу
   словами — «непереводимая запись обязана совпадать с исходной» — а не
   кодом ответа. Загрузка файла идёт отдельным обработчиком маршрута
   (`app/api/glossary/import/route.ts`): действие принимает тело в память
   и ограничено мегабайтом, а термбаза бывает больше. */

import { revalidatePath } from "next/cache";

import { ApiError, apiFetch } from "../../lib/api";
import { accessToken, organizationId } from "../../lib/session";
import type { FirstUseRule, GlossaryKind, GlossaryStatus, GlossaryTerm } from "../../lib/work";

export type Result = { error?: string };

export type AddResult = Result & {
  added?: GlossaryTerm;
  // Когда завели. По нему форма пересобирается после каждой записи.
  at?: number;
};

const KINDS = new Set<string>(["term", "abbreviation", "do_not_translate", "notation", "proper_name"]);
const STATUSES = new Set<string>([
  "proposed",
  "confirmed",
  "needs_review",
  "needs_unification",
  "retired",
]);
const FIRST_USE = new Set<string>(["none", "expand", "original"]);
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Те же пределы, что в API.
const VARIANTS_MAX = 20;
const TERM_MAX = 300;
const DOMAIN_MAX = 120;

/** Запрос от имени вошедшего в текущем пространстве. */
async function call<T>(path: string, method: string, body?: unknown): Promise<T> {
  const token = await accessToken();

  if (token === undefined) {
    throw new ApiError(401, "Сеанс закончился — войдите заново");
  }

  return apiFetch<T>(path, { method, token, organizationId: await organizationId(), body });
}

function failure(error: unknown): Result {
  if (error instanceof ApiError) {
    return { error: error.message };
  }

  return { error: "Сервис недоступен. Попробуйте ещё раз." };
}

/** Языковая пара из значения формы вида «en→ru». */
function pair(value: string): { source: string; target: string } | null {
  const [source = "", target = ""] = value.split("→");

  if (!/^[a-z]{2,10}$/i.test(source) || !/^[a-z]{2,10}$/i.test(target)) {
    return null;
  }

  return { source, target };
}

export async function addTerm(_previous: AddResult, formData: FormData): Promise<AddResult> {
  const languages = pair(String(formData.get("pair") ?? ""));
  const kind = String(formData.get("kind") ?? "term");
  const note = String(formData.get("note") ?? "").trim();
  const domain = String(formData.get("domain") ?? "").trim();
  const firstUse = String(formData.get("first_use_rule") ?? "none");
  const variants = variantsOf(String(formData.get("variants") ?? ""));

  if (languages === null) {
    return { error: "Выберите языковую пару" };
  }

  if (!KINDS.has(kind) || !FIRST_USE.has(firstUse)) {
    return { error: "Запрос повреждён — обновите страницу" };
  }

  const invalid = checkDetails({ allowed_variants: variants, domain });
  if (invalid !== null) {
    return { error: invalid };
  }

  try {
    const added = await call<GlossaryTerm>("/glossary", "POST", {
      source_term: String(formData.get("source_term") ?? "").trim(),
      target_term: String(formData.get("target_term") ?? "").trim(),
      source_language: languages.source,
      target_language: languages.target,
      kind,
      note: note === "" ? null : note,
      domain: domain === "" ? null : domain,
      first_use_rule: firstUse,
      allowed_variants: variants,
    });

    revalidatePath("/app/glossary");

    return { added, at: Date.now() };
  } catch (error) {
    return failure(error);
  }
}

export type TermChange = {
  target_term?: string;
  kind?: GlossaryKind;
  status?: GlossaryStatus;
  allowed_variants?: string[];
  domain?: string | null;
  first_use_rule?: FirstUseRule;
  mandatory?: boolean;
};

/** Варианты из поля «по одному в строке»: в самом варианте бывает запятая. */
function variantsOf(value: string): string[] {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line !== "");
}

function checkDetails(change: { allowed_variants?: string[]; domain?: string | null }): string | null {
  if (change.allowed_variants !== undefined) {
    if (change.allowed_variants.length > VARIANTS_MAX) {
      return `Допустимых вариантов — не больше ${VARIANTS_MAX}`;
    }

    if (change.allowed_variants.some((variant) => variant.length > TERM_MAX)) {
      return `Вариант — не длиннее ${TERM_MAX} знаков`;
    }
  }

  if (typeof change.domain === "string" && change.domain.length > DOMAIN_MAX) {
    return `Область — не длиннее ${DOMAIN_MAX} знаков`;
  }

  return null;
}

export async function updateTerm(id: string, change: TermChange): Promise<Result> {
  if (!UUID.test(id)) {
    return { error: "Запрос повреждён — обновите страницу" };
  }

  if (change.kind !== undefined && !KINDS.has(change.kind)) {
    return { error: "Запрос повреждён — обновите страницу" };
  }

  if (change.status !== undefined && !STATUSES.has(change.status)) {
    return { error: "Запрос повреждён — обновите страницу" };
  }

  if (change.first_use_rule !== undefined && !FIRST_USE.has(change.first_use_rule)) {
    return { error: "Запрос повреждён — обновите страницу" };
  }

  const invalid = checkDetails(change);
  if (invalid !== null) {
    return { error: invalid };
  }

  try {
    await call(`/glossary/${id}`, "PATCH", change);
    revalidatePath("/app/glossary");

    return {};
  } catch (error) {
    return failure(error);
  }
}

export async function deleteTerm(id: string): Promise<Result> {
  if (!UUID.test(id)) {
    return { error: "Запрос повреждён — обновите страницу" };
  }

  try {
    await call(`/glossary/${id}`, "DELETE");
    revalidatePath("/app/glossary");

    return {};
  } catch (error) {
    return failure(error);
  }
}

export async function acceptSuggestion(id: string): Promise<Result> {
  if (!UUID.test(id)) {
    return { error: "Запрос повреждён — обновите страницу" };
  }

  try {
    await call(`/glossary/suggestions/${id}`, "POST");
    revalidatePath("/app/glossary");

    return {};
  } catch (error) {
    return failure(error);
  }
}
