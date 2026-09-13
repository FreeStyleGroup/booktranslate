import type { Metadata } from "next";

import { dictionary } from "../../i18n";
import { JoinPage } from "../../join-page";

const t = dictionary("en");

export const metadata: Metadata = {
  title: t.join.metaTitle,
  description: t.join.metaDescription,
  robots: { index: false, follow: false },
};

export default function EnglishJoin({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  return <JoinPage lang="en" searchParams={searchParams} />;
}
