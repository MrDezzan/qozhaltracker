import { describe, it, expect, vi } from "vitest";
import { describeError, isRetriableError, withRetry } from "../lib/retry";

const noSleep = async () => {};

describe("describeError", () => {
  it("returns the message of a plain error", () => {
    expect(describeError(new Error("boom"))).toBe("boom");
  });

  it("unwraps the hidden cause of fetch failed", () => {
    const inner = new Error("getaddrinfo ENOTFOUND db.supabase.co");
    const outer = new Error("fetch failed", { cause: inner });
    expect(describeError(outer)).toBe("fetch failed: getaddrinfo ENOTFOUND db.supabase.co");
  });

  it("walks nested causes", () => {
    const deepest = new Error("ECONNRESET");
    const middle = new Error("socket hang up", { cause: deepest });
    const outer = new Error("fetch failed", { cause: middle });
    expect(describeError(outer)).toContain("ECONNRESET");
  });

  it("does not repeat identical messages", () => {
    const outer = new Error("fetch failed", { cause: new Error("fetch failed") });
    expect(describeError(outer)).toBe("fetch failed");
  });

  it("handles non-error values", () => {
    expect(describeError("just a string")).toBe("just a string");
  });
});

describe("isRetriableError", () => {
  it("treats fetch failures as retriable", () => {
    expect(isRetriableError(new Error("TypeError: fetch failed"))).toBe(true);
  });

  it("treats connection resets as retriable", () => {
    expect(isRetriableError(new Error("read ECONNRESET"))).toBe(true);
  });

  it("does not retry business errors", () => {
    expect(isRetriableError(new Error("Название фермы не может быть пустым"))).toBe(false);
  });

  it("looks inside the cause chain", () => {
    const outer = new Error("something", { cause: new Error("ETIMEDOUT") });
    expect(isRetriableError(outer)).toBe(true);
  });
});

describe("withRetry", () => {
  it("returns the result on first success", async () => {
    const op = vi.fn().mockResolvedValue("ok");
    await expect(withRetry(op, { sleep: noSleep })).resolves.toBe("ok");
    expect(op).toHaveBeenCalledTimes(1);
  });

  it("retries a network failure and succeeds", async () => {
    const op = vi
      .fn()
      .mockRejectedValueOnce(new Error("fetch failed"))
      .mockResolvedValue("ok");
    await expect(withRetry(op, { sleep: noSleep })).resolves.toBe("ok");
    expect(op).toHaveBeenCalledTimes(2);
  });

  it("gives up after the configured attempts", async () => {
    const op = vi.fn().mockRejectedValue(new Error("fetch failed"));
    await expect(withRetry(op, { attempts: 3, sleep: noSleep })).rejects.toThrow(
      /fetch failed/
    );
    expect(op).toHaveBeenCalledTimes(3);
  });

  it("does not retry a non-network error", async () => {
    const op = vi.fn().mockRejectedValue(new Error("нельзя так"));
    await expect(withRetry(op, { sleep: noSleep })).rejects.toThrow(/нельзя так/);
    expect(op).toHaveBeenCalledTimes(1);
  });
});
