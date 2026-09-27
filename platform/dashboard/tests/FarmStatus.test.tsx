import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FarmStatus, tone } from "../components/FarmStatus";

/**
 * Первое, что видит фермер, открыв экран.
 *
 * Здесь стояло кольцо с числом «77 из 100». Выглядело уместно, значило
 * мало: семьдесят семь чего, насколько это плохо и что сделать, чтобы
 * стало больше, — по кольцу не понять. Первый взгляд оно отнимало, а
 * ответа не давало.
 */
describe("Ответ вместо оценки", () => {
  it("говорит словами, а не числом", () => {
    render(
      <FarmStatus
        condition={{ score: 92, label: "В норме", reasons: [] }}
        farmName="Жайлау"
      />,
    );
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Отклонений нет",
    );
    expect(screen.queryByText("92")).toBeNull();
  });

  it("называет, что именно не так", () => {
    render(
      <FarmStatus
        condition={{
          score: 40,
          label: "Есть проблемы",
          reasons: [
            { kind: "нет-связи" as const, text: "нет связи с фермой" },
            { kind: "нет-камер" as const, text: "камеры не подключены" },
          ],
        }}
        farmName="Жайлау"
      />,
    );
    expect(screen.getByText("нет связи с фермой")).toBeInTheDocument();
    expect(screen.getByText("камеры не подключены")).toBeInTheDocument();
  });

  it("кнопка ведёт туда, где чинят именно эту причину", () => {
    // Без кнопки человек прочитает, что не так, и останется с этим
    // один на один. Одна кнопка на все причины не годится: с
    // неотмеченными кормушками надо в разметку, а не «проверить камеры»
    render(
      <FarmStatus
        condition={{
          score: 40,
          label: "Есть проблемы",
          reasons: [{ kind: "нет-зон" as const, text: "кормушки не отмечены" }],
        }}
        farmName="Жайлау"
      />,
    );
    expect(
      screen.getByRole("link", { name: "Разметить кормушки" }),
    ).toHaveAttribute("href", "/zones");
  });

  it("там, где фермер бессилен, кнопки нет: она увела бы не туда", () => {
    render(
      <FarmStatus
        condition={{
          score: 30,
          label: "Есть проблемы",
          reasons: [{ kind: "нет-связи" as const, text: "нет связи с фермой" }],
        }}
        farmName="Жайлау"
      />,
    );
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText(/обратитесь в поддержку/i)).toBeInTheDocument();
  });

  it("когда всё спокойно, никуда не гонит", () => {
    render(
      <FarmStatus
        condition={{ score: 95, label: "В норме", reasons: [] }}
        farmName="Жайлау"
      />,
    );
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("смысл не передаётся одним цветом", () => {
    // Каждый пятнадцатый мужчина не различает красный и зелёный, а
    // экран смотрят на солнце, где зелёный и янтарный сливаются
    const { container } = render(
      <FarmStatus
        condition={{
          score: 30,
          label: "Есть проблемы",
          reasons: [{ kind: "нет-камер" as const, text: "камеры не подключены" }],
        }}
        farmName="Жайлау"
      />,
    );
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBeTruthy();
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("значок спрятан от читалки: слово рядом уже всё сказало", () => {
    const { container } = render(
      <FarmStatus
        condition={{ score: 95, label: "В норме", reasons: [] }}
        farmName="Жайлау"
      />,
    );
    expect(container.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
  });

  it("название фермы есть, но не вместо ответа", () => {
    render(
      <FarmStatus
        condition={{ score: 95, label: "В норме", reasons: [] }}
        farmName="Жайлау"
      />,
    );
    const заголовок = screen.getByRole("heading", { level: 1 });
    expect(заголовок.textContent).not.toContain("Жайлау");
    expect(screen.getByText("Жайлау")).toBeInTheDocument();
  });
});

describe("Три состояния", () => {
  it.each([
    [100, "calm"],
    [85, "calm"],
    [84, "watch"],
    [60, "watch"],
    [59, "trouble"],
    [0, "trouble"],
  ])("оценка %i — это «%s»", (оценка, ждём) => {
    expect(tone(оценка as number)).toBe(ждём);
  });
});
