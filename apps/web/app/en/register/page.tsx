import type { Metadata } from "next";

import { AuthPage } from "../../auth-page";
import { alternates, dictionary } from "../../i18n";

const t = dictionary("en");

export const metadata: Metadata = {
  title: t.register.metaTitle,
  description: t.register.metaDescription,
  alternates: alternates("en", "/register"),
};

export default function EnglishRegisterPage() {
  return <AuthPage lang="en" mode="register" />;
}
