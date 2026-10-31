import React from "react";
import { createRoot } from "react-dom/client";
import {
  Background,
  BackgroundVariant,
  ControlButton,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  useNodesState,
} from "@xyflow/react";
import { KeyRound, Link2, Maximize, Waypoints } from "lucide-react";

const DATA = JSON.parse(
  document.getElementById("etlalchemy-diagram").textContent,
);
const h = React.createElement;

/**
 * The smallest zoom the first fit is allowed to use.
 *
 * Unbounded, a diagram taller than the frame is fitted by shrinking it until
 * nothing can be read; fitting to this floor keeps the boxes legible, and the
 * reader can zoom further out with the wheel, down to the canvas minimum.
 */
const FIT_ZOOM = 0.5;
const CANVAS_MIN_ZOOM = 0.2;
const ALIGN_DELAY = 450;
const VERTICAL = DATA.direction === "vertical";
const POSITIONS = VERTICAL
  ? { source: Position.Bottom, target: Position.Top }
  : { source: Position.Right, target: Position.Left };

const Over = React.createContext({});

/**
 * What the line under the pointer joins.
 *
 * A card rather than a label on the line: the line has a name, two sides, and
 * the columns those sides are joined by, and a picture with twelve lines has no
 * room to print any of it beside them. The card follows the pointer, because
 * that is where the reader is already looking.
 */
function RelationshipCard({ edge, at }) {
  const pairs = Math.max(
    edge.source_columns.length,
    edge.target_columns.length,
  );
  const rows = [];

  for (let index = 0; index < pairs; index += 1) {
    rows.push([
      edge.source_columns[index] || "",
      edge.target_columns[index] || "",
    ]);
  }

  const flipX = at.left;
  const flipY = at.above;

  return h("div", {
    className: "ea-pop",
    style: {
      left: flipX ? Math.max(8, at.x - 268) : at.x + 16,
      top: flipY ? Math.max(8, at.y - 146) : at.y + 16,
    },
  },
    h("div", { className: "ea-pop-head" },
      h("span", { className: "ea-pop-name" }, edge.name),
      h("span", { className: "ea-pop-mark" }, edge.mark)),
    h("div", { className: "ea-pop-sides" },
      h("span", null, edge.source_name),
      h("span", { className: "ea-pop-arrow" }, "\u2192"),
      h("span", null, edge.target_name)),
    h("ul", { className: "ea-pop-keys" },
      rows.map(([source, target]) => h("li", { key: source + ">" + target },
        h("span", { className: "ea-pop-col" }, source),
        h("span", { className: "ea-pop-arrow" }, "\u2192"),
        h("span", { className: "ea-pop-col" }, target)))),
    h("div", { className: "ea-pop-foot" },
      h("span", null, "priority " + edge.priority),
      edge.both ? h("span", null, "filters both ways") : null));
}


/**
 * One row of a box: the line it is joined by, its name, the key it is read by,
 * and its type.
 *
 * The key stands beside the name rather than at the head of the row, because
 * what a reader reads first is the column and what it holds; the marks say
 * what the model reads it for, which is a second question about the same row.
 */
function ColumnRow({ column, lifted }) {
  return h(
    "li",
    { className: lifted ? "ea-row ea-row--lifted" : "ea-row" },
    h(
      "span",
      { className: "ea-slot" },
      column.joined
        ? h(Link2, {
          size: 12,
          className: "ea-icon",
          role: "img",
          "aria-label": "joined by a relationship",
        })
        : null,
    ),
    h("span", { className: "ea-col" }, column.name),
    column.pk
      ? h(KeyRound, {
        size: 12,
        className: "ea-icon ea-key",
        role: "img",
        "aria-label": "primary key",
      })
      : null,
    h("span", { className: "ea-type" }, column.type || ""),
  );
}

/**
 * One box: the entity's name and table, then its columns a row at a time, with
 * the ones a line under the pointer joins lifted to the head and marked.
 *
 * A row that moves is made to travel from where it stood, because a list that
 * is the same rows in another order is a list the browser never saw move, and
 * a reader looking at the list has to see which rows went where.
 */
function EntityBox({ id, data }) {
  const emphasis = React.useContext(Over);
  const joined = emphasis[id] || [];
  const columns = React.useMemo(() => {
    if (joined.length === 0) return data.columns;
    const lifted = joined
      .map((name) => data.columns.find((column) => column.name === name))
      .filter((column) => column !== undefined);
    const rest = data.columns.filter(
      (column) => joined.indexOf(column.name) < 0,
    );
    return lifted.concat(rest);
  }, [data.columns, joined]);

  const list = React.useRef(null);
  const stood = React.useRef(new Map());
  const running = React.useRef(new Map());
  const [below, setBelow] = React.useState(data.hiddenColumns);
  const pending = React.useRef(0);

  /**
   * Count the columns still under the fold of the list.
   *
   * The card holds every column but shows a window of them, so the bar under
   * the window is only honest while it is measured: it has to shrink as the
   * reader scrolls and empty when the last column arrives. The rows are read
   * against the window rather than against the scroll offset, because the
   * offset of a row is relative to the card and not to the window it moves in.
   */
  const measure = React.useCallback(() => {
    const element = list.current;
    if (element === null || pending.current !== 0) return;
    pending.current = window.requestAnimationFrame(() => {
      pending.current = 0;
      if (list.current !== element) return;
      const fold = element.getBoundingClientRect().bottom;
      let count = 0;
      Array.from(element.children).forEach((row) => {
        if (row.getBoundingClientRect().top >= fold) count += 1;
      });
      setBelow(count);
    });
  }, []);

  React.useEffect(
    () => () => window.cancelAnimationFrame(pending.current),
    [],
  );

  React.useLayoutEffect(() => {
    const element = list.current;
    if (element === null) return;
    running.current.forEach((animation) => animation.cancel());
    running.current.clear();
    const stands = new Map();
    Array.from(element.children).forEach((row, at) => {
      const column = columns[at];
      if (column === undefined) return;
      const place = row.offsetTop;
      stands.set(column.name, place);
      const before = stood.current.get(column.name);
      if (before === undefined || before === place) return;
      running.current.set(row, row.animate(
        [
          { transform: "translateY(" + (before - place) + "px)" },
          { transform: "none" },
        ],
        { duration: 160, easing: "cubic-bezier(0.2, 0, 0, 1)" },
      ));
    });
    stood.current = stands;
    measure();
  }, [columns, measure]);

  const over = joined.length > 0;
  const handle = { isConnectable: false, className: "ea-handle" };

  const hiding = React.useRef(0);

  /**
   * Show the scrollbar while the list is scrolling, and only then.
   *
   * The bar says the card holds more columns than it shows, so a reader who
   * needs it is scrolling already. Leaving it on the card the rest of the time
   * puts a grey stripe down a picture that is mostly read, not scrolled.
   */
  const onScroll = React.useCallback((event) => {
    const element = event.currentTarget;
    element.classList.add("ea-list--scrolling");
    window.clearTimeout(hiding.current);
    hiding.current = window.setTimeout(
      () => element.classList.remove("ea-list--scrolling"),
      600,
    );
    measure();
  }, [measure]);

  return h("div", { className: over ? "ea-card ea-card--over" : "ea-card" },
    h(Handle, Object.assign({}, handle, {
      type: "target",
      position: POSITIONS.target,
    })),
    h("header", { className: "ea-head" },
      h("span", { className: "ea-name", title: data.name }, data.name),
      data.table === null
        ? null
        : h("span", { className: "ea-table", title: data.table }, data.table)),
    data.columns.length === 0
      ? h("p", { className: "ea-empty" }, "No column")
      : h("ul", {
        ref: list,
        className: "ea-list nowheel nodrag",
        onScroll: onScroll,
      }, columns.map((column) => h(ColumnRow, {
        key: column.name,
        column: column,
        lifted: joined.indexOf(column.name) >= 0,
      }))),
    data.hiddenColumns > 0
      ? h("p", { className: "ea-more" },
        below > 0 ? "- +" + below + " more columns" : "")
      : null,
    h(Handle, Object.assign({}, handle, {
      type: "source",
      position: POSITIONS.source,
    })));
}

const NODE_TYPES = { entity: EntityBox };
const EMPTY = {};
const HOVER_RADIUS = 14;

/**
 * The arrowhead an end of a line is drawn with.
 *
 * The name of the marker, not a reference to it: React Flow writes the
 * `url('#...')` around what it is given, so a reference handed in whole is a
 * reference to a reference, and an arrowhead that never resolves.
 *
 * One end or two is what the relationship means: a filter that propagates one
 * way leaves the line with one head, at the entity it propagates to, and a
 * filter that propagates both ways leaves it with a head at each end.
 */
function arrow(pointed) {
  return pointed ? "ea-arrow-accent" : "ea-arrow";
}
/**
 * How far a point lies from a line, measured against points along it.
 *
 * Two lines that join the same box end up drawn on top of each other near it,
 * so the line under the pointer is not always the line the reader means. What
 * they mean is the nearest one, and that is what this measures.
 */
function distanceTo(path, point) {
  const length = path.getTotalLength();
  const steps = Math.max(8, Math.ceil(length / 8));
  let best = Infinity;
  for (let index = 0; index <= steps; index += 1) {
    const at = path.getPointAtLength((length * index) / steps);
    const dx = at.x - point.x;
    const dy = at.y - point.y;
    const distance = Math.sqrt(dx * dx + dy * dy);
    if (distance < best) best = distance;
  }
  return best;
}

/**
 * Line the head of the picture up with the head of the view.
 *
 * ``fitView`` centres what it fits, so a diagram that needs less than
 * ``FIT_ZOOM`` is clamped and then centred, and both ends fall outside the
 * frame. When the fit is clamped the picture is realigned to its topmost box
 * instead, so a tall diagram is read from its head down.
 */
function alignToTop(flow) {
  try {
    const view = flow.getViewport();
    if (Math.abs(view.zoom - FIT_ZOOM) > 0.001) return;
    const nodes = flow.getNodes();
    if (nodes.length === 0) return;
    const top = Math.min(...nodes.map((node) => node.position.y));
    flow.setViewport({ x: view.x, y: 16 - top * view.zoom, zoom: view.zoom });
  } catch (error) {
    // A canvas that cannot be realigned is still a canvas worth drawing.
  }
}

function App() {
  const [over, setOver] = React.useState(null);
  const [at, setAt] = React.useState({ x: 0, y: 0, left: false, above: false });
  const [flow, setFlow] = React.useState(null);
  const canvas = React.useRef(null);
  const [nodes, setNodes, onNodesChange] = useNodesState(DATA.nodes.map((node) => ({
    id: node.id,
    type: "entity",
    position: { x: node.x, y: node.y },
    data: node,
    style: { width: node.width, height: node.height },
    sourcePosition: POSITIONS.source,
    targetPosition: POSITIONS.target,
  })));

  const emphasis = React.useMemo(() => {
    const edge = DATA.edges.find((item) => item.id === over);
    if (edge === undefined) return EMPTY;
    const found = {};
    found[edge.source] = (found[edge.source] || []).concat(edge.source_columns);
    found[edge.target] = (found[edge.target] || []).concat(edge.target_columns);
    return found;
  }, [over]);

  const pointed = React.useMemo(
    () => DATA.edges.find((item) => item.id === over) || null,
    [over],
  );

  const edges = React.useMemo(() => DATA.edges.map((edge) => {
    const pointed = over === edge.id;
    return {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      type: "smoothstep",
      label: edge.mark,
      markerEnd: arrow(pointed),
      markerStart: edge.both ? arrow(pointed) : undefined,
      style: {
        stroke: pointed ? "var(--ea-accent)" : "var(--ea-edge)",
        strokeWidth: pointed ? 2 : 1.5,
      },
      labelStyle: { fill: "var(--ea-on-accent)", fontSize: 10 },
      labelBgStyle: {
        fill: pointed ? "var(--ea-accent)" : "var(--ea-edge)",
      },
      labelBgPadding: [5, 1],
      labelBgBorderRadius: 4,
      // Where the line steps across: between the two rows for a join of two
      // neighbouring rows, and right after leaving its box for a join that
      // skips a row, so that row is not drawn over the line.
      pathOptions: { stepPosition: edge.step },
      zIndex: pointed ? 1 : 0,
      interactionWidth: 24,
    };
  }), [over]);

  React.useEffect(() => {
    const element = canvas.current;
    if (element === null || flow === null) return undefined;
    const onMove = (event) => {
      const point = flow.screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });
      const radius = HOVER_RADIUS / flow.getZoom();
      let nearest = null;
      let best = radius;
      for (const edge of DATA.edges) {
        const path = element.querySelector(
          '.react-flow__edge[data-id="' + edge.id + '"] .react-flow__edge-path',
        );
        if (path === null) continue;
        const distance = distanceTo(path, point);
        if (distance < best) {
          best = distance;
          nearest = edge.id;
        }
      }
      if (nearest !== null) {
        const box = element.getBoundingClientRect();
        setAt({
          x: event.clientX - box.left,
          y: event.clientY - box.top,
          left: event.clientX - box.left > box.width - 280,
          above: event.clientY - box.top > box.height - 160,
        });
      }
      setOver((current) => (current === nearest ? current : nearest));
    };
    const onLeave = () => setOver(null);
    element.addEventListener("mousemove", onMove);
    element.addEventListener("mouseleave", onLeave);
    return () => {
      element.removeEventListener("mousemove", onMove);
      element.removeEventListener("mouseleave", onLeave);
    };
  }, [flow]);

  /**
   * Put every box back where the layout put it.
   *
   * Where a box stands is decided once, where the columns and the joins are
   * read, and it is sent to the page as the place of every box. Dragging moves
   * one box without moving anything else, so laying out again is reading those
   * places once more. Laying the picture out here as well would be the same
   * picture drawn by two algorithms, and the two would drift apart.
   */
  const layOut = React.useCallback(() => {
    setNodes((current) => {
      const place = new Map(DATA.nodes.map((node) => [node.id, node]));
      document.body.classList.add("ea-laying");
      window.setTimeout(() => document.body.classList.remove("ea-laying"), 450);
      return current.map((node) => {
        const spot = place.get(node.id);
        if (spot === undefined) return node;
        return Object.assign({}, node, { position: { x: spot.x, y: spot.y } });
      });
    });
  }, [setNodes]);

  const fit = React.useCallback(() => {
    if (flow === null) return;
    flow.fitView({ padding: 0.2, duration: 400, minZoom: FIT_ZOOM });
    window.setTimeout(() => alignToTop(flow), ALIGN_DELAY);
  }, [flow]);

  /**
   * The canvas is up: the still picture that was drawn for a reader without
   * one has done its job.
   *
   * The still picture is what stays on the page when the canvas cannot be
   * drawn — a page that fails before this point keeps it rather than showing
   * an empty frame.
   */
  const ready = React.useCallback((instance) => {
    setFlow(instance);
    const fallback = document.getElementById("etlalchemy-fallback");
    if (fallback !== null) fallback.remove();
    window.setTimeout(() => alignToTop(instance), ALIGN_DELAY);
  }, []);

  return h(Over.Provider, { value: emphasis },
    h("div", { className: "ea-shell" },
      DATA.title === null ? null : h("div", { className: "ea-title" }, DATA.title),
      h("div", { className: "ea-canvas", ref: canvas },
        h(ReactFlow, {
          nodes: nodes,
          edges: edges,
          nodeTypes: NODE_TYPES,
          onNodesChange: onNodesChange,
          onInit: ready,
          fitView: true,
          fitViewOptions: { padding: 0.2, duration: 400, minZoom: FIT_ZOOM },
          minZoom: CANVAS_MIN_ZOOM,
          maxZoom: 1.5,
          nodesConnectable: false,
          proOptions: { hideAttribution: true },
        },
          h(Background, { variant: BackgroundVariant.Dots, gap: 18, size: 1 }),
          h(Controls, { showInteractive: false, showFitView: false },
            h(ControlButton, {
              className: "ea-control",
              onClick: layOut,
              title: "Lay every box out along the joins",
              "aria-label": "Auto layout",
            }, h(Waypoints, { size: 12 })),
            h(ControlButton, {
              className: "ea-control",
              onClick: fit,
              title: "Fit the picture to the view",
              "aria-label": "Fit view",
            }, h(Maximize, { size: 12 }))),
          h(MiniMap, { pannable: true, zoomable: true })),
        pointed === null ? null : h(RelationshipCard, { edge: pointed, at: at }))));
}

/**
 * Whether the reader is reading a light screen or a dark one.
 *
 * A notebook draws this page in a frame of its own, so the colour scheme of
 * the page around it is asked for first — that is the theme the reader chose —
 * and the system preference is what answers when the frame is another origin
 * and cannot be read. This is only asked when the picture was asked to follow
 * the reader; a page drawn light or dark already says so on its own element.
 */
function detectTheme() {
  try {
    const body = window.parent.document.body;
    if (body !== null) {
      const classes = body.classList;
      if (classes.contains("vscode-dark")) return "dark";
      if (classes.contains("vscode-high-contrast")) return "dark";
      const light = body.getAttribute("data-jp-theme-light");
      if (light === "false") return "dark";
      if (light === "true") return "light";
    }
  } catch (error) {
    // Another origin: the media query below is the answer.
  }
  const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  return dark ? "dark" : "light";
}

if (DATA.theme === "auto") {
  document.documentElement.dataset.theme = detectTheme();
}
createRoot(document.getElementById("etlalchemy-canvas")).render(h(App));
