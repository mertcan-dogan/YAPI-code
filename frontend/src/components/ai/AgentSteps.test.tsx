import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AgentSteps, type AgentStep } from "./AgentSteps";

// CR-011 rich steps — the collapsed step rows show REAL detail (reasoning,
// narration, formatted params, result summary + row count) and the group footer
// shows a subtle per-chat token counter. Nothing is fabricated; absent fields
// are simply not rendered.

const STEP: AgentStep = {
  label: "Tedarikçi harcamaları inceleniyor…",
  tool: "get_vendor_spend",
  input: { vendor_name: "Akçansa", date_from: "2026-01-01" },
  note: "Akçansa harcamalarını çekiyorum.",
  thinking: "Önce tedarikçiyi sorgulamalıyım.",
};

describe("AgentSteps", () => {
  it("renders nothing when there are no steps", () => {
    const { container } = render(<AgentSteps steps={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("shows the group summary + a per-chat token counter, expandable to real detail", () => {
    render(
      <AgentSteps
        steps={[STEP]}
        rowCounts={{ get_vendor_spend: 3 }}
        toolSummaries={{ get_vendor_spend: { total_try: "4500", count: 3, by_month: { "2026-01": 4500 } } }}
        usage={{ input_tokens: 3000, output_tokens: 1100 }}
      />
    );

    // Collapsed: a single completed step → "1 adım tamamlandı" + token counter.
    expect(screen.getByText("1 adım tamamlandı")).toBeInTheDocument();
    expect(screen.getByText("≈ 4,1B token")).toBeInTheDocument();

    // Expand the group, then the step row.
    fireEvent.click(screen.getByText("1 adım tamamlandı"));
    fireEvent.click(screen.getByText("Tedarikçi harcamaları okundu"));

    // Reasoning (thinking) + narration (note) are surfaced.
    expect(screen.getByText("Model değerlendirmesi")).toBeInTheDocument();
    expect(screen.getByText("Önce tedarikçiyi sorgulamalıyım.")).toBeInTheDocument();
    expect(screen.getByText("Akçansa harcamalarını çekiyorum.")).toBeInTheDocument();

    // Parametreler: formatted args, ISO date rendered tr-TR, internal keys hidden.
    expect(screen.getByText("Parametreler")).toBeInTheDocument();
    expect(screen.getByText("Tedarikçi:")).toBeInTheDocument();
    expect(screen.getByText("Akçansa")).toBeInTheDocument();
    expect(screen.getByText("01.01.2026")).toBeInTheDocument();

    // Sonuç: aggregate summary (TRY formatted) + nested by_month skipped; row count.
    expect(screen.getByText("Sonuç")).toBeInTheDocument();
    expect(screen.getByText("Toplam:")).toBeInTheDocument();
    expect(screen.getByText("4.500,00 ₺")).toBeInTheDocument();
    expect(screen.getByText("3 kayıt okundu")).toBeInTheDocument();
  });

  it("omits the token counter when usage is absent and never fabricates detail", () => {
    render(<AgentSteps steps={[{ label: "Projeler taranıyor…", tool: "list_projects" }]} />);
    expect(screen.queryByText(/token/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("1 adım tamamlandı"));
    // No reasoning/narration/params/summary when the step carries none of them.
    expect(screen.queryByText("Model değerlendirmesi")).not.toBeInTheDocument();
    expect(screen.queryByText("Parametreler")).not.toBeInTheDocument();
    expect(screen.queryByText("Sonuç")).not.toBeInTheDocument();
  });

  it("auto-expands while running (no group toggle) and spins the last step", () => {
    render(<AgentSteps steps={[STEP]} running />);
    // Running header is present and steps are already visible (no toggle click).
    expect(screen.getByText("İşlem adımları")).toBeInTheDocument();
    expect(screen.getByText("Tedarikçi harcamaları okundu")).toBeInTheDocument();
    expect(screen.queryByText(/adım tamamlandı/)).not.toBeInTheDocument();
  });
});
