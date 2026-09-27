import type { Metadata } from "next";
import "./globals.css";
import { TopNav } from "../components/ui/TopNav";
import { BottomNav } from "../components/ui/BottomNav";
import { getServerSupabase } from "../lib/supabaseServer";

export const metadata: Metadata = {
  title: "Qozhal",
  description: "Мониторинг поголовья и территории по видеокамерам",
};

/**
 * Счётчик тревог и роль для шапки.
 *
 * Читается здесь, в макете, а не на каждой странице: иначе шапка знала
 * бы про тревоги только там, где страница не забыла ей это передать, —
 * а забыть легко, и обнаружится это не сразу.
 *
 * Любая ошибка гасится: до входа сессии нет, и падать из-за этого макету
 * нельзя — иначе не откроется и сама страница входа.
 */
async function navState(): Promise<{ alertCount: number; isAdmin: boolean }> {
  try {
    const supabase = await getServerSupabase();
    const { data } = await supabase.auth.getSession();
    if (!data.session) return { alertCount: 0, isAdmin: false };

    const [alerts, profile] = await Promise.all([
      supabase
        .from("alerts")
        .select("id", { count: "exact", head: true })
        .is("resolved_at", null)
        .in("severity", ["danger", "warning"]),
      supabase
        .from("profiles")
        .select("role")
        .eq("id", data.session.user.id)
        .maybeSingle(),
    ]);

    return {
      alertCount: alerts.count ?? 0,
      isAdmin: profile.data?.role === "admin",
    };
  } catch {
    return { alertCount: 0, isAdmin: false };
  }
}

export default async function RootLayout({ children }: LayoutProps<"/">) {
  const { alertCount, isAdmin } = await navState();

  return (
    // Onest подключён ссылкой, а не через next/font/google: сборка не
    // должна ходить в сеть за шрифтом. Не загрузился — строки отрисуются
    // системным шрифтом, и экран останется рабочим.
    // suppressHydrationWarning на <body>: расширения браузера дописывают в него
    // свои атрибуты до загрузки React, из-за чего React ругается на несовпадение.
    <html lang="ru" className="h-full">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="preconnect"
          href="https://fonts.gstatic.com"
          crossOrigin="anonymous"
        />
        {/* Правило no-page-custom-font написано про старый роутер, где
            шрифт, подключённый на одной странице, на остальных не
            грузился. Здесь ссылка стоит в корневом макете и действует на
            все страницы, то есть ровно то, чего правило и требует */}
        {/* eslint-disable-next-line @next/next/no-page-custom-font */}
        <link
          href="https://fonts.googleapis.com/css2?family=Onest:wght@400;500;600;700;800&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="min-h-full bg-bg text-ink" suppressHydrationWarning>
        <TopNav alertCount={alertCount} isAdmin={isAdmin} />
        {children}
        <BottomNav alertCount={alertCount} />
      </body>
    </html>
  );
}
