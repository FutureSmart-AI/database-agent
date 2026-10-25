"use client";

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import Icon from "@/components/Icon";
import { includedTableCount } from "@/data/agents";
import AuthBridge from "@/data/AuthBridge";
import { useAgent, useAgents } from "@/data/useAgents";
import { PRODUCT_NAME } from "@/lib/constants";
import { NL2SQL_FONT_CLASS } from "@/lib/fonts";
import { ROUTES } from "@/lib/routes";
import ProfileDropdown from "@/platform/components/rag/dashboard/profile-modal";
import { Button } from "@/platform/components/ui";
import Tooltip from "@/platform/components/ui/Tooltip";
import { useResizablePanel } from "@/platform/hooks/useResizablePanel";
import { useSidebarCollapsed } from "@/platform/hooks/useSidebarCollapsed";
import { cn } from "@/platform/utils";

import {
  COLLAPSED_SIDEBAR_WIDTH,
  SIDEBAR_WIDTH,
  TOPBAR_HEIGHT,
} from "./constants";
import { currentNavItem, navHref, railItemsFor } from "./nav";

interface AppShellProps {
  children: ReactNode;
  /**
   * The agent this view is scoped to, from `?agentId=`. Home and Usage are
   * workspace-level and pass nothing: without an agent the shell shows neither
   * the agent chip nor the agent-scoped rail, since there is nothing to scope
   * them to.
   */
  agentId?: string;
  /** Overrides the topbar title (Analytics names the agent, for example). */
  title?: string;
  /** Secondary text next to the title. */
  crumb?: string;
  /** Views that own their own scrolling (Conversations) drop the view padding. */
  flush?: boolean;
}

/**
 * The product chrome.
 *
 * Deliberately the agent UI's chrome, down to the class strings: the topbar,
 * the collapsible resizable rail and the profile menu are the same ones
 * `src/components/layout.tsx` renders, so moving between the two products does
 * not feel like moving between two applications.
 */
function Shell({ children, agentId, title, crumb, flush }: AppShellProps) {
  const pathname = usePathname() ?? ROUTES.home;
  const current = currentNavItem(pathname);
  const { sidebarCollapsed, toggleSidebarCollapsed } = useSidebarCollapsed();
  // Same resizable rail as the agent UI, sharing its stored width so the two
  // products open at whatever width the person last chose.
  const {
    width: sidebarDragWidth,
    resetWidth: resetSidebarWidth,
    isResizing: isSidebarResizing,
    startResize: startSidebarResize,
    setWidth: setSidebarWidth,
  } = useResizablePanel({
    storageKey: "sidebar-width",
    defaultWidth: SIDEBAR_WIDTH,
    minWidth: 200,
    maxWidth: 400,
    edge: "right",
  });
  // The hook seeds itself from localStorage and the window width, neither of
  // which exists when this static page is prerendered — so the sidebar renders
  // expanded until mount and the server and client markup agree.
  const [mounted, setMounted] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  useEffect(() => setMounted(true), []);
  useEffect(() => setMobileNavOpen(false), [pathname]);
  const collapsed = mounted && sidebarCollapsed;

  const { agents } = useAgents();
  // Exact match only, across owned and shared agents. Falling back to the first
  // agent is what made Home look like an agent was open — the shell shows an
  // agent when one was asked for by id, and nothing otherwise. A shared agent
  // has to resolve here too, or its own pages render with no rail and no name.
  const { agent } = useAgent(agentId);
  const tableCount = agent ? includedTableCount(agent.dbs) : null;

  // The rail navigates within one agent, so it only exists inside one. Home and
  // Usage are workspace-level and run full width.
  const showSidebar = Boolean(agent);
  const railItems = railItemsFor(agent);

  // Topbar secondary text: Home counts agents, workspace-wide Usage says so
  // explicitly, and every agent-scoped view names its agent.
  const isUsage = pathname.startsWith(ROUTES.usage);
  const defaultCrumb = isUsage
    ? "across all agents"
    : agent
      ? agent.name
      : `${agents.length} agent${agents.length === 1 ? "" : "s"}`;

  // Only the agent count is known without another request; the conversation
  // count comes from the sessions call the Conversations view makes.
  const counts = { agents: agents.length } as const;

  const sidebarWidth = collapsed ? COLLAPSED_SIDEBAR_WIDTH : sidebarDragWidth;

  return (
    // `n2s-root` scopes the product's tokens, palette and type to its own
    // subtree, and the font class publishes the three faces they reference.
    // `h-screen overflow-hidden`, not `min-h-screen`: `main` below already owns
    // the scrolling at `calc(100vh - TOPBAR)` with a matching `margin-top`, so
    // a root that could grow past the viewport paid for the topbar twice — the
    // document overflowed by exactly 56px and produced a second scrollbar that
    // fought the inner one, nudging the whole page by the height of the header.
    // One scroll container, and it is `main`.
    <div className={cn("n2s-root h-screen overflow-hidden", NL2SQL_FONT_CLASS)}>
      <header className="fixed top-0 inset-x-0 z-20 flex items-center justify-between px-4 md:px-6 h-14 bg-white/80 supports-backdrop-filter:bg-white/70 backdrop-blur-xl border-b border-slate-200/60">
        {/* Left: brand + breadcrumb */}
        <div className="flex items-center gap-2 min-w-0">
          <Link
            href={ROUTES.home}
            className="shrink-0 flex items-center gap-1.5 text-base font-bold text-indigo-600 hover:text-indigo-700 transition-colors"
          >
            <div className="flex items-center justify-center size-6 rounded-md bg-linear-to-br from-indigo-600 to-blue-500">
              <Icon name="bot" className="size-3.5 text-white" />
            </div>
            {/* The wordmark is title-shaped but not a heading, so it asks for
                the display face by name. */}
            <span className="n2s-display hidden sm:inline">FutureSmart</span>
          </Link>
          <span className="text-slate-300 text-sm shrink-0">/</span>
          <h1 className="text-sm font-semibold text-slate-900 truncate">
            {title ?? current?.title ?? "Usage"}
          </h1>
          {showSidebar && (
            <Button
              variant="ghost"
              size="icon"
              className="md:hidden"
              aria-label={
                mobileNavOpen ? "Close navigation" : "Open navigation"
              }
              aria-expanded={mobileNavOpen}
              aria-controls="nl2sql-mobile-navigation"
              onClick={() => setMobileNavOpen((open) => !open)}
              startIcon={
                mobileNavOpen ? (
                  <Icon name="x" className="size-4" />
                ) : (
                  <Icon name="menu" className="size-4" />
                )
              }
            />
          )}
        </div>

        {/* Center: active agent context */}
        {agent && (
          <div className="hidden md:flex items-center absolute left-1/2 -translate-x-1/2">
            <div className="flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs shadow-sm">
              <span className="relative flex size-2">
                {agent.active && (
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                )}
                <span
                  className={cn(
                    "relative inline-flex size-2 rounded-full",
                    agent.active ? "bg-emerald-500" : "bg-slate-400",
                  )}
                />
              </span>
              <span className="font-medium text-slate-700">{agent.name}</span>
              <span className="h-3 w-px bg-slate-200" />
              <span className="font-mono text-[10px] text-slate-500">
                {agent.dbs.length} database
                {agent.dbs.length === 1 ? "" : "s"}
                {tableCount !== null &&
                  ` · ${tableCount} ${tableCount === 1 ? "table" : "tables"}`}
              </span>
            </div>
          </div>
        )}

        {/* Right: viewer — the agent UI's own profile menu, not a lookalike. */}
        <div className="flex items-center gap-2 shrink-0">
          <span className="hidden whitespace-nowrap text-xs text-slate-400 lg:block">
            {crumb ?? defaultCrumb}
          </span>
          {/* The way out of the product. The brand above goes to this
              product's own Home, so the site needs its own control —
              Document Intelligence carries the same one in the same place. */}
          <Button
            as="a"
            href="https://futuresmart.ai/solutions/database-agent"
            variant="ghost"
            size="icon"
            title="Back to the site"
            aria-label="Back to the site"
            startIcon={<Icon name="globe" className="size-4" />}
          />
          <ProfileDropdown collapsed={false} inHeader />
        </div>
      </header>

      {showSidebar && mobileNavOpen && (
        <nav
          id="nl2sql-mobile-navigation"
          aria-label="Main"
          className="fixed inset-x-0 top-14 z-30 border-b border-slate-200 bg-white p-2 shadow-lg md:hidden"
        >
          <ul className="grid grid-cols-2 gap-1">
            {railItems.map((item) => {
              const isActive = item.href === current?.href;
              return (
                <li key={item.href}>
                  <Link
                    href={navHref(item, agentId)}
                    aria-current={isActive ? "page" : undefined}
                    className={cn(
                      "flex min-h-10 items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                      isActive
                        ? "bg-indigo-50 text-indigo-700"
                        : "text-slate-700 hover:bg-slate-50",
                    )}
                  >
                    <Icon name={item.icon} className="size-4" />
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      )}

      {showSidebar && (
        <aside
          role="complementary"
          aria-label="Main navigation"
          className="fixed left-0 top-0 bottom-0 hidden flex-col overflow-visible border-r border-gray-200 bg-white transition-[width] duration-200 ease-in-out md:flex"
          style={{ width: sidebarWidth }}
        >
          <div className="flex items-center justify-between px-3 py-3 border-b border-gray-100">
            <h2 className="m-0 flex items-center gap-1.5 text-lg font-semibold tracking-tight">
              <Icon name="db" className="size-4 shrink-0 text-indigo-600" />
              {!collapsed && (
                <span className="bg-linear-to-r from-slate-900 via-indigo-700 to-blue-600 bg-clip-text text-transparent">
                  {PRODUCT_NAME}
                </span>
              )}
            </h2>
            <Button
              variant="ghost"
              size="icon"
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              onClick={toggleSidebarCollapsed}
              startIcon={
                <Icon
                  name="caretRight"
                  className={cn(
                    "size-4 transition-transform duration-200",
                    collapsed ? "rotate-90" : "rotate-180",
                  )}
                />
              }
            />
          </div>

          {/* No byline: the rail's own heading sits behind the fixed topbar, as
              it does in the agent UI, so a line under it read as a stray label
              floating above the navigation. */}
          <nav
            aria-label="Main"
            className="mt-2 min-h-0 flex-1 overflow-y-auto [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-slate-300 [&::-webkit-scrollbar-track]:bg-transparent"
          >
            <ul className="px-2">
              {railItems.map((item) => {
                const isActive = item.href === current?.href;
                return (
                  <li key={item.href} className="mb-1 relative group">
                    {isActive && (
                      <span className="absolute left-0 top-1/2 -translate-y-1/2 h-6 w-1 rounded-full bg-indigo-500" />
                    )}
                    {/* Same ghost Button the agent UI's rail uses, so the two
                        sidebars have identical hover, height and active fill. */}
                    <Link
                      href={navHref(item, agentId)}
                      aria-current={isActive ? "page" : undefined}
                    >
                      <Tooltip content={item.label} disabled={!collapsed}>
                        <Button
                          variant="ghost"
                          size="sm"
                          fullWidth
                          className={cn(
                            collapsed ? "justify-center" : "justify-start",
                            isActive
                              ? "bg-indigo-50 text-indigo-700!"
                              : "text-slate-700 hover:bg-slate-50",
                          )}
                          startIcon={<Icon name={item.icon} />}
                          title={collapsed ? item.label : undefined}
                          labelClassName="w-full"
                        >
                          {!collapsed && (
                            <span className="flex w-full items-center justify-between gap-2">
                              {item.label}
                              {item.count === "agents" && (
                                <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold text-slate-500">
                                  {counts.agents}
                                </span>
                              )}
                            </span>
                          )}
                        </Button>
                      </Tooltip>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </nav>

          {/* Floating collapse handle and drag-to-resize edge, both as in the
              agent UI — a rail that cannot be resized here but can there is the
              kind of difference that reads as a different product. */}
          <Button
            variant="ghost"
            size="icon"
            shape="rounded"
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            title={collapsed ? "Expand" : "Collapse"}
            onClick={toggleSidebarCollapsed}
            className="absolute flex top-20 -right-3 z-20 size-6 cursor-pointer items-center justify-center rounded-full border border-slate-200 bg-white text-slate-700 shadow-md hover:bg-slate-50"
            startIcon={
              <Icon
                name="caretLeft"
                className={cn(
                  "size-4 transition-transform duration-200",
                  collapsed && "rotate-180",
                )}
              />
            }
          />
          {!collapsed && (
            <div
              role="separator"
              aria-orientation="vertical"
              aria-label="Resize sidebar"
              tabIndex={0}
              onPointerDown={startSidebarResize}
              onDoubleClick={resetSidebarWidth}
              onKeyDown={(event) => {
                if (event.key === "ArrowLeft") {
                  setSidebarWidth(sidebarDragWidth - 24);
                }
                if (event.key === "ArrowRight") {
                  setSidebarWidth(sidebarDragWidth + 24);
                }
              }}
              title="Drag to resize — double-click to reset"
              className={cn(
                "absolute right-0 top-0 z-10 h-full w-1.5 translate-x-1/2 cursor-col-resize",
                "after:absolute after:inset-y-0 after:left-1/2 after:w-px after:-translate-x-1/2 after:bg-transparent",
                "hover:after:bg-indigo-400",
                isSidebarResizing && "after:bg-indigo-500",
              )}
            />
          )}
        </aside>
      )}

      <main
        className={cn(
          "bg-white text-black overflow-y-auto",
          // The rail is a fixed overlay that only exists from `md` up (below it
          // the nav is the dropdown above), so the content is only inset there.
          // The width comes through a custom property rather than a class so a
          // dragged rail moves the content with it instead of snapping.
          showSidebar && "md:ml-(--rail-width)",
        )}
        style={
          {
            "--rail-width": `${sidebarWidth}px`,
            marginTop: TOPBAR_HEIGHT,
            height: `calc(100vh - ${TOPBAR_HEIGHT}px)`,
          } as React.CSSProperties
        }
      >
        {/* No max width: the agent UI lets a page use the whole window, and a
            capped column here made identical pages look narrower. */}
        <div className={flush ? "h-full" : "px-6 py-6"}>{children}</div>
      </main>
    </div>
  );
}

/**
 * Every view renders inside the agent UI's auth context, so any component
 * reused from that app — the profile menu, the whole chat — finds the agent and
 * viewer it expects without each page wiring that up.
 */
export default function AppShell(props: AppShellProps) {
  return (
    <AuthBridge agentId={props.agentId}>
      <Shell {...props} />
    </AuthBridge>
  );
}
