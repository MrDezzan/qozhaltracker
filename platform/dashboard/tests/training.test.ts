import { describe, it, expect, vi } from "vitest";
import type { SupabaseClient } from "@supabase/supabase-js";
import {
  FIRST_BATCH,
  MIN_DAYS,
  REASON_LABELS,
  VERDICTS,
  collectionAdvice,
  getNextFrame,
  getTrainingFrameUrl,
  getTrainingSummary,
  isVerdict,
  usableForLabelling,
  type TrainingSummaryRow,
} from "../lib/training";

function rpcClient(data: unknown, error: unknown = null) {
  return { rpc: vi.fn().mockResolvedValue({ data, error }) } as unknown as SupabaseClient;
}

function storageClient(data: unknown, error: unknown = null) {
  return {
    storage: {
      from: vi.fn().mockReturnValue({
        createSignedUrl: vi.fn().mockResolvedValue({ data, error }),
      }),
    },
  } as unknown as SupabaseClient;
}

function row(over: Partial<TrainingSummaryRow> = {}): TrainingSummaryRow {
  return {
    farm_id: "f1",
    farm_name: "Заря",
    total: 0,
    pending: 0,
    ok: 0,
    merged: 0,
    missed: 0,
    junk: 0,
    days: 0,
    first_at: null,
    last_at: null,
    ...over,
  };
}

describe("вердикты", () => {
  it("их ровно четыре", () => {
    expect(VERDICTS).toEqual(["ok", "merged", "missed", "junk"]);
  });

  it("чужое значение не проходит", () => {
    // Вердикт приходит из формы, то есть из браузера. Без проверки в
    // базу ушло бы что угодно, и функция упала бы там, где починить
    // труднее всего
    expect(isVerdict("отлично")).toBe(false);
    expect(isVerdict("")).toBe(false);
    expect(isVerdict(null)).toBe(false);
    expect(isVerdict(42)).toBe(false);
  });

  it("свои проходят", () => {
    for (const v of VERDICTS) expect(isVerdict(v)).toBe(true);
  });
});

describe("причины отбора", () => {
  it("у каждой причины есть человеческое название", () => {
    // Причины перечислены в миграции 0042 в check-ограничении. Кадр с
    // причиной без подписи показал бы админу «count_jump», и что с этим
    // делать, понять было бы неоткуда
    for (const reason of ["crowded", "count_jump", "low_confidence", "routine"]) {
      expect(REASON_LABELS[reason]).toBeDefined();
      expect(REASON_LABELS[reason].title.length).toBeGreaterThan(0);
    }
  });
});

describe("getNextFrame", () => {
  it("зовёт функцию базы", async () => {
    const client = rpcClient([{ id: "k1", pending: 5 }]);
    const frame = await getNextFrame(client, "f1");
    expect(client.rpc).toHaveBeenCalledWith("next_training_frame", {
      p_farm_id: "f1",
    });
    expect(frame?.id).toBe("k1");
  });

  it("без фермы просит любую", async () => {
    const client = rpcClient([]);
    await getNextFrame(client);
    expect(client.rpc).toHaveBeenCalledWith("next_training_frame", {
      p_farm_id: null,
    });
  });

  it("пусто, когда всё разобрано", async () => {
    await expect(getNextFrame(rpcClient([]))).resolves.toBeNull();
  });

  it("пусто при ошибке, а не падение", async () => {
    // Экран отбраковки не должен ронять весь раздел админки из-за
    // недоступной таблицы: остальные страницы к ней отношения не имеют
    await expect(
      getNextFrame(rpcClient(null, { message: "нет доступа" }))
    ).resolves.toBeNull();
  });
});

describe("ссылка на кадр", () => {
  it("подписывается", async () => {
    const client = storageClient({ signedUrl: "https://x/подпись" });
    await expect(getTrainingFrameUrl(client, "f/c/2026-08-21/1.jpg")).resolves.toBe(
      "https://x/подпись"
    );
    expect(client.storage.from).toHaveBeenCalledWith("training");
  });

  it("пусто, если файла нет", async () => {
    // Строка в базе есть, а файл не загрузился. Экран покажет подсказку
    // «отметьте мусор» вместо битой картинки
    await expect(
      getTrainingFrameUrl(storageClient(null, { message: "not found" }), "нет.jpg")
    ).resolves.toBeNull();
  });
});

describe("сводка", () => {
  it("пусто при ошибке", async () => {
    await expect(
      getTrainingSummary(rpcClient(null, { message: "нет" }))
    ).resolves.toEqual([]);
  });

  it("считает только кадры с ошибками", () => {
    // Кадров может быть собрано десять тысяч, а полезных для обучения —
    // двадцать. Общее число говорит о работе устройства, а не о том,
    // сколько модель может из этого узнать
    expect(usableForLabelling(row({ total: 10000, ok: 9980, merged: 15, missed: 5 })))
      .toBe(20);
  });

  it("кадры без ошибок в счёт не идут", () => {
    expect(usableForLabelling(row({ total: 500, ok: 500 }))).toBe(0);
  });

  it("мусор в счёт не идёт", () => {
    expect(usableForLabelling(row({ junk: 300 }))).toBe(0);
  });
});

describe("совет, что делать дальше", () => {
  it("сначала просит доотбраковать", () => {
    const advice = collectionAdvice(row({ pending: 42, days: 30, merged: 999 }));
    expect(advice).toContain("42");
  });

  it("мало дней съёмки — просит продолжать, даже если кадров много", () => {
    // Полторы тысячи кадров за один день — это одна погода и одно
    // освещение. Модель заучит именно их и на следующей неделе
    // перестанет работать
    const advice = collectionAdvice(
      row({ days: 2, merged: FIRST_BATCH * 2, total: 5000 })
    );
    expect(advice).toContain("продолжайте сбор");
  });

  it("дней хватает, а ошибок мало — просит продолжать", () => {
    const advice = collectionAdvice(row({ days: MIN_DAYS, merged: 10 }));
    expect(advice).toContain("продолжайте сбор");
  });

  it("готово, когда есть и дни, и ошибки", () => {
    const advice = collectionAdvice(
      row({ days: MIN_DAYS, merged: FIRST_BATCH, missed: 5 })
    );
    expect(advice).toContain("Готово к разметке");
  });

  it("ровно на границе по дням ещё не готово без ошибок", () => {
    expect(collectionAdvice(row({ days: MIN_DAYS - 1, merged: FIRST_BATCH })))
      .toContain("продолжайте сбор");
  });

  it("пустая ферма не выглядит готовой", () => {
    expect(collectionAdvice(row())).toContain("продолжайте сбор");
  });
});
