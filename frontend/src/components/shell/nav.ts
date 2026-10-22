import { agentRoute, APP, ROUTES } from "@/lib/routes";

import type { IconName } from "../Icon";

type Route = (typeof ROUTES)[keyof typeof ROUTES];

export interface NavItem {
  /** Route this item points at, under the product shell. */
  href: Route;
  label: string;
  icon: IconName;
  /** Title shown in the topbar when this item is current. */
  title: string;
  /** Whether this item shows a trailing count in the rail. */
  count?: "agents" | "conversations";
  /**
   * Workspace-level items keep their bare route; every other item is scoped to
   * one agent and carries its `?agentId=` so the rail cannot silently switch
   * which agent you are looking at.
   */
  scope?: "workspace";
  /**
   * Kept as a destination but taken out of the rail: the screen still answers on
   * its own route, so a saved link keeps working and the topbar still knows what
   * to call it, but nothing points at it from the navigation.
   */
  hidden?: boolean;
  /**
   * Changes the agent itself. Left out of the rail for the shared example agent,
   * which is one row for every user — only its real owner may edit or share it.
   */
  editsAgent?: boolean;
}

/**
 * Every destination the product shell knows, in the design artifact's order.
 *
 * Batch Query Reports is `hidden`: the screen still answers on its own route
 * and the topbar still titles it, but the rail no longer offers it.
 *
 * Usage lives *inside* Home (reached from the "Usage & Limits" card) rather than
 * in the rail, and Analytics is agent-scoped — both keep their own "Back to
 * Home" affordance, as in the prototype.
 */
export const NAV_ITEMS: NavItem[] = [
  {
    href: ROUTES.home,
    label: "Home",
    icon: "home",
    title: "Home",
    count: "agents",
    scope: "workspace",
  },
  {
    href: ROUTES.conversations,
    label: "Conversations",
    icon: "chat",
    title: "Conversations",
    count: "conversations",
  },
  {
    href: ROUTES.analytics,
    label: "Analytics",
    icon: "chart",
    title: "Agent Analytics",
  },
  {
    href: ROUTES.share,
    label: "Share",
    icon: "share",
    title: "Share",
    editsAgent: true,
  },
  {
    href: ROUTES.reports,
    label: "Batch Query Reports",
    icon: "clipboard",
    title: "Batch Query Reports",
    hidden: true,
  },
  {
    href: ROUTES.settings,
    label: "Settings",
    icon: "cog",
    title: "Settings",
    editsAgent: true,
  },
];

/** The items the rail actually draws — every destination that is not hidden. */
export const RAIL_ITEMS: NavItem[] = NAV_ITEMS.filter((item) => !item.hidden);

/** The rail for one agent: the example agent gets no editing destinations. */
export function railItemsFor(agent: { demo: boolean } | undefined): NavItem[] {
  return agent?.demo
    ? RAIL_ITEMS.filter((item) => !item.editsAgent)
    : RAIL_ITEMS;
}

/**
 * Longest-prefix match, so `/app/settings/…` still highlights Settings.
 *
 * Returns `null` for routes that are not rail destinations — Usage, for one,
 * which is reached from the Home card and highlights nothing, as in the artifact.
 */
/**
 * Where a rail item points for the agent currently open. Workspace items — Home —
 * deliberately drop the agent, since leaving the agent is what they are for.
 */
export function navHref(item: NavItem, agentId?: string): string {
  return item.scope === "workspace" || !agentId
    ? item.href
    : agentRoute(item.href, agentId);
}

export function currentNavItem(pathname: string): NavItem | null {
  const normalized = pathname.replace(/\/+$/, "") || APP;
  return (
    NAV_ITEMS.filter(
      (item) =>
        normalized === item.href || normalized.startsWith(`${item.href}/`),
    ).sort((a, b) => b.href.length - a.href.length)[0] ?? null
  );
}
