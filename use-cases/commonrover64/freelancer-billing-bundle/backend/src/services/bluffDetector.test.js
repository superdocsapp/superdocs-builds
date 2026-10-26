import { describe, it, expect } from "vitest";
import { isBluffedChange } from "./bluffDetector.js";

describe("isBluffedChange", () => {
    it("flags a generic placeholder marker introduced by the edit", () => {
        const change = {
            old_html: "<p>Client: TBD</p>",
            new_html: "<p>Client: <mark>Please fill: Client Name</mark></p>",
        };
        expect(isBluffedChange(change)).toBe(true);
    });

    it("does not flag a correctly filled value", () => {
        const change = {
            old_html: "<p>Client: TBD</p>",
            new_html: "<p>Client: Acme Co</p>",
        };
        expect(isBluffedChange(change)).toBe(false);
    });

    it("does not flag leftover TBD text that already existed before this edit", () => {
        // Regression test for a real bug found during development: a partial
        // table fill (row 1 correct, rows 2-4 still TBD) was false-flagged
        // as a bluff because TBD existed anywhere in new_html, even though
        // it was already present in old_html and untouched by this edit.
        const change = {
            old_html:
                "<table><tr><td>TBD</td></tr><tr><td>TBD</td></tr></table>",
            new_html:
                "<table><tr><td>2026-01-05</td></tr><tr><td>TBD</td></tr></table>",
        };
        expect(isBluffedChange(change)).toBe(false);
    });
});
