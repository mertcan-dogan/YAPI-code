import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AiTrustBadge } from "./AiTrustBadge";

describe("AiTrustBadge", () => {
  it("renders the read-only copy and links to the principles page", () => {
    render(
      <MemoryRouter>
        <AiTrustBadge />
      </MemoryRouter>
    );
    const link = screen.getByRole("link");
    expect(link).toHaveTextContent(/Salt-okunur/i);
    expect(link).toHaveAttribute("href", "/ai-principles");
  });

  it("compact form still shows the read-only label and the full claim as title", () => {
    render(
      <MemoryRouter>
        <AiTrustBadge compact />
      </MemoryRouter>
    );
    const link = screen.getByRole("link");
    expect(link).toHaveTextContent(/Salt-okunur/i);
    expect(link).toHaveAttribute("title", expect.stringContaining("değişiklik yapmaz"));
  });
});
