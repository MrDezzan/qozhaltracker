import { ReactNode } from "react";

type Variant = "primary" | "secondary" | "danger";

/**
 * Кнопка.
 *
 * Главное здесь — высота. Она задана токеном `--tap-min` (48 пикселей),
 * и это не про красоту: ниже этого палец в перчатке промахивается по
 * соседней кнопке. Раньше высота набиралась отступами `py-2`, то есть
 * зависела от размера шрифта внутри, — и на коротком тексте кнопка
 * выходила в тридцать с небольшим пикселей.
 *
 * ПОЧЕМУ У ОСНОВНОЙ КНОПКИ ТЁМНЫЕ БУКВЫ НА ТЁПЛОЙ ЗАЛИВКЕ
 *
 * В макете сайта терракотовая кнопка подписана белым. Контраст такой
 * пары 2.77 при норме 4.5: подпись на ней не читается ни на солнце, ни
 * на плохом проекторе. Тёмно-синие буквы по той же заливке дают 5.81 и
 * выглядят так же тепло.
 *
 * КОНТУР ОБЯЗАТЕЛЕН
 *
 * Сама терракота к молочному фону даёт 2.52, то есть край кнопки на
 * светлом фоне теряется. WCAG 1.4.11 требует 3:1 для границы органа
 * управления, и её даёт контур цветом --clay-deep: 4.7 к фону.
 */
const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-action text-on-action border-action-hover hover:bg-action-hover hover:text-surface",
  secondary:
    "bg-surface text-ink border-line-strong hover:bg-leaf-bg",
  danger:
    "bg-surface text-trouble border-trouble hover:bg-trouble-bg",
};

export function Button({
  children,
  variant = "primary",
  type = "button",
  disabled,
  className = "",
  onClick,
}: {
  children: ReactNode;
  variant?: Variant;
  type?: "button" | "submit";
  disabled?: boolean;
  className?: string;
  onClick?: () => void;
}) {
  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      className={`tap inline-flex cursor-pointer items-center justify-center rounded-[var(--button-radius)] border px-5 text-[length:var(--text-base)] font-medium transition-colors duration-200 disabled:cursor-not-allowed disabled:opacity-40 ${VARIANTS[variant]} ${className}`}
    >
      {children}
    </button>
  );
}
