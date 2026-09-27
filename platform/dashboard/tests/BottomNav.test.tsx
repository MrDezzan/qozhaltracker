import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const путь = vi.hoisted(() => ({ значение: "/" }));
vi.mock("next/navigation", () => ({ usePathname: () => путь.значение }));

import { BottomNav } from "../components/ui/BottomNav";
import { NAV } from "../components/ui/TopNav";

/**
 * Разделы внизу экрана — только на телефоне.
 *
 * Телефон держат одной рукой, и большой палец достаёт до нижней трети.
 * Верхняя полоса требует перехватить телефон или тянуться второй
 * рукой; в загоне, где вторая рука занята, это значит «не буду
 * переходить».
 */
describe("Полоса разделов внизу", () => {
  it("показывает все разделы", () => {
    путь.значение = "/";
    render(<BottomNav />);
    for (const раздел of NAV) {
      expect(screen.getByText(раздел.label)).toBeInTheDocument();
    }
  });

  it("разделов не больше пяти", () => {
    // Шестой раздел внизу телефона — это кнопка шириной в палец
    // ребёнка. Промахнуться по ней проще, чем попасть
    expect(NAV.length).toBeLessThanOrEqual(5);
  });

  it("берёт список у верхней полосы, а не свой", () => {
    // Два списка разойдутся, и раздел, пропавший на компьютере,
    // заметят случайно
    путь.значение = "/";
    render(<BottomNav />);
    const ссылки = screen.getAllByRole("link");
    expect(ссылки).toHaveLength(NAV.length);
  });

  it("отмечает, где человек находится", () => {
    путь.значение = "/animals";
    render(<BottomNav />);
    const текущий = screen.getByText("Поголовье").closest("a");
    expect(текущий).toHaveAttribute("aria-current", "page");
  });

  it("на входе и на условиях не показывается", () => {
    // Там переходить некуда, а ссылки на разделы, которые всё равно
    // потребуют входа, только мешают
    for (const где of ["/login", "/terms", "/auth/callback"]) {
      путь.значение = где;
      const { container } = render(<BottomNav />);
      expect(container.firstChild).toBeNull();
    }
  });

  it("число тревог видно", () => {
    путь.значение = "/";
    render(<BottomNav alertCount={3} />);
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("нуля тревог не показывает", () => {
    путь.значение = "/";
    const { container } = render(<BottomNav alertCount={0} />);
    expect(container.textContent).not.toContain("0");
  });

  it("у каждого раздела и значок, и подпись", () => {
    // Значок без подписи экономит место и стоит понимания: «домик» —
    // это обзор или настройки фермы?
    путь.значение = "/";
    render(<BottomNav />);
    for (const раздел of NAV) {
      const ссылка = screen.getByText(раздел.label).closest("a");
      expect(ссылка?.querySelector("svg")).not.toBeNull();
    }
  });

  it("значки спрятаны от читалки", () => {
    путь.значение = "/";
    const { container } = render(<BottomNav />);
    for (const значок of container.querySelectorAll("svg")) {
      expect(значок.getAttribute("aria-hidden")).toBe("true");
    }
  });
});
