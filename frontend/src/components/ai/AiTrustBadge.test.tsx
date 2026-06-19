import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AiTrustBadge } from "./AiTrustBadge";

describe("AiTrustBadge", () => {
  // CR-011-D §0.2.2 — once write-with-approval shipped, the claim flipped from
  // "salt-okunur" to "önerir, siz onaylarsınız" (never a stale read-only claim).
  it("renders the propose-with-approval copy and links to the principles page", () => {
    render(
      <MemoryRouter>
        <AiTrustBadge />
      </MemoryRouter>
    );
    const link = screen.getByRole("link");
    expect(link).toHaveTextContent(/Önerir, siz onaylarsınız/i);
    expect(link).not.toHaveTextContent(/Salt-okunur/i); // the stale claim is gone
    expect(link).toHaveAttribute("href", "/ai-principles");
  });

  it("compact form shows the short claim and the full claim as title", () => {
    render(
      <MemoryRouter>
        <AiTrustBadge compact />
      </MemoryRouter>
    );
    const link = screen.getByRole("link");
    expect(link).toHaveTextContent(/Önerir, siz onaylarsınız/i);
    expect(link).toHaveAttribute("title", expect.stringContaining("onaysız hiçbir şey yazmaz"));
  });
});
