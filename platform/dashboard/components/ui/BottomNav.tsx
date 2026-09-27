"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { NAV, isActive, shouldHide, withBase } from "./TopNav";

/**
 * Разделы внизу экрана — только на телефоне.
 *
 * ПОЧЕМУ ВНИЗУ
 *
 * Телефон держат одной рукой, и большой палец достаёт до нижней трети
 * экрана. Верхняя полоса требует перехватить телефон или тянуться
 * второй рукой — в загоне, где вторая рука занята, это значит «не
 * буду переходить».
 *
 * Верхняя полоса при этом остаётся: на широком экране мышь достаёт
 * куда угодно, а полоса внизу там выглядит как мобильное приложение,
 * заехавшее в браузер.
 *
 * ПОЧЕМУ СО ЗНАЧКАМИ И ПОДПИСЯМИ
 *
 * Значок без подписи экономит место и стоит понимания: «домик» это
 * обзор или настройки фермы? Подпись без значка хуже читается краем
 * глаза. Вместе они работают, и это тот случай, когда дублирование
 * оправдано.
 */

const ЗНАЧКИ: Record<string, React.ReactNode> = {
  "/": (
    <path
      d="M4 10.5 12 4l8 6.5V20a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1v-9.5Z"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinejoin="round"
    />
  ),
  "/alerts": (
    <>
      <path
        d="M18 8.5a6 6 0 1 0-12 0c0 5-2 6.5-2 6.5h16s-2-1.5-2-6.5Z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
      <path
        d="M10.5 19a1.8 1.8 0 0 0 3 0"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </>
  ),
  "/animals": (
    <>
      <path
        d="M5 9c0-1 .8-2 2-2s2 1 2 2m6 0c0-1 .8-2 2-2s2 1 2 2"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
      <path
        d="M6 9c-1 3 .5 9 6 9s7-6 6-9"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
      <circle cx="10" cy="13" r="1" fill="currentColor" />
      <circle cx="14" cy="13" r="1" fill="currentColor" />
    </>
  ),
  "/zones": (
    <>
      <rect
        x="3"
        y="7"
        width="13"
        height="10"
        rx="2"
        stroke="currentColor"
        strokeWidth="1.8"
      />
      <path
        d="m16 11 5-3v8l-5-3v-2Z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
    </>
  ),
  "/settings": (
    <>
      <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.8" />
      <path
        d="M12 3v2.5M12 18.5V21M21 12h-2.5M5.5 12H3m13.6-6.6-1.8 1.8M9.2 14.8l-1.8 1.8m11.2 0-1.8-1.8M9.2 9.2 7.4 7.4"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </>
  ),
};

export function BottomNav({
  alertCount = 0,
  basePath = "",
}: {
  alertCount?: number;
  basePath?: string;
}) {
  const pathname = usePathname() ?? "/";
  if (shouldHide(pathname, basePath)) return null;

  return (
    <nav
      aria-label="Разделы"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-surface pb-[env(safe-area-inset-bottom)] md:hidden"
    >
      <ul className="mx-auto flex max-w-lg">
        {NAV.map((item) => {
          const href = withBase(basePath, item.href);
          const active = isActive(pathname, href);
          return (
            <li key={item.href} className="flex-1">
              <Link
                href={href}
                aria-current={active ? "page" : undefined}
                className={`tap flex flex-col items-center justify-center gap-1 py-2 transition-colors ${
                  active
                    ? "text-brand"
                    : "text-faint"
                }`}
              >
                <span className="relative">
                  <svg
                    viewBox="0 0 24 24"
                    fill="none"
                    className="h-6 w-6"
                    aria-hidden="true"
                  >
                    {ЗНАЧКИ[item.href]}
                  </svg>
                  {item.href === "/alerts" && alertCount > 0 && (
                    <span className="absolute -right-2 -top-1 inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-trouble px-1 text-[11px] font-semibold text-surface">
                      {alertCount}
                    </span>
                  )}
                </span>
                <span className="text-[11px] font-medium leading-none">
                  {item.label}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
