import type { Metadata } from "next";

import { AuthPage } from "../auth-page";
import { alternates, dictionary } from "../i18n";

const t = dictionary("ru");

export const metadata: Metadata = {
  title: t.login.metaTitle,
  description: t.login.metaDescription,
  alternates: alternates("ru", "/login"),
};

export default function LoginPage() {
  return <AuthPage lang="ru" mode="login" />;
}
