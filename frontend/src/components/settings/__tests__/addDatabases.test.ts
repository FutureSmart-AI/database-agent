import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentDatabase } from "@/data/types";

import { addDatabases, nameList } from "../addDatabases";

const addDatabase = vi.fn();
const generateDescription = vi.fn();

vi.mock("@/data/databases", () => ({
  addDatabase: (...args: unknown[]) => addDatabase(...args),
  generateDescription: (...args: unknown[]) => generateDescription(...args),
}));

/** A row as the service answers it, with only the fields this module reads. */
const row = (name: string, description: string | null): AgentDatabase =>
  ({
    db_id: `db_${name}`,
    db_name: name,
    description,
  }) as AgentDatabase;

const connection = (name: string, description?: string) => ({
  db_name: name,
  db_engine: "postgresql",
  db_host: "db.acme.com",
  db_port: 5432,
  db_user: "reader",
  db_password: "secret",
  ...(description ? { description } : {}),
});

beforeEach(() => {
  addDatabase.mockReset();
  generateDescription.mockReset();
  generateDescription.mockResolvedValue({});
});

describe("addDatabases", () => {
  it("adds every connection and reports progress per row", async () => {
    addDatabase.mockImplementation(
      (_service: string, credentials: { db_name: string }) =>
        Promise.resolve(row(credentials.db_name, "described")),
    );
    const progress: Array<[number, number]> = [];

    const result = await addDatabases(
      "NL2SQL_1",
      [connection("orders", "orders"), connection("warehouse", "stock")],
      (done, total) => progress.push([done, total]),
    );

    expect(addDatabase).toHaveBeenCalledTimes(2);
    expect(result.added.map((db) => db.db_name)).toEqual([
      "orders",
      "warehouse",
    ]);
    expect(result.failed).toEqual([]);
    expect(progress).toEqual([
      [1, 2],
      [2, 2],
    ]);
  });

  it("keeps the good rows when the service refuses one", async () => {
    addDatabase.mockImplementation(
      (_service: string, credentials: { db_name: string }) =>
        credentials.db_name === "bad"
          ? Promise.reject(new Error("password authentication failed"))
          : Promise.resolve(row(credentials.db_name, "described")),
    );

    const result = await addDatabases("NL2SQL_1", [
      connection("good", "fine"),
      connection("bad", "fine"),
    ]);

    expect(result.added.map((db) => db.db_name)).toEqual(["good"]);
    expect(result.failed).toEqual([
      { db_name: "bad", message: "password authentication failed" },
    ]);
  });

  it("starts a description only for the rows that came back without one", async () => {
    addDatabase.mockImplementation(
      (_service: string, credentials: { db_name: string }) =>
        Promise.resolve(
          row(
            credentials.db_name,
            credentials.db_name === "described" ? "already there" : null,
          ),
        ),
    );

    const result = await addDatabases("NL2SQL_1", [
      connection("described", "already there"),
      connection("blank"),
    ]);

    expect(result.describing).toEqual(["blank"]);
    expect(generateDescription).toHaveBeenCalledTimes(1);
    expect(generateDescription).toHaveBeenCalledWith("NL2SQL_1", "db_blank");
  });

  it("does not reject when a background description fails", async () => {
    addDatabase.mockResolvedValue(row("blank", null));
    generateDescription.mockRejectedValue(new Error("generator busy"));

    const result = await addDatabases("NL2SQL_1", [connection("blank")]);

    expect(result.added).toHaveLength(1);
    expect(result.failed).toEqual([]);
  });
});

describe("nameList", () => {
  it("lists up to three names and summarises the rest", () => {
    expect(nameList(["a", "b"])).toBe("a, b");
    expect(nameList(["a", "b", "c"])).toBe("a, b, c");
    expect(nameList(["a", "b", "c", "d"])).toBe("a, b and 2 more");
  });
});
