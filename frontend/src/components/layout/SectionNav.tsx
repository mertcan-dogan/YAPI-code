import * as React from "react";
import { Link, useLocation } from "react-router-dom";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/cn";
import { useHoverIntent } from "@/hooks/useHoverIntent";
import { NavItemRow } from "./NavItemRow";

// CR-038 §A2 — the top-bar section navigation as an accessible `menubar`. The
// existing NAV_GROUPS are reshaped (one source of truth) into ordered sections:
// direct-link "hero" items (Yapı AI) and dropdown menus. Opens on hover (intent
// delay) + click + keyboard, with full ARIA + roving tabindex; collapses the
// tail into "Daha fazla" when the bar is too narrow.

export type NavEntry = {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  to: string;
  directorOnly?: boolean;
  comingSoon?: boolean;
};

export type SectionDef =
  | { kind: "link"; key: string; label: string; to: string; icon: React.ComponentType<{ className?: string }>; hero?: boolean }
  | { kind: "menu"; key: string; label: string; items: NavEntry[] };

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = React.useState(false);
  React.useEffect(() => {
    const mq = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!mq) return;
    setReduced(mq.matches);
    const on = () => setReduced(mq.matches);
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, []);
  return reduced;
}

interface SectionNavProps {
  sections: SectionDef[];
  isDirector: boolean;
  approvalCount: number;
  isSectionActive: (s: SectionDef) => boolean;
  isItemActive: (to: string) => boolean;
}

export function SectionNav({ sections, isDirector, approvalCount, isSectionActive, isItemActive }: SectionNavProps) {
  const { pathname } = useLocation();
  const reducedMotion = usePrefersReducedMotion();
  const hover = useHoverIntent();

  const [openKey, setOpenKey] = React.useState<string | null>(null);
  const [openFocus, setOpenFocus] = React.useState<"first" | "last" | null>(null);
  const [focusIndex, setFocusIndex] = React.useState(0);

  const navRef = React.useRef<HTMLDivElement>(null);
  const measureRef = React.useRef<HTMLDivElement>(null);
  const buttonRefs = React.useRef<(HTMLElement | null)[]>([]);

  // --- responsive overflow: how many top sections fit before "Daha fazla". ----
  const [visibleCount, setVisibleCount] = React.useState(sections.length);
  React.useLayoutEffect(() => {
    const compute = () => {
      const avail = navRef.current?.clientWidth ?? 0;
      // No layout (jsdom / not yet measured) → show everything.
      if (!avail) {
        setVisibleCount(sections.length);
        return;
      }
      const els = Array.from(measureRef.current?.children ?? []) as HTMLElement[];
      const MORE = 96; // reserve for the "Daha fazla" trigger
      const fit = (budget: number) => {
        let used = 0;
        let count = 0;
        for (const el of els) {
          used += el.offsetWidth + 4;
          if (used <= budget) count++;
          else break;
        }
        return count;
      };
      const all = fit(avail);
      if (all >= els.length) {
        setVisibleCount(sections.length);
        return;
      }
      setVisibleCount(Math.max(1, fit(avail - MORE)));
    };
    compute();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(compute);
    if (navRef.current) ro.observe(navRef.current);
    return () => ro.disconnect();
  }, [sections]);

  const visibleSections = sections.slice(0, visibleCount);
  const overflowSections = sections.slice(visibleCount);
  const hasOverflow = overflowSections.length > 0;
  const MORE_KEY = "__more__";

  // top-level focusable items, in visual order (sections + optional "more").
  const topKeys = [...visibleSections.map((s) => s.key), ...(hasOverflow ? [MORE_KEY] : [])];
  const topCount = topKeys.length;
  // Clamp the roving index for rendering: if overflow shrinks topCount below a
  // stale focusIndex, this keeps EXACTLY ONE top item tabbable (else the menubar
  // becomes keyboard-unreachable until clicked).
  const activeTopIndex = Math.min(focusIndex, topCount - 1);

  const close = React.useCallback(() => {
    setOpenKey(null);
    setOpenFocus(null);
  }, []);
  const open = React.useCallback((key: string, focus: "first" | "last" | null = null) => {
    setOpenKey(key);
    setOpenFocus(focus);
  }, []);

  // Close on outside click + route change + Escape.
  React.useEffect(() => close(), [pathname, close]);
  React.useEffect(() => {
    if (!openKey) return;
    const onDoc = (e: MouseEvent) => {
      if (navRef.current && !navRef.current.contains(e.target as Node)) close();
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [openKey, close]);

  const focusTop = (i: number) => {
    const idx = ((i % topCount) + topCount) % topCount;
    setFocusIndex(idx);
    buttonRefs.current[idx]?.focus();
  };

  // Cross-section arrow move from inside a panel: close, focus the adjacent top
  // item, and open it if it is a menu.
  const moveSection = (fromKey: string, dir: 1 | -1) => {
    const idx = topKeys.indexOf(fromKey);
    if (idx === -1) return;
    const targetIdx = ((idx + dir) % topCount + topCount) % topCount;
    const targetKey = topKeys[targetIdx];
    close();
    setFocusIndex(targetIdx);
    const targetIsMenu = targetKey === MORE_KEY || sections.find((s) => s.key === targetKey)?.kind === "menu";
    if (targetIsMenu) {
      open(targetKey, "first");
      // focus moves into the panel via the section's open-effect
      buttonRefs.current[targetIdx]?.focus();
    } else {
      buttonRefs.current[targetIdx]?.focus();
    }
  };

  const onNavKey = (e: React.KeyboardEvent) => {
    const active = document.activeElement;
    const topIdx = buttonRefs.current.findIndex((r) => r === active);
    if (topIdx === -1) return; // focus is inside a panel → handled there
    if (e.key === "ArrowRight") {
      e.preventDefault();
      focusTop(topIdx + 1);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      focusTop(topIdx - 1);
    } else if (e.key === "Home") {
      e.preventDefault();
      focusTop(0);
    } else if (e.key === "End") {
      e.preventDefault();
      focusTop(topCount - 1);
    }
  };

  const onHoverOpen = (key: string) => {
    hover.cancel();
    if (openKey) open(key);
    else hover.scheduleOpen(() => open(key));
  };
  const onHoverClose = () => hover.scheduleClose(() => close());

  const renderApprovalBadge = (to: string) =>
    to === "/approvals" && approvalCount > 0 ? (
      <span className="rounded-full bg-danger px-1.5 text-[10px] font-bold leading-[16px] text-white">{approvalCount}</span>
    ) : undefined;

  return (
    <div
      ref={navRef}
      role="menubar"
      aria-label="Bölümler"
      onKeyDown={onNavKey}
      className="relative hidden min-w-0 flex-1 items-center gap-0.5 lg:flex"
    >
      {/* Offscreen measurement row (mirrors the labels for width calc). */}
      <div ref={measureRef} aria-hidden className="pointer-events-none absolute -z-10 flex opacity-0">
        {sections.map((s) => (
          <span key={s.key} className="flex h-9 items-center gap-1 px-3 text-[13px] font-medium">
            {s.label}
            {s.kind === "menu" && <ChevronDown className="h-3.5 w-3.5" />}
          </span>
        ))}
      </div>

      {visibleSections.map((section, i) => {
        const active = isSectionActive(section);
        const reg = (el: HTMLElement | null) => (buttonRefs.current[i] = el);
        const tabIndex = i === activeTopIndex ? 0 : -1;
        if (section.kind === "link") {
          return (
            <Link
              key={section.key}
              ref={reg as any}
              to={section.to}
              role="menuitem"
              tabIndex={tabIndex}
              aria-current={active ? "page" : undefined}
              onFocus={() => setFocusIndex(i)}
              className={cn(
                "focus-ring relative flex h-9 items-center gap-1.5 rounded-control px-3 text-[13px] font-medium transition-colors",
                section.hero
                  ? active
                    ? "text-brand"
                    : "text-brand/90 hover:bg-blue-soft hover:text-brand"
                  : active
                  ? "text-brand"
                  : "text-text-secondary hover:bg-surface-hover hover:text-text-primary"
              )}
            >
              <section.icon className="h-4 w-4 shrink-0" />
              <span>{section.label}</span>
              {active && <span className="absolute inset-x-2 -bottom-[11px] h-0.5 rounded-full bg-brand" />}
            </Link>
          );
        }
        return (
          <MenuSection
            key={section.key}
            section={section}
            isActive={active}
            isDirector={isDirector}
            isItemActive={isItemActive}
            approvalBadge={renderApprovalBadge}
            reducedMotion={reducedMotion}
            tabIndex={tabIndex}
            open={openKey === section.key}
            focus={openKey === section.key ? openFocus : null}
            registerButton={reg}
            onButtonFocus={() => setFocusIndex(i)}
            onToggle={() => (openKey === section.key ? close() : open(section.key))}
            onOpen={(f) => open(section.key, f)}
            onClose={close}
            onHoverOpen={() => onHoverOpen(section.key)}
            onHoverClose={onHoverClose}
            onMoveSection={(dir) => moveSection(section.key, dir)}
          />
        );
      })}

      {hasOverflow && (
        <MoreMenu
          sections={overflowSections}
          isDirector={isDirector}
          isItemActive={isItemActive}
          approvalBadge={renderApprovalBadge}
          reducedMotion={reducedMotion}
          tabIndex={topKeys.indexOf(MORE_KEY) === activeTopIndex ? 0 : -1}
          open={openKey === MORE_KEY}
          focus={openKey === MORE_KEY ? openFocus : null}
          registerButton={(el) => (buttonRefs.current[topKeys.indexOf(MORE_KEY)] = el)}
          onButtonFocus={() => setFocusIndex(topKeys.indexOf(MORE_KEY))}
          onToggle={() => (openKey === MORE_KEY ? close() : open(MORE_KEY))}
          onOpen={(f) => open(MORE_KEY, f)}
          onClose={close}
          onHoverOpen={() => onHoverOpen(MORE_KEY)}
          onHoverClose={onHoverClose}
        />
      )}
    </div>
  );
}

// --- one dropdown section -------------------------------------------------- //
interface MenuSectionProps {
  section: Extract<SectionDef, { kind: "menu" }>;
  isActive: boolean;
  isDirector: boolean;
  isItemActive: (to: string) => boolean;
  approvalBadge: (to: string) => React.ReactNode;
  reducedMotion: boolean;
  tabIndex: number;
  open: boolean;
  focus: "first" | "last" | null;
  registerButton: (el: HTMLElement | null) => void;
  onButtonFocus: () => void;
  onToggle: () => void;
  onOpen: (focus: "first" | "last") => void;
  onClose: () => void;
  onHoverOpen: () => void;
  onHoverClose: () => void;
  onMoveSection: (dir: 1 | -1) => void;
}

function menuItemEls(panel: HTMLElement | null): HTMLElement[] {
  return Array.from(panel?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? []);
}

function MenuSection(p: MenuSectionProps) {
  const buttonRef = React.useRef<HTMLButtonElement>(null);
  const panelRef = React.useRef<HTMLDivElement>(null);
  const items = p.section.items.filter((n) => !n.directorOnly || p.isDirector);
  const panelId = `section-menu-${p.section.key}`;

  React.useEffect(() => {
    p.registerButton(buttonRef.current);
    return () => p.registerButton(null);
  });

  // Focus the first/last item when opened via keyboard (focus signal set).
  React.useEffect(() => {
    if (p.open && p.focus) {
      const els = menuItemEls(panelRef.current);
      if (els.length) (p.focus === "first" ? els[0] : els[els.length - 1]).focus();
    }
  }, [p.open, p.focus]);

  const onButtonKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      p.onOpen("first");
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      p.onOpen("last");
    } else if (e.key === "Escape") {
      p.onClose();
    }
  };

  const move = (dir: 1 | -1) => {
    const els = menuItemEls(panelRef.current);
    if (!els.length) return;
    const idx = els.findIndex((el) => el === document.activeElement);
    const next = idx === -1 ? (dir > 0 ? 0 : els.length - 1) : (idx + dir + els.length) % els.length;
    els[next].focus();
  };

  const onPanelKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      move(1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      move(-1);
    } else if (e.key === "Home") {
      e.preventDefault();
      menuItemEls(panelRef.current)[0]?.focus();
    } else if (e.key === "End") {
      e.preventDefault();
      const els = menuItemEls(panelRef.current);
      els[els.length - 1]?.focus();
    } else if (e.key === "Escape") {
      e.preventDefault();
      p.onClose();
      buttonRef.current?.focus();
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      p.onMoveSection(1);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      p.onMoveSection(-1);
    }
  };

  return (
    <div className="relative" onMouseEnter={p.onHoverOpen} onMouseLeave={p.onHoverClose}>
      <button
        ref={buttonRef}
        type="button"
        role="menuitem"
        aria-haspopup="menu"
        aria-expanded={p.open}
        aria-controls={p.open ? panelId : undefined}
        aria-current={p.isActive ? "page" : undefined}
        tabIndex={p.tabIndex}
        onFocus={p.onButtonFocus}
        onClick={p.onToggle}
        onKeyDown={onButtonKey}
        className={cn(
          "focus-ring relative flex h-9 items-center gap-1 rounded-control px-3 text-[13px] font-medium transition-colors",
          p.isActive ? "text-brand" : "text-text-secondary hover:bg-surface-hover hover:text-text-primary"
        )}
      >
        <span>{p.section.label}</span>
        <ChevronDown className={cn("h-3.5 w-3.5 text-text-muted transition-transform", p.open && "rotate-180")} />
        {p.isActive && <span className="absolute inset-x-2 -bottom-[11px] h-0.5 rounded-full bg-brand" />}
      </button>
      {p.open && (
        <div
          ref={panelRef}
          id={panelId}
          role="menu"
          aria-label={p.section.label}
          onKeyDown={onPanelKey}
          className={cn(
            "absolute left-0 z-50 mt-1.5 min-w-[232px] rounded-control border border-border bg-surface p-1 shadow-pop",
            !p.reducedMotion && "animate-fade-in"
          )}
        >
          {items.map((n) => (
            <NavItemRow
              key={n.to}
              inMenu
              icon={n.icon}
              label={n.label}
              to={n.to}
              comingSoon={n.comingSoon}
              active={!n.comingSoon && p.isItemActive(n.to)}
              onNavigate={p.onClose}
              right={p.approvalBadge(n.to)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// --- "Daha fazla" overflow menu (flattens the tail sections) --------------- //
interface MoreMenuProps {
  sections: SectionDef[];
  isDirector: boolean;
  isItemActive: (to: string) => boolean;
  approvalBadge: (to: string) => React.ReactNode;
  reducedMotion: boolean;
  tabIndex: number;
  open: boolean;
  focus: "first" | "last" | null;
  registerButton: (el: HTMLElement | null) => void;
  onButtonFocus: () => void;
  onToggle: () => void;
  onOpen: (focus: "first" | "last") => void;
  onClose: () => void;
  onHoverOpen: () => void;
  onHoverClose: () => void;
}

function MoreMenu(p: MoreMenuProps) {
  const buttonRef = React.useRef<HTMLButtonElement>(null);
  const panelRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    p.registerButton(buttonRef.current);
    return () => p.registerButton(null);
  });

  React.useEffect(() => {
    if (p.open && p.focus) {
      const els = menuItemEls(panelRef.current);
      if (els.length) (p.focus === "first" ? els[0] : els[els.length - 1]).focus();
    }
  }, [p.open, p.focus]);

  const move = (dir: 1 | -1) => {
    const els = menuItemEls(panelRef.current);
    if (!els.length) return;
    const idx = els.findIndex((el) => el === document.activeElement);
    const next = idx === -1 ? (dir > 0 ? 0 : els.length - 1) : (idx + dir + els.length) % els.length;
    els[next].focus();
  };

  const onButtonKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      p.onOpen("first");
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      p.onOpen("last");
    } else if (e.key === "Escape") {
      p.onClose();
    }
  };
  const onPanelKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      move(1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      move(-1);
    } else if (e.key === "Escape") {
      e.preventDefault();
      p.onClose();
      buttonRef.current?.focus();
    }
  };

  return (
    <div className="relative" onMouseEnter={p.onHoverOpen} onMouseLeave={p.onHoverClose}>
      <button
        ref={buttonRef}
        type="button"
        role="menuitem"
        aria-haspopup="menu"
        aria-expanded={p.open}
        tabIndex={p.tabIndex}
        onFocus={p.onButtonFocus}
        onClick={p.onToggle}
        onKeyDown={onButtonKey}
        className={cn(
          "focus-ring flex h-9 items-center gap-1 rounded-control px-3 text-[13px] font-medium text-text-secondary transition-colors hover:bg-surface-hover hover:text-text-primary"
        )}
      >
        <span>Daha fazla</span>
        <ChevronDown className={cn("h-3.5 w-3.5 text-text-muted transition-transform", p.open && "rotate-180")} />
      </button>
      {p.open && (
        <div
          ref={panelRef}
          role="menu"
          aria-label="Daha fazla"
          onKeyDown={onPanelKey}
          className={cn(
            "absolute right-0 z-50 mt-1.5 max-h-[70vh] min-w-[232px] overflow-y-auto rounded-control border border-border bg-surface p-1 shadow-pop",
            !p.reducedMotion && "animate-fade-in"
          )}
        >
          {p.sections.map((s) =>
            s.kind === "link" ? (
              <NavItemRow
                key={s.key}
                inMenu
                icon={s.icon}
                label={s.label}
                to={s.to}
                active={p.isItemActive(s.to)}
                onNavigate={p.onClose}
              />
            ) : (
              <div key={s.key} className="border-t border-border first:border-t-0">
                <div className="px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wide text-text-faint">
                  {s.label}
                </div>
                {s.items
                  .filter((n) => !n.directorOnly || p.isDirector)
                  .map((n) => (
                    <NavItemRow
                      key={n.to}
                      inMenu
                      icon={n.icon}
                      label={n.label}
                      to={n.to}
                      comingSoon={n.comingSoon}
                      active={!n.comingSoon && p.isItemActive(n.to)}
                      onNavigate={p.onClose}
                      right={p.approvalBadge(n.to)}
                    />
                  ))}
              </div>
            )
          )}
        </div>
      )}
    </div>
  );
}
