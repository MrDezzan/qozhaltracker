"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export const APP_NAME = "Qozhal";

/**
 * Верхняя полоса приложения.
 *
 * Живёт в корневом макете, а не на отдельных страницах. Первая попытка
 * была именно такой — шапку подключили на главной и на «Животных», — и
 * получилось хуже, чем без неё: на половине разделов её просто не было,
 * и вернуться можно было только кнопкой «назад» браузера. На телефоне,
 * где такой кнопки на экране нет, это тупик.
 *
 * Прячется на входе и на странице условий: там переходить некуда, а
 * ссылки на разделы, которые всё равно потребуют входа, только мешают.
 */

// Разделы объявлены здесь и берутся отсюда же нижней полосой. Двух
// списков быть не должно: разойдясь, они дадут раздел, который есть на
// телефоне и пропал на компьютере, и заметить это можно только случайно
export const NAV = [
  { href: "/", label: "Сводка" },
  { href: "/alerts", label: "Тревоги" },
  { href: "/animals", label: "Поголовье" },
  { href: "/zones", label: "Камеры" },
  { href: "/settings", label: "Настройки" },
];

const HIDDEN_ON = ["/login", "/terms", "/auth"];

/**
 * Показ платформы живёт под своим адресом и со своей полосой разделов:
 * ссылки там ведут внутрь показа, а не на живую ферму. Приставка
 * задаётся снаружи, а не читается из пути, чтобы полоса не угадывала,
 * где она находится.
 */
export function withBase(basePath: string, href: string): string {
  if (!basePath) return href;
  return href === "/" ? basePath : `${basePath}${href}`;
}

/**
 * Активен ли раздел.
 *
 * Корень подсвечивается только при точном совпадении. Иначе он горит
 * всегда: любой путь начинается с корня, и `startsWith` отвечает «да»
 * на каждой странице.
 *
 * Корень — не обязательно «/». В показе он равен basePath, и первая
 * версия этой проверки сравнивала href с «/» буквально. На живой ферме
 * всё работало, а в показе «Сводка» оставалась выделенной на всех
 * страницах, и на «/demo/alerts» горели сразу два раздела. Поэтому
 * корень передаётся, а не угадывается.
 */
export function isActive(pathname: string, href: string, basePath = ""): boolean {
  const корень = basePath || "/";
  if (href === корень) return pathname === корень;
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function shouldHide(pathname: string, basePath = ""): boolean {
  if (HIDDEN_ON.some((prefix) => pathname.startsWith(prefix))) return true;
  // Обычная полоса на страницах показа не нужна: её ссылки уводят из
  // показа наружу. Свою полосу показ рисует сам, с приставкой
  if (!basePath && pathname.startsWith("/demo")) return true;
  return false;
}

export function TopNav({
  alertCount = 0,
  isAdmin = false,
  basePath = "",
}: {
  alertCount?: number;
  isAdmin?: boolean;
  basePath?: string;
}) {
  const pathname = usePathname() ?? "/";
  if (shouldHide(pathname, basePath)) return null;

  return (
    <header className="sticky top-0 z-40 hidden border-b border-line bg-surface/90 backdrop-blur-sm md:block">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 h-14 flex items-center gap-4 sm:gap-6">
        <Link
          href={basePath || "/"}
          className="text-base font-semibold tracking-tight text-ink shrink-0"
        >
          {APP_NAME}
        </Link>

        {/* Прокрутка вместо переноса: перенесённая на вторую строку
            шапка скачет по высоте при переходах между разделами.
            Отрицательные отступы — чтобы кнопки не липли к краям
            при прокрутке, но и не сдвигали название */}
        <nav className="flex items-center gap-1 overflow-x-auto whitespace-nowrap -mx-2 px-2 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {NAV.map((item) => {
            const href = withBase(basePath, item.href);
            const active = isActive(pathname, href, basePath);
            return (
              <Link
                key={item.href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={`rounded-lg px-3 py-1.5 text-sm transition-colors ${
                  active
                    ? "bg-line-soft text-ink font-medium"
                    : "text-muted hover:text-ink hover:bg-soft"
                }`}
              >
                {item.label}
                {item.href === "/alerts" && alertCount > 0 && (
                  <span className="ml-1.5 inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-trouble text-[11px] font-medium text-surface align-middle">
                    {alertCount}
                  </span>
                )}
              </Link>
            );
          })}
        </nav>

        {isAdmin && (
          <Link
            href="/admin"
            className="ml-auto shrink-0 rounded-lg px-3 py-1.5 text-sm text-faint hover:text-ink hover:bg-soft transition-colors"
          >
            Администрирование
          </Link>
        )}
      </div>
    </header>
  );
}
