import { describe, it, expect, vi } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { requireFarmId, describeAuthError, НЕ_ВОШЁЛ } from "../lib/auth";

function makeMockClient(userId: string | null, farmRow: unknown, farmError: unknown = null) {
  return {
    auth: {
      getSession: vi.fn().mockResolvedValue({
        data: { session: userId ? { user: { id: userId } } : null },
      }),
    },
    from: vi.fn().mockReturnValue({
      select: vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          limit: vi.fn().mockReturnValue({
            single: vi.fn().mockResolvedValue({ data: farmRow, error: farmError }),
          }),
        }),
      }),
    }),
  } as any;
}

describe("requireFarmId", () => {
  it("throws when there is no session", async () => {
    const client = makeMockClient(null, null);
    await expect(requireFarmId(client)).rejects.toThrow(/не вошли/);
  });

  it("throws when the user has no farm", async () => {
    const client = makeMockClient("user-1", null, { message: "no rows" });
    await expect(requireFarmId(client)).rejects.toThrow(/нет фермы/);
  });

  it("returns the farm id for the current user", async () => {
    const client = makeMockClient("user-1", { id: "farm-1" });
    const farm = await requireFarmId(client);
    expect(farm).toBe("farm-1");
    expect(client.from).toHaveBeenCalledWith("farms");
  });
});

describe("describeAuthError", () => {
  it("translates invalid credentials", () => {
    expect(describeAuthError("Invalid login credentials")).toMatch(/Неверный email или пароль/);
  });

  it("translates email rate limit", () => {
    expect(describeAuthError("email rate limit exceeded")).toMatch(/Слишком много писем/);
  });

  it("passes through unknown messages unchanged", () => {
    expect(describeAuthError("something odd")).toBe("something odd");
  });
});

describe("«Вы не вошли» живёт в одном месте", () => {
  /*
    Эту ошибку не только показывают: по ней узнают ситуацию и решают,
    вести человека на вход или на главную. Пока сравнивали по куску
    текста, переименование самой ошибки тихо ломало разбор: админский
    макет искал «не авторизован», не находил и отправлял незалогиненного
    человека на главную вместо страницы входа. Оба пути ведут на живой
    экран, поэтому в глаза это не бросается.
  */
  function исходники(корень: string): string[] {
    const найдено: string[] = [];
    const обойти = (папка: string) => {
      for (const имя of readdirSync(папка)) {
        const путь = join(папка, имя);
        if (statSync(путь).isDirectory()) обойти(путь);
        else if (путь.endsWith(".ts") || путь.endsWith(".tsx")) найдено.push(путь);
      }
    };
    обойти(join(process.cwd(), корень));
    return найдено;
  }

  it("текст ошибки задан один раз", () => {
    const свои = ["app", "components", "lib"].flatMap(исходники);
    const дубли = свои.filter((путь) => {
      if (путь.endsWith("lib/auth.ts")) return false;
      return readFileSync(путь, "utf8").includes(`"${НЕ_ВОШЁЛ}"`);
    });
    expect(дубли).toEqual([]);
  });

  it("никто не разбирает ошибку по куску текста", () => {
    // Комментарии срезаем: в admin/layout.tsx эта поломка разобрана
    // словами, и без этого тест спотыкается о собственное объяснение
    const безКомментариев = (код: string) =>
      код.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
    const свои = ["app", "components", "lib"].flatMap(исходники);
    const поКуску = свои.filter((путь) =>
      /includes\(\s*["'`][^"'`]*(?:не вошли|авторизован)/.test(
        безКомментариев(readFileSync(путь, "utf8")),
      ),
    );
    expect(поКуску).toEqual([]);
  });
});
