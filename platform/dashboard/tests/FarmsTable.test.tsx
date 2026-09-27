import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { FarmsTable } from "../components/FarmsTable";
import { FarmOverviewRow } from "../lib/adminData";

vi.mock("next/link", () => ({
  default: ({ children, href }: any) => <a href={href}>{children}</a>,
}));

const now = new Date("2026-08-09T12:00:00.000Z");

const farm = (overrides: Partial<FarmOverviewRow> = {}): FarmOverviewRow => ({
  farm_id: "f1",
  farm_name: "Заря",
  farm_created_at: "2026-08-01T00:00:00.000Z",
  cameras_count: 4,
  device_last_seen: "2026-08-09T11:59:00.000Z",
  events_24h: 120,
  last_event_at: "2026-08-09T11:58:00.000Z",
  ...overrides,
});

describe("FarmsTable", () => {
  it("shows a hint when there are no farms", () => {
    render(<FarmsTable farms={[]} now={now} />);
    expect(screen.getByText(/Ферм пока нет/i)).toBeInTheDocument();
  });

  it("shows a farm with a recent heartbeat as online", () => {
    render(<FarmsTable farms={[farm()]} now={now} />);
    expect(screen.getByText("Онлайн")).toBeInTheDocument();
    expect(screen.getByText("Заря")).toBeInTheDocument();
  });

  it("shows a farm with a stale heartbeat as offline", () => {
    render(<FarmsTable farms={[farm({ device_last_seen: "2026-08-09T10:00:00.000Z" })]} now={now} />);
    expect(screen.getByText("Офлайн")).toBeInTheDocument();
  });

  it("shows a farm that never reported as offline", () => {
    render(<FarmsTable farms={[farm({ device_last_seen: null })]} now={now} />);
    expect(screen.getByText("Офлайн")).toBeInTheDocument();
  });

  it("links to the farm page", () => {
    render(<FarmsTable farms={[farm()]} now={now} />);
    expect(screen.getByRole("link", { name: "Заря" })).toHaveAttribute(
      "href",
      "/admin/farms/f1"
    );
  });

  it("renders a dash when there were no events yet", () => {
    render(<FarmsTable farms={[farm({ last_event_at: null })]} now={now} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
