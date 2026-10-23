import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { HomePage } from "@/pages/HomePage";

describe("HomePage", () => {
  it("renders brand and primary CTA", () => {
    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );
    expect(screen.getByText(/Interview Preparation Brief/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Start a brief/i })).toHaveAttribute(
      "href",
      "/upload",
    );
  });
});
