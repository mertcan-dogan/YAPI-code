import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppErrorBoundary } from "./AppErrorBoundary";

function Boom(): never {
  throw new Error("kaboom");
}

describe("AppErrorBoundary", () => {
  afterEach(() => vi.restoreAllMocks());

  it("renders the Turkish fallback when a child throws", () => {
    // React logs the caught error to console.error; silence it for a clean run.
    vi.spyOn(console, "error").mockImplementation(() => {});

    render(
      <AppErrorBoundary>
        <Boom />
      </AppErrorBoundary>
    );

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText(/Bir şeyler ters gitti/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Sayfayı yenile/i })).toBeInTheDocument();
  });

  it("renders children normally when nothing throws", () => {
    render(
      <AppErrorBoundary>
        <span>içerik</span>
      </AppErrorBoundary>
    );

    expect(screen.getByText("içerik")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
