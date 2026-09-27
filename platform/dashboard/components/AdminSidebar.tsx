"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/admin", label: "Фермы", exact: true },
  { href: "/admin/farms/new", label: "Создать ферму", exact: false },
  { href: "/admin/training", label: "Отбраковка кадров", exact: false },
];

export function AdminSidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-full sm:w-60 shrink-0 border-b sm:border-b-0 sm:border-r border-line bg-surface px-4 py-4 sm:py-6">
      <div className="px-3 mb-4 sm:mb-8">
        <div className="text-sm font-medium text-ink">Мониторинг ферм</div>
        <div className="text-sm text-faint mt-0.5">Администратор</div>
      </div>

      <nav className="flex sm:block gap-2 sm:gap-0 sm:space-y-1 overflow-x-auto">
        {LINKS.map((link) => {
          const active = link.exact
            ? pathname === link.href
            : pathname.startsWith(link.href);
          return (
            <Link
              key={link.href}
              href={link.href}
              className={`block shrink-0 rounded-lg px-3 py-2 text-sm transition-colors ${
                active
                  ? "bg-line-soft text-ink font-medium"
                  : "text-muted hover:bg-soft hover:text-ink"
              }`}
            >
              {link.label}
            </Link>
          );
        })}
      </nav>

      <div className="mt-4 sm:mt-8 pt-4 sm:pt-6 border-t border-line">
        <Link
          href="/"
          className="block rounded-lg px-3 py-2 text-sm text-muted hover:bg-soft hover:text-ink transition-colors"
        >
          Экран фермы
        </Link>
      </div>
    </aside>
  );
}
