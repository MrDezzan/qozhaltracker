import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { HeadcountChart } from "../components/HeadcountChart";

describe("HeadcountChart", () => {
  it("shows a placeholder when there are no points", () => {
    render(<HeadcountChart points={[]} />);
    expect(screen.getByText(/Данных для графика недостаточно/i)).toBeInTheDocument();
  });

  it("renders one bar per data point", () => {
    const { container } = render(
      <HeadcountChart
        points={[
          { bucketStart: "2026-08-07T10:00:00.000Z", count: 2 },
          { bucketStart: "2026-08-07T10:01:00.000Z", count: 5 },
        ]}
      />
    );
    expect(container.querySelectorAll("rect")).toHaveLength(2);
  });
});

describe("HeadcountChart axis labels", () => {
  it("shows the maximum value on the vertical axis", () => {
    render(
      <HeadcountChart
        points={[
          { bucketStart: "2026-08-07T10:00:00.000Z", count: 2 },
          { bucketStart: "2026-08-07T10:01:00.000Z", count: 7 },
        ]}
      />
    );
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("0")).toBeInTheDocument();
  });

  it("labels the time axis with hours and minutes", () => {
    // 14:35 по Гринвичу это 19:35 на ферме. Раньше подпись брали срезом
    // строки, то есть показывали UTC, и соседний график по часам
    // противоречил этому на пять часов
    render(
      <HeadcountChart
        points={[{ bucketStart: "2026-08-07T14:35:00.000Z", count: 1 }]}
        timeZone="Asia/Almaty"
      />,
    );
    expect(screen.getByText("19:35")).toBeInTheDocument();
  });

  it("explains the empty state instead of just saying no data", () => {
    render(<HeadcountChart points={[]} />);
    expect(screen.getByText(/после первых подсчётов/i)).toBeInTheDocument();
  });
});
