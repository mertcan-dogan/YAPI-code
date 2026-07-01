import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Avatar, Badge, Menu, MenuItem, Pagination, SectionTitle, Sparkline, Stat, Switch, Tabs } from "./index";

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

describe("Menu (CR-029)", () => {
  it("opens on trigger click, shows items, closes on Escape", () => {
    const onClick = vi.fn();
    render(
      <Menu trigger="Aç" triggerLabel="menü">
        <MenuItem onClick={onClick}>Detaylar</MenuItem>
      </Menu>
    );
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "menü" }));
    expect(screen.getByRole("menu")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("menuitem", { name: "Detaylar" }));
    expect(onClick).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "menü" })); // reopen
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});

describe("Sparkline (CR-029)", () => {
  it("renders a polyline for >=2 points and nothing for <2", () => {
    const { container, rerender } = render(<Sparkline data={[1, 3, 2, 5]} />);
    expect(container.querySelector("polyline")).toBeInTheDocument();
    rerender(<Sparkline data={[1]} />);
    expect(container.querySelector("polyline")).not.toBeInTheDocument();
  });
});

describe("Pagination (CR-029)", () => {
  it("disables prev on first page and next on last, and pages otherwise", () => {
    const onPage = vi.fn();
    const { rerender } = render(<Pagination page={1} pageCount={3} onPage={onPage} />);
    expect(screen.getByLabelText("Önceki")).toBeDisabled();
    fireEvent.click(screen.getByLabelText("Sonraki"));
    expect(onPage).toHaveBeenCalledWith(2);
    rerender(<Pagination page={3} pageCount={3} onPage={onPage} />);
    expect(screen.getByLabelText("Sonraki")).toBeDisabled();
  });
});

describe("Switch (CR-029)", () => {
  it("reflects checked state and toggles", () => {
    const onChange = vi.fn();
    render(<Switch checked={false} onChange={onChange} label="otomasyon" />);
    const sw = screen.getByRole("switch", { name: "otomasyon" });
    expect(sw).toHaveAttribute("aria-checked", "false");
    fireEvent.click(sw);
    expect(onChange).toHaveBeenCalledWith(true);
  });
});

describe("Avatar (CR-029)", () => {
  it("renders Turkish-uppercased initials from a name", () => {
    render(<Avatar name="ilke yıldız" />);
    expect(screen.getByText("İY")).toBeInTheDocument();
  });
});
