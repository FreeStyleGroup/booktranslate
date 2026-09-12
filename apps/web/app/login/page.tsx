import type { Metadata } from "next";

import { AuthForm } from "../auth-form";
import { AuthShell } from "../auth-shell";

export const metadata: Metadata = {
  title: "Вход — BookTranslate",
  description: "Вход в рабочее пространство BookTranslate.",
  alternates: { canonical: "/login" },
};

export default function LoginPage() {
  return (
    <AuthShell
      title="С возвращением"
      lead="Очередь замечаний ждёт там же, где вы её оставили."
      footer={{ text: "Ещё нет рабочего пространства?", href: "/register", link: "Регистрация" }}
    >
      <AuthForm mode="login" />
    </AuthShell>
  );
}
