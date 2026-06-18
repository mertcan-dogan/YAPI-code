import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Badge, SectionTitle, Stat, Tabs } from "./index";

describe("Badge", () => {
  it("renders children and applies the variant class", () => {
    const { rerender } = render(<Badge variant="success">Ödendi</Badge>);
    const el = screen.getByText("Ödendi");
    expect(el).toHaveClass("text-success");
    rerender(<Badge variant="danger">Gecikmiş</Badge>);
    expect(screen.getByText("Gecikmiş")).toHaveClass("text-danger");
  });

  it("allows a style override (used by StatusBadge)", () => {
    render(<Badge style={{ color: "rgb(1, 2, 3)" }}>X</Badge>);
    expect(screen.getByText("X")).toHaveStyle({ color: "rgb(1, 2, 3)" });
  });
});

describe("Stat", () => {
  it("renders a label, value, and a colored delta", () => {
    render(<Stat label="Marj" value="12,5%" delta={{ text: "+1,2 pp", positive: true }} />);
    expect(screen.getByText("Marj")).toBeInTheDocument();
    expect(screen.getByText("12,5%")).toHaveClass("tabular");
    expect(screen.getByText("+1,2 pp")).toHaveClass("text-success");
  });

  it("shows a negative delta in danger", () => {
    render(<Stat label="Nakit" value="-5" delta={{ text: "-3%", positive: false }} />);
    expect(screen.getByText("-3%")).toHaveClass("text-danger");
  });
});

describe("Tabs", () => {
  it("marks the active tab and switches on click", () => {
    const onChange = vi.fn();
    render(
      <Tabs
        value="a"
        onChange={onChange}
        tabs={[
          { id: "a", label: "Bir" },
          { id: "b", label: "İki" },
        ]}
      />
    );
    expect(screen.getByRole("tab", { name: "Bir" })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("tab", { name: "İki" }));
    expect(onChange).toHaveBeenCalledWith("b");
  });

  it("is keyboard-navigable with arrow keys", () => {
    const onChange = vi.fn();
    render(
      <Tabs
        value="a"
        onChange={onChange}
        tabs={[
          { id: "a", label: "Bir" },
          { id: "b", label: "İki" },
        ]}
      />
    );
    fireEvent.keyDown(screen.getByRole("tablist"), { key: "ArrowRight" });
    expect(onChange).toHaveBeenCalledWith("b");
  });
});

describe("SectionTitle", () => {
  it("renders title + subtitle + right slot", () => {
    render(<SectionTitle title="Başlık" subtitle="Alt" right={<span>sağ</span>} />);
    expect(screen.getByRole("heading", { name: "Başlık" })).toBeInTheDocument();
    expect(screen.getByText("Alt")).toBeInTheDocument();
    expect(screen.getByText("sağ")).toBeInTheDocument();
  });
});
