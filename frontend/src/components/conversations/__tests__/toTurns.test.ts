import { describe, expect, it } from "vitest";

import { toTurns } from "../toTurns";

describe("toTurns", () => {
  it("pairs each question with the answer that follows it", () => {
    const turns = toTurns([
      { role: "user", message: "how many customers?", chat_id: "c1" },
      { role: "assistant", response: "Ten.", chat_id: "c1" },
      { role: "user", message: "and orders?", chat_id: "c2" },
      { role: "assistant", response: "Twelve.", chat_id: "c2" },
    ]);
    expect(turns).toHaveLength(2);
    expect(turns[0].question).toBe("how many customers?");
    expect(turns[0].answer?.response).toBe("Ten.");
    expect(turns[1].question).toBe("and orders?");
  });

  it("keeps a question that has no answer yet", () => {
    const turns = toTurns([{ role: "user", message: "pending" }]);
    expect(turns).toEqual([
      {
        key: "turn-0",
        question: "pending",
        questionViaVoice: false,
        answer: null,
      },
    ]);
  });

  it("keeps an assistant message with no question before it", () => {
    const turns = toTurns([{ role: "assistant", response: "orphan" }]);
    expect(turns).toHaveLength(1);
    expect(turns[0].question).toBe("");
    expect(turns[0].answer?.response).toBe("orphan");
  });

  it("carries the dictated flag through to the turn", () => {
    const turns = toTurns([
      { role: "user", message: "spoken", via_voice: true },
      { role: "assistant", response: "ok" },
    ]);
    expect(turns[0].questionViaVoice).toBe(true);
  });

  it("reads either response or message for the text", () => {
    const turns = toTurns([
      { role: "user", response: "from response" },
      { role: "assistant", message: "from message" },
    ]);
    expect(turns[0].question).toBe("from response");
    expect(turns[0].answer?.message).toBe("from message");
  });

  it("does not consume two answers for one question", () => {
    const turns = toTurns([
      { role: "user", message: "q" },
      { role: "assistant", response: "a1" },
      { role: "assistant", response: "a2" },
    ]);
    expect(turns).toHaveLength(2);
    expect(turns[1].question).toBe("");
  });
});
