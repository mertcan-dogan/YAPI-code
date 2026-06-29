// CR-038 §A2 — the top-bar section navigation (menubar): founder order, dropdowns
// that open on click + keyboard, directorOnly filtering, comingSoon toasts, the
// approval badge, and aria-current on the active section.
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

const { toastInfo } = vi.hoisted(() => ({ toastInfo: vi.fn() }));
vi.mock("@/store/toast", () => ({ toast: { info: toastInfo, success: vi.fn(), error: vi.fn(), warning: vi.fn() } }));

import { SectionNav, type SectionDef } from "./SectionNav";

const Icon = () => null;

const SECTIONS: SectionDef[] = [
  {
    kind: "menu",
    key: "genel",
    label: "Genel",
    items: [
      { icon: Icon, label: "Ana Sayfa", to: "/dashboard" },
      { icon: Icon, label: "Çalışma Alanım", to: "/workspace" },
    ],
  },
  { kind: "link", key: "yapi-ai", label: "Yapı AI", to: "/ai-assistant", icon: Icon, hero: true },
  {
    kind: "menu",
    key: "studio",
    label: "Stüdyo",
    items: [
      { icon: Icon, label: "Rapor Stüdyosu", to: "/studio/reports" },
      { icon: Icon, label: "Segmentler", to: "#segments", comingSoon: true },
    ],
  },
  {
    kind: "menu",
    key: "aksiyon",
    label: "Aksiyon",
    items: [
      { icon: Icon, label: "Onay Bekleyenler", to: "/approvals", directorOnly: true },
      { icon: Icon, label: "Hatırlatıcılar", to: "/reminders" },
    ],
  },
];

function renderNav({ isDirector = true, active = "genel", approvalCount = 3 } = {}) {
  return render(
    <MemoryRouter>
      <SectionNav
        sections={SECTIONS}
        isDirector={isDirector}
        approvalCount={approvalCount}
        isSectionActive={(s) => s.key === active}
        isItemActive={() => false}
      />
    </MemoryRouter>
  );
}

// Top-level triggers are role="menuitem"; while every menu is closed they are the
// only menuitems on screen (the offscreen measurement row has no role).
const topLabels = () => screen.getAllByRole("menuitem").map((el) => (el.textContent ?? "").trim());

afterEach(() => vi.clearAllMocks());

describe("SectionNav (CR-038)", () => {
  it("renders the founder-ordered sections", () => {
    renderNav();
    expect(topLabels()).toEqual(["Genel", "Yapı AI", "Stüdyo", "Aksiyon"]);
  });

  it("opens a dropdown on click and lists its items", () => {
    renderNav();
    fireEvent.click(screen.getByRole("menuitem", { name: /Stüdyo/ }));
    expect(screen.getByText("Rapor Stüdyosu")).toBeInTheDocument();
    expect(screen.getByText("Segmentler")).toBeInTheDocument();
  });

  it("opens via keyboard (ArrowDown) and closes on Escape", () => {
    renderNav();
    const studio = screen.getByRole("menuitem", { name: /Stüdyo/ });
    fireEvent.keyDown(studio, { key: "ArrowDown" });
    expect(screen.getByText("Rapor Stüdyosu")).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
    expect(screen.queryByText("Rapor Stüdyosu")).not.toBeInTheDocument();
  });

  it("hides directorOnly items for non-directors", () => {
    renderNav({ isDirector: false });
    fireEvent.click(screen.getByRole("menuitem", { name: /Aksiyon/ }));
    expect(screen.queryByText("Onay Bekleyenler")).not.toBeInTheDocument();
    expect(screen.getByText("Hatırlatıcılar")).toBeInTheDocument();
  });

  it("shows the approval-count badge for directors", () => {
    renderNav({ isDirector: true, approvalCount: 3 });
    fireEvent.click(screen.getByRole("menuitem", { name: /Aksiyon/ }));
    const menu = screen.getByRole("menu");
    expect(within(menu).getByText("Onay Bekleyenler")).toBeInTheDocument();
    expect(within(menu).getByText("3")).toBeInTheDocument();
  });

  it("toasts on a comingSoon item and marks it 'yakında'", () => {
    renderNav();
    fireEvent.click(screen.getByRole("menuitem", { name: /Stüdyo/ }));
    expect(screen.getByText("yakında")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Segmentler"));
    expect(toastInfo).toHaveBeenCalled();
  });

  it("marks the active section with aria-current=page", () => {
    renderNav({ active: "studio" });
    expect(screen.getByRole("menuitem", { name: /Stüdyo/ })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("menuitem", { name: /Genel/ })).not.toHaveAttribute("aria-current");
  });
});
