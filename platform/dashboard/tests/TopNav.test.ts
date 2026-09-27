import { describe, expect, it } from "vitest";
import { isActive, shouldHide } from "../components/ui/TopNav";

describe("подсветка активного раздела", () => {
  it("обзор подсвечен только на самом обзоре", () => {
    // Любой путь начинается со слэша: наивная проверка «начинается с href»
    // подсветила бы «Сводка» вообще всегда
    expect(isActive("/", "/")).toBe(true);
    expect(isActive("/animals", "/")).toBe(false);
    expect(isActive("/zones", "/")).toBe(false);
  });

  it("раздел подсвечен на своей странице", () => {
    expect(isActive("/animals", "/animals")).toBe(true);
    expect(isActive("/zones", "/zones")).toBe(true);
  });

  it("вложенная страница тоже подсвечивает раздел", () => {
    expect(isActive("/animals/123", "/animals")).toBe(true);
  });

  it("похожий по началу путь не считается своим", () => {
    // «/animals-archive» не относится к разделу «/animals»
    expect(isActive("/animals-archive", "/animals")).toBe(false);
  });

  it("чужой раздел не подсвечен", () => {
    expect(isActive("/zones", "/animals")).toBe(false);
  });
});

describe("где шапки быть не должно", () => {
  it("на входе", () => {
    // Переходить некуда, а ссылки на разделы всё равно потребуют входа
    expect(shouldHide("/login")).toBe(true);
  });

  it("на странице условий", () => {
    // Условия надо принять до того, как пускать в разделы
    expect(shouldHide("/terms")).toBe(true);
  });

  it("на обратном вызове входа", () => {
    expect(shouldHide("/auth/callback")).toBe(true);
  });

  it("на обычных страницах шапка есть", () => {
    expect(shouldHide("/")).toBe(false);
    expect(shouldHide("/animals")).toBe(false);
    expect(shouldHide("/settings")).toBe(false);
    expect(shouldHide("/admin")).toBe(false);
  });
});
