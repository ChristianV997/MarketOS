/**
 * Shared operator-shell drawer contract.
 * Layout-only: no provider, POST, order, payment, message, ad, or publishing authority.
 */

/** Matches Tailwind `md` (768px): below this, the rail is an overlay. */
export const DRAWER_MAX_WIDTH_PX = 767;
export const DRAWER_MEDIA_QUERY = `(max-width: ${DRAWER_MAX_WIDTH_PX}px)`;
export const SIDEBAR_NAV_ID = "operator-sidebar-nav";
export const OPERATOR_MAIN_ID = "operator-main";
export const NAV_TOGGLE_ID = "operator-nav-toggle";
export const NAV_SCRIM_ID = "operator-nav-scrim";
export const SKIP_TO_MAIN_ID = "operator-skip-to-main";

export function isDrawerMode(viewportWidth: number): boolean {
  return viewportWidth <= DRAWER_MAX_WIDTH_PX;
}

export function shouldCloseDrawerOnKey(
  key: string,
  state: { open: boolean; drawerMode: boolean },
): boolean {
  return state.drawerMode && state.open && key === "Escape";
}

export function navigationToggleLabel(open: boolean): string {
  return open ? "Close navigation" : "Open navigation";
}

export function sidebarIsInert(drawerMode: boolean, open: boolean): boolean {
  return drawerMode && !open;
}

export function shouldCloseDrawerOnRouteChange(drawerMode: boolean, open: boolean): boolean {
  return drawerMode && open;
}

/** Skip-to-main must not leave a mobile drawer covering the landmark. */
export function shouldCloseDrawerOnSkip(drawerMode: boolean, open: boolean): boolean {
  return shouldCloseDrawerOnRouteChange(drawerMode, open);
}
