import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { EventsTable, meaningfulEvents } from "../components/EventsTable";
import { EventRow } from "../lib/formatters";

const event = (overrides: Partial<EventRow> = {}): EventRow => ({
  id: "evt-1",
  camera_id: "cam-1",
  animal_id: null,
  event_type: "zone_exit",
  payload: { zone_name: "Кормушка", duration_s: 720 },
  occurred_at: "2026-08-07T10:00:00.000Z",
  ...overrides,
});

describe("meaningfulEvents", () => {
  it("выбрасывает поштучные обнаружения", () => {
    const events = [event(), event({ id: "2", event_type: "detected" })];
    expect(meaningfulEvents(events)).toHaveLength(1);
  });

  it("выбрасывает сводки поголовья", () => {
    // Строка «1 гол.» каждую минуту забивает ленту так, что настоящие
    // события в ней не найти. Само число есть и на плитке, и на графике
    const events = [event(), event({ id: "2", event_type: "counted" })];
    expect(meaningfulEvents(events)).toHaveLength(1);
  });

  it("оставляет визиты в зоны", () => {
    expect(meaningfulEvents([event()])).toHaveLength(1);
  });
});

describe("EventsTable", () => {
  it("shows a placeholder message when there are no events", () => {
    render(<EventsTable events={[]} />);
    expect(screen.getByText(/Событий пока нет/i)).toBeInTheDocument();
  });

  it("shows the placeholder when only noise arrived", () => {
    render(<EventsTable events={[event({ event_type: "counted" })]} />);
    expect(screen.getByText(/Событий пока нет/i)).toBeInTheDocument();
  });

  it("renders a zone visit with its name and duration", () => {
    render(
      <EventsTable
        events={[
          event({
            event_type: "zone_exit",
            payload: { zone_name: "Кормушка", duration_s: 720 },
          }),
        ]}
      />
    );
    expect(screen.getByText("Кормушка или поилка")).toBeInTheDocument();
    expect(screen.getByText("Кормушка — 12 мин")).toBeInTheDocument();
  });

  it("shows short visits in seconds", () => {
    render(
      <EventsTable
        events={[
          event({ event_type: "zone_exit", payload: { zone_name: "Поилка", duration_s: 40 } }),
        ]}
      />
    );
    expect(screen.getByText("Поилка — 40 с")).toBeInTheDocument();
  });

  it("shows the camera name when it is known", () => {
    render(<EventsTable events={[event()]} cameraNames={{ "cam-1": "Кормушка" }} />);
    expect(screen.getByText("Кормушка")).toBeInTheDocument();
  });

  it("falls back to a distinct label when the camera name is unknown", () => {
    render(<EventsTable events={[event()]} />);
    expect(screen.getByText("Без названия")).toBeInTheDocument();
  });

  it("falls back to the raw event type for unknown kinds", () => {
    render(<EventsTable events={[event({ event_type: "custom_thing" })]} />);
    expect(screen.getByText("custom_thing")).toBeInTheDocument();
  });
});
