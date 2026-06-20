import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AiExplainPanel } from "./AiExplainPanel";

function expand() {
  fireEvent.click(screen.getByRole("button", { name: /AI nasıl çalıştı/i }));
}

describe("AiExplainPanel", () => {
  it("renders friendly tool labels + row counts from a real response", () => {
    const { container } = render(
      <AiExplainPanel
        toolsUsed={["get_vendor_spend", "create_chart"]}
        rowCounts={{ get_vendor_spend: 42 }}
        citationCount={3}
        generatedAt="2026-06-18T09:00:00Z"
      />
    );
    expand();
    expect(container.textContent).toContain("Tedarikçi harcamaları okundu");
    expect(container.textContent).toContain("Grafik oluşturuldu");
    expect(container.textContent).toContain("42 kayıt okundu");
  });

  it("shows the honest empty state when no tools were used", () => {
    const { container } = render(
      <AiExplainPanel toolsUsed={[]} rowCounts={{}} generatedAt="2026-06-18T09:00:00Z" />
    );
    expand();
    expect(container.textContent).toContain("Bu yanıt için araç kullanılmadı.");
    // no fabricated row-count line
    expect(container.textContent).not.toContain("kayıt okundu");
  });

  it("falls back to the raw name for an unmapped tool (never crashes)", () => {
    const { container } = render(<AiExplainPanel toolsUsed={["brand_new_tool"]} />);
    expand();
    expect(container.textContent).toContain("brand_new_tool");
  });

  it("collapses repeated identical tool calls into one line with a count", () => {
    const { container } = render(
      <AiExplainPanel toolsUsed={Array(6).fill("get_overdue_payments")} generatedAt="2026-06-18T09:00:00Z" />
    );
    expand();
    // One line, not six.
    const items = container.querySelectorAll("li");
    expect(items).toHaveLength(1);
    expect(container.textContent).toContain("Vadesi geçmiş ödemeler tarandı");
    expect(container.textContent).toContain("×6");
  });

  it("does not add a count for a single call", () => {
    const { container } = render(
      <AiExplainPanel toolsUsed={["get_vendor_spend"]} generatedAt="2026-06-18T09:00:00Z" />
    );
    expand();
    expect(container.textContent).not.toContain("×1");
  });
});
