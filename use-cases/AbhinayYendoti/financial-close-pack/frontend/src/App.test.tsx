import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { App } from "./App";

/**
 * The rewrite replaced all local mock state with API calls. These assertions pin the
 * rendered structure so the visual layer cannot drift while that happens: the CSS in
 * styles.css targets exactly these class names.
 */
describe("App shell", () => {
  const markup = renderToStaticMarkup(<App />);

  it("renders the sign-in screen when there is no session", () => {
    expect(markup).toContain('class="auth-screen"');
    expect(markup).toContain('class="auth-hero"');
    expect(markup).toContain("Close with evidence, review, and sign-off in one place.");
    expect(markup).toContain("Continue demo");
  });

  it("keeps the branded top navigation", () => {
    expect(markup).toContain('class="top-nav"');
    expect(markup).toContain('class="brand"');
    expect(markup).toContain('class="logo-mark"');
    expect(markup).toContain('class="logo-core"');
    expect(markup).toContain('class="logo-satellite"');
    expect(markup).toContain("CloseOrbit");

    // These are real destinations now, not aliases onto the workspace tab strip.
    for (const label of ["Workspace", "Closes", "Templates", "Activity", "Exports"]) {
      expect(markup).toContain(`>${label}</a>`);
    }
  });

  it("keeps the orbit artwork and its three portraits", () => {
    expect(markup).toContain('class="auth-orbit"');
    expect(markup).toContain('class="portrait one"');
    expect(markup).toContain('class="portrait two"');
    expect(markup).toContain('class="portrait three"');
  });

  it("points the nav links at destinations rather than workspace tabs", () => {
    expect(markup).toContain('href="#closes"');
    expect(markup).toContain('href="#exports"');
    // The operations ledger is engineering evidence; it is behind ?debug=1 now.
    expect(markup).not.toContain(">SuperDocs</a>");
  });
});
