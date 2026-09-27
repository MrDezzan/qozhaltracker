import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { CollapsibleCard } from "../components/ui/CollapsibleCard";

describe("CollapsibleCard", () => {
  it("shows the title and content", () => {
    render(
      <CollapsibleCard title="Последние события">
        <p>содержимое</p>
      </CollapsibleCard>
    );
    expect(screen.getByText("Последние события")).toBeInTheDocument();
    expect(screen.getByText("содержимое")).toBeInTheDocument();
  });

  it("is open by default", () => {
    const { container } = render(
      <CollapsibleCard title="Заголовок">
        <p>содержимое</p>
      </CollapsibleCard>
    );
    expect(container.querySelector("details")).toHaveAttribute("open");
  });

  it("can start collapsed", () => {
    const { container } = render(
      <CollapsibleCard title="Заголовок" defaultOpen={false}>
        <p>содержимое</p>
      </CollapsibleCard>
    );
    expect(container.querySelector("details")).not.toHaveAttribute("open");
  });

  it("offers both labels so the state is readable either way", () => {
    render(
      <CollapsibleCard title="Заголовок">
        <p>содержимое</p>
      </CollapsibleCard>
    );
    expect(screen.getByText("Свернуть")).toBeInTheDocument();
    expect(screen.getByText("Развернуть")).toBeInTheDocument();
  });

  it("shows the description when given", () => {
    render(
      <CollapsibleCard title="Заголовок" description="Пояснение">
        <p>содержимое</p>
      </CollapsibleCard>
    );
    expect(screen.getByText("Пояснение")).toBeInTheDocument();
  });
});
