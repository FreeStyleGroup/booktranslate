import type { Metadata } from "next";

import { AuthPage } from "../../auth-page";
import { alternates, dictionary } from "../../i18n";

const t = dictionary("en");

export const metadata: Metadata = {
  title: t.login.metaTitle,
  description: t.login.metaDescription,
  alternates: alternates("en", "/login"),
};

export default function EnglishLoginPage() {
  return <AuthPage lang="en" mode="login" />;
}
