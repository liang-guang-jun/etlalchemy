import { useEffect, useRef, useState } from 'react';
import { ChevronDown, LogOut, MessagesSquare, Moon, Search, Settings, Sun } from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import { Link, NavLink, Outlet, useLocation } from 'react-router';

import { selectIsSystemAdmin, useSessionStore } from '@/entities/session';
import { useLogout } from '@/features/auth-logout';
import { useCommentPanelStore, useMyOpenThreadCount } from '@/features/comment-threads';
import { AgentFloatingWidget } from '@/widgets/agent-chat';
import { CommentInboxDrawer, CommentPanelDrawer } from '@/widgets/comment-drawers';
import { ADMIN_NAV_ITEMS, NAV_ITEMS } from '@/shared/config/navigation';
import { cn } from '@/shared/lib/cn';
import { Brand } from '@/shared/ui';

type Theme = 'light' | 'dark';
type HeaderMenu = 'user' | 'settings';

const THEME_STORAGE_KEY = 'etlalchemy.theme';

/** Shared sizing of the square icon buttons in the header action row. */
const HEADER_ICON_BUTTON =
  'flex size-9 items-center justify-center rounded-md text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary';

/** Applied to a header icon button whose target route is active. */
const ACTIVE_ICON_BUTTON = 'bg-bg-hover text-text-primary';

/** Frame shared by the two header dropdown menus. */
const MENU_PANEL =
  'absolute right-0 top-full z-50 mt-1 rounded-md border border-border-base bg-bg-surface py-1 shadow-md';

/** Fade-and-drop animation shared by the header dropdown menus. */
const MENU_MOTION = {
  initial: { opacity: 0, y: -6 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -6 },
  transition: { duration: 0.15, ease: 'easeOut' },
} as const;

function readStoredTheme(): Theme {
  return window.localStorage.getItem(THEME_STORAGE_KEY) === 'dark' ? 'dark' : 'light';
}

function initials(name: string): string {
  const trimmed = name.trim();
  return trimmed === '' ? '?' : trimmed.slice(0, 2).toUpperCase();
}

/**
 * Application shell: a full-width top bar, a narrow icon rail and a floating
 * white content card.
 *
 * The rail is deliberately fixed at 64px: it only shows icons and reveals the
 * label of each entry as a tooltip on hover.
 *
 * @returns The layout element.
 */
export function AppShell() {
  const location = useLocation();
  const isAdmin = useSessionStore(selectIsSystemAdmin);
  const user = useSessionStore((state) => state.user);
  const logout = useLogout();
  const [theme, setTheme] = useState<Theme>(readStoredTheme);
  const [openMenu, setOpenMenu] = useState<HeaderMenu | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  }, [theme]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
    };
  }, []);

  useEffect(() => {
    if (openMenu === null) {
      return undefined;
    }
    const onClick = () => {
      setOpenMenu(null);
    };
    window.addEventListener('click', onClick);
    return () => {
      window.removeEventListener('click', onClick);
    };
  }, [openMenu]);

  const displayName = user?.display_name || user?.username || 'Not signed in';
  const settingsActive = ADMIN_NAV_ITEMS.some((item) => location.pathname.startsWith(item.to));
  const openInbox = useCommentPanelStore((state) => state.openInbox);
  const threadCount = useMyOpenThreadCount();

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden bg-bg-canvas text-text-primary">
      <header className="relative flex h-14 w-full shrink-0 items-center justify-between gap-4 px-6">
        <div className="flex shrink-0 items-center gap-4">
          <Link to="/catalog" aria-label="ETLAlchemy home">
            <Brand />
          </Link>
        </div>

        <div className="absolute left-1/2 top-1/2 hidden w-full max-w-lg -translate-x-1/2 -translate-y-1/2 md:block">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-text-secondary"
            aria-hidden="true"
          />
          <input
            ref={searchRef}
            type="search"
            aria-label="Global search"
            placeholder="Search catalogs, tables, fields or terms…"
            className="h-9 w-full rounded-md border border-border-strong bg-bg-surface pl-9 pr-16 text-sm text-text-primary shadow-sm outline-none transition-shadow placeholder:text-text-secondary/80 focus:border-brand focus:ring-2 focus:ring-brand/40"
          />
          <kbd className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 rounded-sm border border-border-strong bg-bg-canvas px-1.5 py-0.5 text-[11px] text-text-secondary">
            ⌘K
          </kbd>
        </div>

        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            aria-label="Discussions"
            title="Discussions"
            aria-haspopup="dialog"
            onClick={() => {
              openInbox();
            }}
            className={cn(HEADER_ICON_BUTTON, 'relative')}
          >
            <MessagesSquare className="size-[18px]" aria-hidden="true" />
            {threadCount === 0 ? null : (
              <span className="absolute right-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-danger px-1 text-[9px] font-semibold text-white">
                {threadCount > 9 ? '9+' : threadCount}
              </span>
            )}
          </button>

          {isAdmin ? (
            <div className="relative">
              <button
                type="button"
                aria-label="Settings"
                title="Settings"
                aria-haspopup="menu"
                aria-expanded={openMenu === 'settings'}
                onClick={(event) => {
                  event.stopPropagation();
                  setOpenMenu((current) => (current === 'settings' ? null : 'settings'));
                }}
                className={cn(HEADER_ICON_BUTTON, settingsActive && ACTIVE_ICON_BUTTON)}
              >
                <Settings className="size-[18px]" aria-hidden="true" />
              </button>
              <AnimatePresence>
                {openMenu === 'settings' ? (
                  <motion.div
                    role="menu"
                    aria-label="Settings"
                    {...MENU_MOTION}
                    onClick={(event) => {
                      event.stopPropagation();
                    }}
                    className={cn(MENU_PANEL, 'w-56')}
                  >
                    <p className="px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-text-disabled">
                      Admin console
                    </p>
                    {ADMIN_NAV_ITEMS.map((item) => (
                      <NavLink
                        key={item.to}
                        to={item.to}
                        role="menuitem"
                        onClick={() => {
                          setOpenMenu(null);
                        }}
                        className={({ isActive }) =>
                          cn(
                            'flex items-center gap-2 px-3 py-2 text-sm transition-colors',
                            isActive
                              ? 'bg-bg-hover font-medium text-text-primary'
                              : 'text-text-primary hover:bg-bg-hover',
                          )
                        }
                      >
                        <item.icon className="size-4 text-text-secondary" aria-hidden="true" />
                        {item.label}
                      </NavLink>
                    ))}
                  </motion.div>
                ) : null}
              </AnimatePresence>
            </div>
          ) : null}

          <button
            type="button"
            aria-label="Toggle theme"
            title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            onClick={() => {
              setTheme((current) => (current === 'dark' ? 'light' : 'dark'));
            }}
            className={HEADER_ICON_BUTTON}
          >
            {theme === 'dark' ? (
              <Sun className="size-[18px]" aria-hidden="true" />
            ) : (
              <Moon className="size-[18px]" aria-hidden="true" />
            )}
          </button>

          <div className="relative">
            <button
              type="button"
              aria-haspopup="menu"
              aria-expanded={openMenu === 'user'}
              onClick={(event) => {
                event.stopPropagation();
                setOpenMenu((current) => (current === 'user' ? null : 'user'));
              }}
              className="flex h-9 items-center gap-2 rounded-md px-1.5 transition-colors hover:bg-bg-hover"
            >
              <span className="flex size-7 items-center justify-center rounded-full bg-brand text-xs font-semibold text-brand-text">
                {initials(displayName)}
              </span>
              <span className="hidden max-w-32 truncate text-sm text-text-secondary lg:block">
                {displayName}
              </span>
              <ChevronDown className="size-3 text-text-secondary" aria-hidden="true" />
            </button>
            <AnimatePresence>
              {openMenu === 'user' ? (
                <motion.div
                  role="menu"
                  aria-label="Account"
                  {...MENU_MOTION}
                  onClick={(event) => {
                    event.stopPropagation();
                  }}
                  className={cn(MENU_PANEL, 'w-56')}
                >
                  <div className="border-b border-border-base px-3 py-2">
                    <p className="truncate text-sm font-medium text-text-primary">{displayName}</p>
                    <p className="truncate text-xs text-text-secondary">{user?.email ?? ''}</p>
                  </div>
                  <button
                    type="button"
                    role="menuitem"
                    className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-text-primary hover:bg-bg-hover disabled:text-text-disabled"
                    disabled={logout.isPending}
                    onClick={() => {
                      logout.mutate();
                    }}
                  >
                    <LogOut className="size-4" aria-hidden="true" />
                    Sign out
                  </button>
                </motion.div>
              ) : null}
            </AnimatePresence>
          </div>
        </div>
      </header>

      {/* The rail and the content card share an edge: the selected item's white
          pill overflows into the card so both read as one surface. */}
      <div className="flex flex-1 overflow-hidden pb-4 pr-4 pt-2">
        <aside className="relative flex w-16 shrink-0 flex-col overflow-visible">
          <nav
            className="flex w-full flex-1 flex-col gap-1 px-3 pb-1 pt-5"
            aria-label="Main navigation"
          >
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end === true}
                aria-label={item.label}
                className="group relative flex h-10 w-full items-center justify-center outline-none"
              >
                {({ isActive }) => (
                  <>
                    {isActive ? (
                      <motion.span
                        layoutId="active-nav-indicator"
                        aria-hidden="true"
                        // A tab glued to the content card: 4px of air above and
                        // below, rounded on the left, square and flush on the
                        // right where it meets the card.
                        className="absolute inset-y-1 left-0 right-[-12px] z-10 rounded-l-md bg-bg-surface"
                        transition={{ type: 'spring', stiffness: 400, damping: 35 }}
                      >
                        {/* Inverted radii: a 12px square whose background is a
                            radial gradient — transparent inside the circle at
                            the outer corner, surface colour outside it — so the
                            tab's edge curves into the panel instead of cutting
                            it with a straight line. */}
                        <span
                          className="absolute -top-3 right-0 h-3 w-3"
                          style={{
                            background:
                              'radial-gradient(circle 12px at 0 0, transparent 11px, var(--color-bg-surface) 12px)',
                          }}
                        />
                        <span
                          className="absolute -bottom-3 right-0 h-3 w-3"
                          style={{
                            background:
                              'radial-gradient(circle 12px at 0 100%, transparent 11px, var(--color-bg-surface) 12px)',
                          }}
                        />
                      </motion.span>
                    ) : null}
                    <item.icon
                      className={cn(
                        'relative z-20 size-5 transition-colors',
                        isActive
                          ? 'text-brand-ink'
                          : 'text-text-secondary group-hover:text-text-primary',
                      )}
                      aria-hidden="true"
                    />
                    <span className="pointer-events-none absolute left-full top-1/2 z-50 ml-2 -translate-y-1/2 whitespace-nowrap rounded-md bg-black/75 px-2 py-1 text-xs font-medium text-white opacity-0 transition-opacity duration-150 group-hover:opacity-100 group-focus-visible:opacity-100">
                      {item.label}
                    </span>
                  </>
                )}
              </NavLink>
            ))}
          </nav>
        </aside>

        <main className="min-w-0 flex-1 overflow-hidden">
          {/* Pages own their padding and scrolling, so a workspace such as the
              data catalog can split the card into a tree and a detail pane. */}
          <div className="h-full overflow-hidden rounded-xl bg-bg-surface shadow-sm">
            <Outlet />
          </div>
        </main>
      </div>

      {/* One pair of drawers for the whole app: entry points only open a target. */}
      <CommentInboxDrawer />
      <CommentPanelDrawer />

      {/* The floating agent is global, but hides itself on the full page where
          the same conversation is already on screen. */}
      {location.pathname.startsWith('/agent') ? null : <AgentFloatingWidget />}
    </div>
  );
}
