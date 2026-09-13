import type { Metadata } from "next";

import { AuthPage } from "../auth-page";
import { alternates, dictionary } from "../i18n";

const t = dictionary("ru");

export const metadata: Metadata = {
  title: t.register.metaTitle,
  description: t.register.metaDescription,
  alternates: alternates("ru", "/register"),
};

export default function RegisterPage() {
  return <AuthPage lang="ru" mode="register" />;
}
