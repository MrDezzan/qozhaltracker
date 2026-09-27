import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { FeedingTable } from "../components/FeedingTable";
import { ZoneSummary } from "../lib/feeding";

const zone = (overrides: Partial<ZoneSummary> = {}): ZoneSummary => ({
  zoneId: "z1",
  zoneName: "Кормушка",
  zoneKind: "feeder",
  visits: 12,
  totalSeconds: 3900,
  averageSeconds: 325,
  ...overrides,
});

describe("FeedingTable", () => {
  it("объясняет, что делать, когда кормушки не размечены", () => {
    // Пустой экран без подсказки — самая частая причина «непонятно».
    // Слова тут не про наше устройство («зоны»), а про то, что фермер
    // видит в загоне: кормушка
    render(<FeedingTable zones={[]} />);
    expect(screen.getByText(/Зоны кормления не заданы/i)).toBeInTheDocument();
    expect(screen.getByText(/после разметки зоны/i)).toBeInTheDocument();
  });

  it("пустое состояние называет, чего не хватает и что сделать", () => {
    /*
      Здесь стояло правило «в пустом состоянии не должно быть слова
      зона»: считалось, что фермер говорит «кормушка», а «зона» это
      наше слово. Правило снято сознательно.

      «Зона кормления» это термин продукта: он стоит в разделе
      разметки, в договоре и в разговоре с монтажником. Разные слова
      для одного и того же в разных местах экрана путают сильнее, чем
      незнакомое слово, объяснённое рядом.

      Требование к пустому состоянию осталось прежним: сказать, чего
      не хватает, и что с этим делать.
    */
    const { container } = render(<FeedingTable zones={[]} />);
    const текст = container.textContent ?? "";
    expect(текст).toContain("Зоны кормления не заданы");
    expect(текст).toContain("после разметки зоны");
  });

  it("shows visits and readable durations", () => {
    render(<FeedingTable zones={[zone()]} />);
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("1 ч 05 мин")).toBeInTheDocument();
  });

  it("does not repeat the kind when it duplicates the name", () => {
    render(<FeedingTable zones={[zone({ zoneKind: "feeder", zoneName: "Кормушка" })]} />);
    expect(screen.getAllByText("Кормушка")).toHaveLength(1);
  });

  it("shows the kind when the name is more specific", () => {
    render(<FeedingTable zones={[zone({ zoneKind: "water", zoneName: "Поилка слева" })]} />);
    expect(screen.getByText("Поилка слева")).toBeInTheDocument();
    expect(screen.getByText("Поилка")).toBeInTheDocument();
  });

  it("renders one row per zone", () => {
    render(
      <FeedingTable
        zones={[zone(), zone({ zoneId: "z2", zoneName: "Поилка", zoneKind: "water" })]}
      />
    );
    expect(screen.getAllByRole("row")).toHaveLength(3);
  });
});
