import { describe, it, expect } from "vitest";
import { readPublicEnv, getBrowserSupabase } from "../lib/supabaseBrowser";

describe("readPublicEnv", () => {
  it("throws when env vars are missing", () => {
    expect(() => readPublicEnv()).toThrow(/Missing Supabase/);
  });
});

describe("getBrowserSupabase", () => {
  it("does not throw at import time when env vars are missing", () => {
    expect(typeof getBrowserSupabase).toBe("function");
  });
});
