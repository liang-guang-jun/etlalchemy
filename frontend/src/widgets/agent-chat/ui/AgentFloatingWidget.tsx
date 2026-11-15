import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent } from 'react';
import { createPortal } from 'react-dom';
import { AnimatePresence, motion } from 'motion/react';
import { History, Maximize2, Minus, Plus, Search, Sparkles } from 'lucide-react';
import { useLocation, useNavigate } from 'react-router';

import {
  filterConversations,
  useActiveConversation,
  useAgentStore,
  useConversationFeed,
  useConversationHydration,
  useTranscript,
  type AgentConversation,
} from '@/entities/agent';
import { Composer, useAgentChat } from '@/features/agent-chat';
import {
  describeLocationContext,
  formatLocationContext,
  locationContextNote,
} from '@/shared/config/navigation';
import { cn } from '@/shared/lib/cn';
import { clampToViewport, placePanel, type PanelPlacement } from '@/shared/lib/floating-placement';
import { Popover, Switch } from '@/shared/ui';

import {
  clampPanelSize,
  readPanelSize,
  readWidgetPosition,
  WIDGET_SIZE,
  writePanelSize,
  writeWidgetPosition,
} from '../model/position';
import { MessageList } from './MessageList';

/** Movement in pixels above which a pointer gesture counts as a drag. */
const DRAG_THRESHOLD = 4;

/** Prompts offered before the first message. */
const SUGGESTIONS = [
  'Which tables have no description yet?',
  'List the semantic models and their entities',
  'Which business terms are still drafts?',
];

/**
 * Renders a conversation title with a fallback for untitled chats.
 *
 * @param props Component props.
 * @returns The label text.
 */
function ConversationLabel({ conversation }: { conversation: AgentConversation }) {
  return (
    <span className="block truncate">
      {conversation.title === '' ? 'New conversation' : conversation.title}
    </span>
  );
}

/**
 * Renders the globally available agent button and its popover.
 *
 * The button is draggable and remembers where it was left. The popover opens
 * away from the nearest corner and stays inside the viewport, so a button
 * dragged to an edge still gets a usable panel. Both surfaces read the same
 * store, so a conversation started here is already open on the page.
 *
 * @returns The floating widget.
 */
export function AgentFloatingWidget() {
  const navigate = useNavigate();
  const location = useLocation();
  const feed = useConversationFeed();
  const conversations = useAgentStore((state) => state.conversations);
  const activeConversationId = useAgentStore((state) => state.activeConversationId);
  const setActiveConversation = useAgentStore((state) => state.setActiveConversation);
  const widgetOpen = useAgentStore((state) => state.widgetOpen);
  const setWidgetOpen = useAgentStore((state) => state.setWidgetOpen);
  const autoApprove = useAgentStore((state) => state.autoApprove);
  const setAutoApprove = useAgentStore((state) => state.setAutoApprove);
  const active = useActiveConversation();
  const transcript = useTranscript(activeConversationId);
  const chat = useAgentChat(activeConversationId);
  const [position, setPosition] = useState(() => readWidgetPosition());
  const [placement, setPlacement] = useState<PanelPlacement | null>(null);
  const [anchor, setAnchor] = useState<{
    x: number;
    y: number;
    width: number;
    height: number;
  } | null>(null);
  const [historyTerm, setHistoryTerm] = useState('');
  const [size, setSize] = useState(() => readPanelSize());
  const buttonRef = useRef<HTMLButtonElement>(null);
  // `place` runs from callbacks and effects, so it reads the committed size through
  // a ref: resizing must not re-place the panel, only move its edges.
  const sizeRef = useRef(size);
  useEffect(() => {
    sizeRef.current = size;
  }, [size]);
  const drag = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    originX: number;
    originY: number;
    moved: boolean;
  } | null>(null);
  const headerDrag = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    originLeft: number;
    originTop: number;
  } | null>(null);
  const resizeDrag = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    originWidth: number;
    originHeight: number;
  } | null>(null);

  useConversationHydration(activeConversationId);

  useEffect(() => {
    const onResize = () => {
      const viewport = { width: window.innerWidth, height: window.innerHeight };
      setPosition((current) => clampToViewport(current, WIDGET_SIZE, viewport));
      setSize((current) => clampPanelSize(current, viewport));
    };
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('resize', onResize);
    };
  }, []);

  const place = useCallback(() => {
    const rect = buttonRef.current?.getBoundingClientRect();
    if (rect === undefined) {
      return;
    }
    const box = { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
    setAnchor(box);
    setPlacement(
      placePanel(
        box,
        { x: 0, y: 0, width: sizeRef.current.width, height: sizeRef.current.height },
        { x: 0, y: 0, width: window.innerWidth, height: window.innerHeight },
      ),
    );
  }, []);

  useEffect(() => {
    if (!widgetOpen) {
      setPlacement(null);
      return undefined;
    }
    place();
    window.addEventListener('resize', place);
    return () => {
      window.removeEventListener('resize', place);
    };
  }, [widgetOpen, position, place]);

  useEffect(() => {
    if (!widgetOpen) {
      return undefined;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setWidgetOpen(false);
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [widgetOpen, setWidgetOpen]);

  const onPointerDown = (event: PointerEvent<HTMLButtonElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originX: position.x,
      originY: position.y,
      moved: false,
    };
  };

  const onPointerMove = (event: PointerEvent<HTMLButtonElement>) => {
    const current = drag.current;
    if (current === null || current.pointerId !== event.pointerId) {
      return;
    }
    const dx = event.clientX - current.startX;
    const dy = event.clientY - current.startY;
    if (!current.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD) {
      return;
    }
    current.moved = true;
    setPosition(
      clampToViewport({ x: current.originX + dx, y: current.originY + dy }, WIDGET_SIZE, {
        width: window.innerWidth,
        height: window.innerHeight,
      }),
    );
  };

  const onPointerUp = (event: PointerEvent<HTMLButtonElement>) => {
    const current = drag.current;
    drag.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
    if (current === null) {
      return;
    }
    if (current.moved) {
      // A drag moves the widget; it must not also toggle the popover.
      writeWidgetPosition(position);
      setPlacement(null);
      setWidgetOpen(false);
      return;
    }
    setWidgetOpen(!widgetOpen);
  };

  const expand = () => {
    setWidgetOpen(false);
    navigate(activeConversationId === null ? '/agent' : `/agent/${activeConversationId}`);
  };

  // The header's blank area is the panel handle: it moves the dialog without
  // touching the icon, so the anchor and the panel position can differ.
  const onHeaderPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (placement === null) {
      return;
    }
    event.currentTarget.setPointerCapture(event.pointerId);
    headerDrag.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originLeft: placement.left,
      originTop: placement.top,
    };
  };

  const onHeaderPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const current = headerDrag.current;
    if (current === null || current.pointerId !== event.pointerId) {
      return;
    }
    const left = current.originLeft + (event.clientX - current.startX);
    const top = current.originTop + (event.clientY - current.startY);
    setPlacement((previous) =>
      previous === null
        ? previous
        : {
            ...previous,
            left: Math.max(0, Math.min(left, window.innerWidth - size.width)),
            top: Math.max(0, Math.min(top, window.innerHeight - size.height)),
          },
    );
  };

  const onHeaderPointerUp = (event: PointerEvent<HTMLDivElement>) => {
    if (headerDrag.current === null) {
      return;
    }
    headerDrag.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
  };

  // The corner grip resizes the panel in both axes, inside the viewport limits.
  const onResizePointerDown = (event: PointerEvent<HTMLSpanElement>) => {
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    resizeDrag.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originWidth: size.width,
      originHeight: size.height,
    };
  };

  const onResizePointerMove = (event: PointerEvent<HTMLSpanElement>) => {
    const current = resizeDrag.current;
    if (current === null || current.pointerId !== event.pointerId) {
      return;
    }
    const viewport = { width: window.innerWidth, height: window.innerHeight };
    const next = clampPanelSize(
      {
        width: current.originWidth + (event.clientX - current.startX),
        height: current.originHeight + (event.clientY - current.startY),
      },
      viewport,
    );
    setSize(next);
    // Growing must not push the panel off screen, and must not re-place it.
    setPlacement((previous) =>
      previous === null
        ? previous
        : {
            ...previous,
            left: Math.max(0, Math.min(previous.left, viewport.width - next.width)),
            top: Math.max(0, Math.min(previous.top, viewport.height - next.height)),
          },
    );
  };

  const onResizePointerUp = (event: PointerEvent<HTMLSpanElement>) => {
    if (resizeDrag.current === null) {
      return;
    }
    resizeDrag.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
    writePanelSize(size);
  };

  const title = active === null || active.title === '' ? 'New conversation' : active.title;
  // The widget survives navigation, so the page is read on every render: each
  // prompt names the resource the reader is looking at right now. The agent page
  // itself holds no resource worth sending.
  const pageContext = useMemo(
    () => describeLocationContext(location.pathname, location.search),
    [location.pathname, location.search],
  );
  const onAgentRoute = location.pathname === '/agent' || location.pathname.startsWith('/agent/');
  const contextSummary = onAgentRoute ? null : formatLocationContext(pageContext);
  const contextLabels = contextSummary === null ? [] : [contextSummary];
  const contextNote = onAgentRoute ? null : locationContextNote(pageContext);
  const recent = useMemo(
    () => filterConversations(conversations, historyTerm).slice(0, 20),
    [conversations, historyTerm],
  );
  // The panel grows out of the icon, so the origin is the icon centre in panel
  // coordinates: the two never show up side by side.
  const origin =
    anchor === null || placement === null
      ? 'center'
      : `${String(anchor.x + anchor.width / 2 - placement.left)}px ${String(
          anchor.y + anchor.height / 2 - placement.top,
        )}px`;

  return (
    <>
      <motion.button
        ref={buttonRef}
        type="button"
        aria-label="Open the agent"
        aria-haspopup="dialog"
        aria-expanded={widgetOpen}
        aria-hidden={widgetOpen}
        tabIndex={widgetOpen ? -1 : 0}
        title="Agent — drag to move, click to ask"
        animate={{ opacity: widgetOpen ? 0 : 1, scale: widgetOpen ? 0.6 : 1 }}
        transition={{ duration: 0.18, ease: 'easeOut' }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        style={{
          left: position.x,
          top: position.y,
          width: WIDGET_SIZE,
          height: WIDGET_SIZE,
          pointerEvents: widgetOpen ? 'none' : 'auto',
        }}
        className={cn(
          'fixed z-40 flex cursor-grab touch-none items-center justify-center rounded-full',
          'bg-brand text-brand-text shadow-lg transition-colors hover:bg-brand-hover',
          'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand',
          'active:cursor-grabbing',
        )}
      >
        <Sparkles className="size-6" aria-hidden="true" />
      </motion.button>

      {createPortal(
        <AnimatePresence>
          {widgetOpen && placement !== null ? (
            <motion.div
              key="agent-panel"
              role="dialog"
              aria-label="Agent"
              initial={{ opacity: 0, scale: 0.15 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.15 }}
              transition={{ duration: 0.2, ease: [0.2, 0.9, 0.2, 1] }}
              style={{
                left: placement.left,
                top: placement.top,
                width: size.width,
                height: size.height,
                transformOrigin: origin,
              }}
              className={cn(
                'fixed z-40 flex flex-col overflow-hidden rounded-xl',
                'border border-border-base bg-bg-surface/95 shadow-2xl backdrop-blur-md',
              )}
            >
              <header className="flex shrink-0 items-center gap-1 border-b border-border-base px-2 py-1.5">
                <div
                  onPointerDown={onHeaderPointerDown}
                  onPointerMove={onHeaderPointerMove}
                  onPointerUp={onHeaderPointerUp}
                  title="Drag to move the agent"
                  className="flex min-w-0 flex-1 cursor-grab touch-none items-center px-1 select-none active:cursor-grabbing"
                >
                  <span className="min-w-0 truncate text-sm font-medium text-text-primary">
                    {title}
                  </span>
                </div>
                <label className="flex shrink-0 items-center gap-1.5 pr-1 text-[11px] text-text-secondary">
                  <Switch
                    checked={autoApprove}
                    onCheckedChange={setAutoApprove}
                    label="Auto-approve destructive tools"
                  />
                  <span aria-hidden="true">auto-approve</span>
                </label>
                <button
                  type="button"
                  aria-label="New conversation"
                  title="New conversation"
                  onClick={() => {
                    setActiveConversation(null);
                  }}
                  className="flex size-7 items-center justify-center rounded-md text-text-secondary hover:bg-bg-hover hover:text-text-primary"
                >
                  <Plus className="size-4" aria-hidden="true" />
                </button>
                <Popover
                  label="Conversation history"
                  align="end"
                  panelClassName="w-72"
                  triggerClassName="size-7 text-text-secondary hover:bg-bg-hover"
                  trigger={<History className="size-4" aria-hidden="true" />}
                >
                  {(close) => (
                    <div className="flex flex-col gap-1 p-1">
                      <label className="flex items-center gap-1.5 rounded-md border border-border-base bg-bg-canvas px-2 py-1">
                        <Search
                          className="size-3.5 shrink-0 text-text-disabled"
                          aria-hidden="true"
                        />
                        <input
                          type="search"
                          value={historyTerm}
                          onChange={(event) => {
                            setHistoryTerm(event.target.value);
                          }}
                          onKeyDown={(event) => {
                            // Escape closes the search, not the whole widget.
                            if (event.key === 'Escape') {
                              event.stopPropagation();
                            }
                          }}
                          placeholder="Search conversations"
                          aria-label="Search conversations"
                          autoFocus
                          className="w-full bg-transparent text-xs text-text-primary outline-none placeholder:text-text-disabled"
                        />
                      </label>
                      <ul className="max-h-64 overflow-y-auto">
                        {recent.length === 0 ? (
                          <li className="px-2 py-1.5 text-xs text-text-secondary">
                            {conversations.length === 0
                              ? 'No conversations yet.'
                              : 'No conversation matches that search.'}
                          </li>
                        ) : (
                          recent.map((conversation) => (
                            <li key={conversation.conversation_id}>
                              <button
                                type="button"
                                className="w-full rounded-sm px-2 py-1.5 text-left text-sm text-text-primary hover:bg-bg-hover"
                                onClick={() => {
                                  close();
                                  setActiveConversation(conversation.conversation_id);
                                }}
                              >
                                <ConversationLabel conversation={conversation} />
                              </button>
                            </li>
                          ))
                        )}
                      </ul>
                    </div>
                  )}
                </Popover>
                <button
                  type="button"
                  aria-label="Expand to full screen"
                  title="Expand to full screen"
                  onClick={expand}
                  className="flex size-7 items-center justify-center rounded-md text-text-secondary hover:bg-bg-hover hover:text-text-primary"
                >
                  <Maximize2 className="size-4" aria-hidden="true" />
                </button>
                <button
                  type="button"
                  aria-label="Minimize the agent"
                  title="Minimize"
                  onClick={() => {
                    setWidgetOpen(false);
                  }}
                  className="flex size-7 items-center justify-center rounded-md text-text-secondary hover:bg-bg-hover hover:text-text-primary"
                >
                  <Minus className="size-4" aria-hidden="true" />
                </button>
              </header>

              <div className="min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto">
                {feed.isError ? (
                  <p role="alert" className="p-3 text-xs text-danger">
                    The conversation history could not be loaded.
                  </p>
                ) : null}
                <MessageList
                  conversationId={activeConversationId}
                  transcript={transcript}
                  compact
                  suggestions={SUGGESTIONS}
                  onOpenFullScreen={expand}
                  onSuggestion={(prompt) => {
                    void chat.send(prompt);
                  }}
                  onEditMessage={(messageId, content) => {
                    void chat.edit(messageId, content);
                  }}
                />
              </div>

              <Composer
                conversationId={activeConversationId}
                compact
                autoFocus
                contextLabels={contextLabels}
                contextNote={contextNote}
              />

              <span
                role="separator"
                aria-label="Resize the agent panel"
                aria-orientation="horizontal"
                onPointerDown={onResizePointerDown}
                onPointerMove={onResizePointerMove}
                onPointerUp={onResizePointerUp}
                className="absolute right-0 bottom-0 z-10 flex size-3.5 cursor-nwse-resize touch-none items-end justify-end text-text-disabled"
              >
                <svg viewBox="0 0 10 10" className="size-2.5" aria-hidden="true">
                  <path
                    d="M9 1 1 9M9 5 5 9"
                    stroke="currentColor"
                    strokeWidth="1.2"
                    strokeLinecap="round"
                    fill="none"
                  />
                </svg>
              </span>
            </motion.div>
          ) : null}
        </AnimatePresence>,
        document.body,
      )}
    </>
  );
}
