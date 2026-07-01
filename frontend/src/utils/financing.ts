// CR-015 discoverability: the financing ENABLE toggle lives in Ayarlar → Şirket,
// and the project dashboard card only appears once financing is enabled with a
// positive accrual. When financing is OFF, show a director a one-line hint
// pointing to Settings so it's clear HOW to turn it on (the card's absence alone
// is ambiguous). Non-directors can't change company settings, so they see nothing.
export interface FinancingState {
  enabled?: boolean;
  total_try?: string;
}

export function shouldShowFinancingHint(isDirector: boolean, financing?: FinancingState | null): boolean {
  // Only once the dashboard payload has loaded (financing present) and it's off.
  return !!isDirector && !!financing && !financing.enabled;
}
