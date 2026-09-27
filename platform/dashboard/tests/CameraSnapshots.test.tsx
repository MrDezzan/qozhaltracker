import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { CameraSnapshots } from "../components/CameraSnapshots";
import { CameraSnapshot } from "../lib/snapshots";

const now = new Date("2026-08-09T12:00:00.000Z");

const snap = (overrides: Partial<CameraSnapshot> = {}): CameraSnapshot => ({
  cameraId: "cam-1",
  cameraName: "Кормовой стол",
  url: "/api/frame/cam-1",
  liveUrl: "/api/frame/cam-1",
  hasStream: false,
  updatedAt: "2026-08-09T11:59:00.000Z",
  ...overrides,
});

describe("Трансляция с камер", () => {
  it("без камер сообщает, что оборудование не подключено", () => {
    render(<CameraSnapshots snapshots={[]} now={now} />);
    expect(screen.getByText("Камеры не подключены")).toBeInTheDocument();
  });

  it("номер и название камеры стоят в заголовке", () => {
    // «Трансляция с камеры №1» вместо «Что сейчас видно»: человек должен
    // понимать, на что он смотрит, без догадок
    render(<CameraSnapshots snapshots={[snap()]} now={now} />);
    const заголовок = screen.getByRole("heading", { level: 2 });
    expect(заголовок).toHaveTextContent("Трансляция с камеры №1");
    expect(заголовок).toHaveTextContent("Кормовой стол");
  });

  it("камера без кадра окна не получает", () => {
    // Пустое окно с подписью «Камера №2» утверждало, что кадр есть.
    // Человек решал, что сломана программа
    render(
      <CameraSnapshots
        snapshots={[snap(), snap({ cameraId: "cam-2", cameraName: "Проход", url: null, updatedAt: null })]}
        now={now}
      />,
    );
    expect(screen.getAllByRole("img")).toHaveLength(1);
    expect(screen.getByText(/Без сигнала/)).toBeInTheDocument();
    expect(screen.getByText("кадров не поступало")).toBeInTheDocument();
  });

  it("когда кадра нет ни с одной камеры, окон нет вовсе", () => {
    render(
      <CameraSnapshots
        snapshots={[
          snap({ url: null, updatedAt: null }),
          snap({ cameraId: "cam-2", url: null, updatedAt: null }),
        ]}
        now={now}
      />,
    );
    expect(screen.queryAllByRole("img")).toHaveLength(0);
    expect(screen.getByText("Сигнал с камер не поступает")).toBeInTheDocument();
    expect(screen.getByText(/техническую поддержку/)).toBeInTheDocument();
  });

  it("у камеры без кадра указано время последнего", () => {
    render(
      <CameraSnapshots
        snapshots={[snap(), snap({ cameraId: "cam-2", url: null, updatedAt: "2026-08-09T09:00:00.000Z" })]}
        now={now}
      />,
    );
    expect(screen.getByText(/последний кадр 3 часа назад/)).toBeInTheDocument();
  });

  it("переключатель камер стоит над кадром", () => {
    render(
      <CameraSnapshots
        snapshots={[
          snap(),
          snap({ cameraId: "cam-2", cameraName: "Проход" }),
          snap({ cameraId: "cam-3", cameraName: "Периметр" }),
        ]}
        now={now}
      />,
    );
    const переключатель = screen.getByRole("tablist", { name: "Выбор камеры" });
    expect(переключатель).toBeInTheDocument();
    // По кнопке на камеру плюс «Все камеры»: до двадцатой камеры один
    // переход, а не двадцать нажатий стрелкой
    expect(screen.getAllByRole("tab")).toHaveLength(4);
    expect(screen.getByRole("tab", { name: "Все камеры" })).toBeInTheDocument();
  });

  it("метка в адресе меняется вместе с кадром", () => {
    // Без неё браузер покажет прежнюю картинку по тому же адресу
    render(<CameraSnapshots snapshots={[snap()]} now={now} />);
    const img = screen.getByRole("img", { name: /Кормовой стол/ });
    expect(img.getAttribute("src")).toContain("2026-08-09T11:59");
  });

  it("видно, когда пришёл кадр", () => {
    render(<CameraSnapshots snapshots={[snap()]} now={now} />);
    expect(screen.getByText("кадр 1 минуту назад")).toBeInTheDocument();
  });

  it("устаревший кадр приглушён, чтобы не принять его за живой", () => {
    render(
      <CameraSnapshots
        snapshots={[snap({ updatedAt: "2026-08-09T10:00:00.000Z" })]}
        now={now}
      />,
    );
    expect(screen.getByRole("img").className).toContain("opacity-60");
  });

  it("свежий кадр не приглушается", () => {
    render(<CameraSnapshots snapshots={[snap()]} now={now} />);
    expect(screen.getByRole("img").className).not.toContain("opacity-60");
  });

  it("в режиме сетки видны все камеры с кадром", () => {
    render(
      <CameraSnapshots
        snapshots={[snap(), snap({ cameraId: "cam-2", cameraName: "Поилка" })]}
        now={now}
      />,
    );
    expect(screen.getAllByRole("img")).toHaveLength(2);
  });

  it("нумерация не сбивается от камер без сигнала", () => {
    // Номер это адрес камеры на ферме. Если он поедет, когда одна
    // камера отвалилась, все прежние разговоры про «камеру №3» станут
    // неверными
    render(
      <CameraSnapshots
        snapshots={[
          snap({ cameraId: "cam-1", url: null, updatedAt: null }),
          snap({ cameraId: "cam-2", cameraName: "Проход" }),
        ]}
        now={now}
      />,
    );
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(
      "Трансляция с камеры №2",
    );
  });
});
