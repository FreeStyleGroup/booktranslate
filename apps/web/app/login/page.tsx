import type { Metadata } from "next";

import { AuthPage } from "../auth-page";
import { alternates, dictionary } from "../i18n";
import { safeReturnPath } from "../lib/return-path";

const t = dictionary("ru");

export const metadata: Metadata = {
  title: t.login.metaTitle,
  description: t.login.metaDescription,
  alternates: alternates("ru", "/login"),
};

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string | string[] }>;
}) {
  const { next } = await searchParams;

  return (
    <AuthPage
      lang="ru"
      mode="login"
      next={safeReturnPath(typeof next === "string" ? next : null)}
    />
  );
}
