"use server";

/* Каталог справок: спросить про слова, перенести справку в словарь.

   Серверные действия: токен живёт в httpOnly-печенье. Отказ API уходит на
   страницу словами — «за раз ищется не больше 25 терминов». */

import { revalidatePath } from "next/cache";

import { ApiError, apiFetch } from "../../lib/api";
import { accessToken, organizationId } from "../../lib/session";
import type { CatalogLookupReport, GlossaryKind } from "../../lib/work";

export type Result = { error?: string };

export type LookupResult = Result & {
  report?: CatalogLookupReport;
  // Когда спросили. По нему форма пересобирается после каждого запроса.
  at?: number;
};

// Столько же, сколько принимает API за раз: список длиннее отвергается
// там, а сказать об этом здесь быстрее.
const MAX_TERMS = 50;
const KINDS = new Set<string>([
  "term",
  "abbreviation",
  "do_not_translate",
  "notation",
  "proper_name",
]);

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

/** Языковая пара из значения формы вида «en→ru». */
function pair(value: string): { source: string; target: string } | null {
  const [source = "", target = ""] = value.split("→");

  if (!/^[a-z]{2,10}$/i.test(source) || !/^[a-z]{2,10}$/i.test(target)) {
    return null;
  }

  return { source, target };
}

/** Спросить справки: по строке на слово. */
export async function lookupTerms(
  _previous: LookupResult,
  formData: FormData,
): Promise<LookupResult> {
  const languages = pair(String(formData.get("pair") ?? ""));
  const terms = String(formData.get("terms") ?? "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line !== "");
  const sample = String(formData.get("sample") ?? "").trim();
  const subject = String(formData.get("subject") ?? "").trim();

  if (languages === null) {
    return { error: "Выберите языковую пару" };
  }

  if (terms.length === 0) {
    return { error: "Напишите хотя бы одно слово — по одному на строку" };
  }

  if (terms.length > MAX_TERMS) {
    return { error: `За раз ищется не больше ${MAX_TERMS} слов` };
  }

  try {
    const report = await call<CatalogLookupReport>("/catalog/lookup", "POST", {
      terms,
      source_language: languages.source,
      target_language: languages.target,
      sample: sample === "" ? null : sample.slice(0, 1000),
      subject: subject === "" ? null : subject.slice(0, 300),
      refresh: formData.get("refresh") === "yes",
    });

    revalidatePath("/app/catalog");

    return { report, at: Date.now() };
  } catch (error) {
    return failure(error);
  }
}

export type Adoption = {
  source_term: string;
  target_term: string;
  source_language: string;
  target_language: string;
  kind: GlossaryKind;
  reference: string | null;
};

/** Перенести справку в словарь — решением человека, а не сама собой. */
export async function adoptEntry(entry: Adoption): Promise<Result> {
  if (!KINDS.has(entry.kind) || entry.target_term.trim() === "") {
    return { error: "Запрос повреждён — обновите страницу" };
  }

  try {
    await call("/glossary", "POST", {
      source_term: entry.source_term,
      target_term: entry.target_term.trim(),
      source_language: entry.source_language,
      target_language: entry.target_language,
      kind: entry.kind,
      reference: entry.reference,
    });

    revalidatePath("/app/glossary");

    return {};
  } catch (error) {
    return failure(error);
  }
}
