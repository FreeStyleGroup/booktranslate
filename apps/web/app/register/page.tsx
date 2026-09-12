import type { Metadata } from "next";

import { AuthForm } from "../auth-form";
import { AuthShell } from "../auth-shell";

export const metadata: Metadata = {
  title: "Регистрация — BookTranslate",
  description: "Создание рабочего пространства BookTranslate.",
  alternates: { canonical: "/register" },
};

export default function RegisterPage() {
  return (
    <AuthShell
      title="Заведём рабочее пространство"
      lead="Проекты, словари и каталог терминов принадлежат ему. Коллег пригласите позже."
      footer={{ text: "Уже работаете здесь?", href: "/login", link: "Войти" }}
    >
      <AuthForm mode="register" />
    </AuthShell>
  );
}
