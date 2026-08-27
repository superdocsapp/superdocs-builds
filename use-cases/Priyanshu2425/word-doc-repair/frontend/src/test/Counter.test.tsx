/**
 * The counter, tested the same way the rest of this page is: at the HTTP
 * boundary, over what actually lands on screen.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, beforeEach } from "vitest";

import App from "../App";
import {
  holdNextTurn,
  releaseNextTurn,
  resetCounter,
  serve,
  serveCapabilities,
  serveTurn,
} from "./server";

function file(name = "broken.docx", size = 4096) {
  const f = new File([new Uint8Array(size)], name, {
    type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  });
  Object.defineProperty(f, "size", { value: size });
  return f;
}

/** Upload a file and wait for the report, the same round trip every scenario
 *  here starts from. */
async function repaired(styling = true) {
  serve("truncated");
  serveCapabilities(
    styling,
    styling ? "" : "Styling is switched off on this copy of the page.",
  );
  const user = userEvent.setup();
  render(<App />);
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  await user.upload(input, file());
  await screen.findByText(/what came through/i);
  return user;
}

async function openTheDoor(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: /set it your way/i }));
  return screen.findByPlaceholderText(/what should be different/i);
}

/** The one-sentence reply, scoped so a phrase that also appears on the ledger
 *  or in the full transcript is not ambiguous here. */
function said() {
  return within(document.querySelector(".said") as HTMLElement);
}

beforeEach(() => {
  resetCounter();
  serveTurn({
    stages: ["Sending your change to SuperDocs…"],
    applied: true,
    note: "Table rules are hairlines now.",
  });
});

describe("the door", () => {
  it("renders when this copy of the page can style", async () => {
    await repaired(true);
    expect(screen.getByRole("button", { name: /set it your way/i })).toBeInTheDocument();
  });

  it("is absent when capabilities say styling is not available", async () => {
    await repaired(false);
    expect(screen.queryByRole("button", { name: /set it your way/i })).toBeNull();
    expect(screen.getByText(/switched off on this copy/i)).toBeInTheDocument();
  });
});

describe("a turn", () => {
  it("streams its stages, applies, and repoints the download", async () => {
    const user = await repaired(true);
    const field = await openTheDoor(user);

    await user.type(field, "Hairline table rules");
    await user.click(screen.getByRole("button", { name: /^send$/i }));

    await said().findByText(/table rules are hairlines now/i);
    const link = screen.getByRole("link", { name: /download the styled file/i });
    expect(link).toHaveAttribute("href", expect.stringContaining("truncated-token-v1"));
  });

  it("disables the field and the send button while a turn is in flight", async () => {
    const user = await repaired(true);
    const field = await openTheDoor(user);
    await user.type(field, "Hairline table rules");

    holdNextTurn();
    const send = screen.getByRole("button", { name: /^send$/i });
    await user.click(send);

    expect(field).toBeDisabled();
    expect(send).toBeDisabled();

    releaseNextTurn();
    await said().findByText(/table rules are hairlines now/i);
    expect(field).not.toBeDisabled();
  });
});

describe("a turn that did not land", () => {
  it("shows the server's sentence once, and says nothing about what it cost", async () => {
    const user = await repaired(true);
    const field = await openTheDoor(user);

    const note =
      "No more changes can be made here this month. Your document is "
      + "unchanged and still yours to download.";
    serveTurn({ applied: false, note });
    await user.type(field, "Make the headings smaller");
    await user.click(screen.getByRole("button", { name: /^send$/i }));

    await said().findByText(/no more changes can be made here/i);
    // The note is the server's, shown verbatim. The page used to append its
    // own cost sentence on top, which printed it twice on screen.
    const shown = said().getByText(/no more changes can be made here/i).textContent ?? "";
    expect(shown.match(/no more changes can be made here/gi) ?? []).toHaveLength(1);
    // Nothing on this screen tells the person what a change costs us.
    for (const word of [/allowance/i, /operation/i, /counted/i, /spent/i, /billed/i]) {
      expect(said().queryByText(word)).toBeNull();
    }
  });
});

describe("what is left", () => {
  it("shows how many changes this document has left, and nothing about cost", async () => {
    resetCounter({ turnsLeft: 7 });
    const user = await repaired(true);
    await openTheDoor(user);

    // The count that is the person's own stays. The one that describes our
    // metering does not: they arrived with a broken file, not an account.
    expect(screen.getByText(/7 changes left on this document/i)).toBeInTheDocument();
    for (const word of [/allowance/i, /operations? left/i, /unknown, not zero/i]) {
      expect(screen.queryByText(word)).toBeNull();
    }
  });
});

describe("before and after", () => {
  it("the toggle swaps the sheet", async () => {
    serveTurn({
      applied: true,
      note: "Headings are a size smaller now.",
      previewHtml: "<p>Headings are a size smaller now, in the document itself.</p>",
    });
    const user = await repaired(true);
    const field = await openTheDoor(user);
    await user.type(field, "Smaller headings");
    await user.click(screen.getByRole("button", { name: /^send$/i }));
    await said().findByText(/headings are a size smaller now/i);

    // "With your changes" is the default tab, and shows the new content.
    expect(
      screen.getByText(/headings are a size smaller now, in the document itself/i),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /as it came back/i }));
    expect(
      screen.queryByText(/headings are a size smaller now, in the document itself/i),
    ).toBeNull();
    expect(screen.getByText("Quarterly Report")).toBeInTheDocument();
  });
});

describe("both files", () => {
  it("keeps the unstyled copy reachable after a turn", async () => {
    const user = await repaired(true);
    const field = await openTheDoor(user);
    expect(screen.getByRole("link", { name: /the unstyled copy/i })).toBeInTheDocument();

    await user.type(field, "Hairline table rules");
    await user.click(screen.getByRole("button", { name: /^send$/i }));
    await said().findByText(/table rules are hairlines now/i);

    expect(screen.getByRole("link", { name: /the unstyled copy/i })).toBeInTheDocument();
  });
});

describe("put it back", () => {
  it("returns the sheet to as it came back", async () => {
    serveTurn({
      applied: true,
      note: "Headings are a size smaller now.",
      previewHtml: "<p>Headings are a size smaller now, in the document itself.</p>",
    });
    const user = await repaired(true);
    const field = await openTheDoor(user);
    await user.type(field, "Smaller headings");
    await user.click(screen.getByRole("button", { name: /^send$/i }));
    await said().findByText(/headings are a size smaller now/i);
    expect(
      screen.getByText(/headings are a size smaller now, in the document itself/i),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: /put it back/i }));

    await waitFor(() =>
      expect(
        screen.queryByText(/headings are a size smaller now, in the document itself/i),
      ).toBeNull(),
    );
    // Back to the original rebuild -- the "as it came back" content.
    expect(screen.getByText("Quarterly Report")).toBeInTheDocument();
  });
});

describe("a preview that could not be rendered", () => {
  it("still applies the turn and repoints the download, leaving the sheet as it was", async () => {
    serveTurn({
      applied: true,
      note: "Margins are narrower now.",
      previewHtml: "",
    });
    const user = await repaired(true);
    const field = await openTheDoor(user);
    await user.type(field, "Narrower margins");
    await user.click(screen.getByRole("button", { name: /^send$/i }));
    await said().findByText(/margins are narrower now/i);

    const link = screen.getByRole("link", { name: /download the styled file/i });
    expect(link).toHaveAttribute("href", expect.stringContaining("truncated-token-v1"));
    // No blank sheet, no error -- the original rebuild is still what shows.
    expect(screen.getByText("Quarterly Report")).toBeInTheDocument();
  });
});
