# ETLAlchemy 前端

ETLAlchemy 的单页应用（SPA），覆盖数据目录、语义模型、业务术语、数据摄取、讨论与 IAM 六个域。

技术栈：Vite + React 19 + TypeScript（`strict`）+ TailwindCSS v4 + TanStack Query/Table +
zustand + react-hook-form + zod + axios + `@xyflow/react`。没有 UI 组件库，所有组件自研。

## 快速开始

```bash
# 1. 后端（仓库根目录）
docker compose -f docker/docker-compose.yml up -d --wait
uv run etla server                       # http://localhost:8000

# 2. 首个系统管理员（没有 HTTP 接口，只能用 CLI；密码从隐藏提示读取）
printf 'Passw0rd!\nPassw0rd!\n' | uv run etla iam bootstrap admin --email you@example.com

# 3. 前端
cd frontend
pnpm install
pnpm dev                                 # http://localhost:5173
```

开发期 Vite 只把 `/api` 和 `/mcp` 代理到 `http://localhost:8000`，因此浏览器只看到一个
origin，不需要 CORS。所有业务请求都在 `/api` 前缀下（axios 的 `baseURL` 为 `/api`，也可用
构建期变量 `VITE_API_BASE` 覆盖），SPA 自己的路由（`/iam/users`、`/agent` 等）与 API 路径
不再重叠，刷新任意前端路由都会回落到 `index.html`。生产环境（包括 Databricks Apps）由
FastAPI 同时提供 `dist/ui` 和 `/api`，同源，运行时不需要任何代理。

## 命令

| 命令                                | 作用                                                |
| ----------------------------------- | --------------------------------------------------- |
| `pnpm dev`                          | 启动开发服务器（5173，带 proxy）                    |
| `pnpm build`                        | `tsc --noEmit` + 生产构建（输出到根目录 `dist/ui`） |
| `pnpm typecheck`                    | 只做类型检查                                        |
| `pnpm lint`                         | ESLint（含 FSD 分层规则）                           |
| `pnpm format` / `pnpm format:check` | Prettier 写入 / 校验                                |
| `pnpm test` / `pnpm test:watch`     | Vitest 单元测试                                     |
| `pnpm e2e`                          | Playwright 端到端（重建测试库）                     |
| `pnpm e2e:reset`                    | 只重建 `etlalchemy_test` 数据库                     |

编辑器：`.vscode/settings.json` 已配置保存时用 Prettier 格式化 TypeScript/TSX，并执行
ESLint 自动修复；推荐插件见 `.vscode/extensions.json`。

构建产物统一输出到仓库根目录 `dist/ui`（`vite.config.ts` 的 `build.outDir`，配合
`emptyOutDir` 清空旧文件），`frontend/` 下不再生成 `dist`；根目录的 `dist/` 已被
`.gitignore` 忽略，发布时直接取 `dist/ui` 这一份静态文件即可。

## 目录与分层（Feature-Sliced Design）

```
src/
├── app/        # providers、路由、布局、全局样式
├── pages/      # 路由页面，只做组合
├── widgets/    # 跨页面组合块（catalog-explorer、term-tree、field-table、comment-drawers…）
├── features/   # 单个用户动作（create/change/discard、comment-threads…）及其 mutation
├── entities/   # zod schema、类型、查询 hook、key 工厂、展示组件（含 comment 的回复树）
└── shared/     # api 客户端、UI 基础组件、工具函数、导航配置
```

规则：`app → pages → widgets → features → entities → shared` 单向依赖，同层 slice 之间不互相
导入。跨 slice 一律用 `@/` 别名，切片内部用相对路径；`no-restricted-imports` 在 ESLint 中按
层拦截（例如 `shared` 不得导入 `@/features/*`、`@/entities/*`）。

每个 slice 只有一个 `index.ts` 出口，显式导出；不使用 `export *`，不使用默认导出（页面组件
除外，用于路由懒加载）。

## 数据目录工作区（左树 + 右详情）

`/api/catalog` 是唯一的数据目录工作区，路由在 `app/routes/router.tsx` 中嵌套：

| 路径                                                | 右侧面板                                                 |
| --------------------------------------------------- | -------------------------------------------------------- |
| `/api/catalog`                                          | Catalog 列表（列表 + New catalog）                       |
| `/api/catalog/:catalogId`                               | Catalog 详情：`Schemas` / `Description` / `Linked terms` |
| `/api/catalog/:catalogId/schemas/:schema`               | Schema 详情：`Tables` / `Description` / `Linked terms`   |
| `/api/catalog/:catalogId/schemas/:schema/tables/:table` | Table 详情：`Fields` / `Description` / `Linked terms`    |
| `.../tables/:table/columns/:column`                 | Column 详情：Linked terms + Settings                     |

- 四个详情页共用 `shared/ui/resource-detail-layout.tsx` 的 `ResourceDetailLayout`：
  面包屑 → 大标题（`text-2xl font-bold`）→ 描述（空则浅灰斜体 `No description`）→ 元数据 Badge，
  右上角是统一的 `ActionIconButton` 图标组；`staggerChildren: 0.05` 让左侧元素从左滑入、按钮从右滑入。
  Tabs 内容包在 `bg-bg-canvas/40` 的浅灰圆角面里，切换用 `AnimatePresence mode="wait"` 淡出 + 微滑。
- 操作按钮通过 `shared/ui/action-icon-button.tsx` 统一：只有图标 + `Tooltip`，
  `whileHover={{ scale: 1.1 }}` / `whileTap={{ scale: 0.9 }}`；新建保留主题黄文字按钮，
  删除前用 `ActionIconDivider`（`w-px h-4`）与普通操作用竖线隔开，hover 变红。
- `shared/ui/tabs.tsx` 的选中底线是 `motion.span layoutId`（每个 Tabs 用 `useId()` 隔离），
  切换时从旧位置滑到新位置，不再靠 CSS 边框跳动。
- 全局动效基调在 `app/providers/MotionProvider.tsx`：`MotionConfig` 统一
  `spring(300, 30)`，`reducedMotion="user"` 尊重系统设置：时长保持在 0.18–0.3s，克制、不拖沓。

- `app/layouts/CatalogLayout.tsx` 是工作区外壳：`flex h-full`，左侧 `w-80` 的
  `widgets/catalog-explorer`（与主界面同色 `bg-bg-surface` + `border-r` 分隔，独立滚动），右侧 `flex-1` 的白底
  详情面板，内层 `mx-auto w-full max-w-5xl p-8`。树放在布局路由里，切换节点只换 `<Outlet/>`，
  展开状态不会丢失。
- 树是递归组件（`widgets/catalog-explorer/ui/tree-row.tsx` + `CatalogExplorer.tsx`）：
  行高 `h-8`、`rounded-sm`，hover `bg-bg-hover`，选中 `bg-border-base` + `font-medium` +
  左侧 `border-l-2 border-brand`（始终保留 2px 透明边框，选中时只换颜色，不产生位移）。
  类型图标 `Database` / `Folder` / `Table2` / `Columns3`，箭头用 `motion` 旋转 0°↔90°，
  子级用 `AnimatePresence` + `height: auto` 展开。Catalog / Schema / Table 的子级按需加载
  （展开后才挂载 `useSchemas` / `useTables` / `useFields`），并跟随 URL 自动展开祖先节点；
  展开的 Table 会列出它的 Column（右侧显示 `data_type`），点击进入 Column 详情。
- 树顶有 `h-8` 的搜索框（`bg-bg-hover` 极浅底 + `border-border-base`，聚焦变 `focus:bg-bg-surface`
  `focus:border-brand focus:shadow-sm`，`Search` 图标）。搜索是**树形过滤（tree filtering）**，
  不是扁平列表：树的结构保持不变，只有命中自身或含有命中后代的节点留下，祖先节点即使不匹配也
  保留并自动展开（例如搜 `d` 时 `Customer 360 › service` 仍在，因为 `dim_segments` 命中），
  不相关的兄弟节点直接隐藏，行内命中片段用 `<mark>` 高亮（`TreeRow` 的 `highlight`）。
  Catalog / Schema / Table 用 `useQueries` 拉齐读模型后按名称过滤，**字段**在 200ms 防抖后走
  `GET /catalog/search?term=`（`useFieldSearch`，至少 2 个字符），命中的字段作为表格的子节点挂在
  原位置（只显示真正匹配的字段名，服务端顺带返回的同表其它字段不再列出），点它直达 Column 详情。
  搜索期间的展开状态是**临时**的（`collapsedNodes`，换关键词就清空），清空搜索框会回到搜索前的
  折叠/展开状态；搜索中的父节点只展开命中的子节点，展开一个只有字段命中的表格不会带出无关字段。
  没有命中时显示 `No resource matches “xyz”.`。
- 每行悬浮时右侧浮出两个纯图标按钮（无背景块，`gap-1`，从 `translate-x-1 + opacity-0`
  滑入）：`+`（Catalog 建 Schema、Schema 建 Table、Table 加字段）与 `···`（重命名/编辑、删除），
  默认 `text-text-disabled`，hover 只变 `text-text-primary`；删除当前节点后自动退回父级路由。
  行 hover 用 `bg-bg-hover-subtle`（`#fafafa`，暗色 `#2b2a29`），比常规 `bg-bg-hover` 更轻。
- Catalog 概览、Catalog 的 Schemas、Schema 的 Tables 统一用**列表**（`DataTable`），不再有卡片
  gallery；Catalog / Schema / Table 详情都是三个 Tab（`Schemas` / `Tables` / `Fields` +
  `Description` + `Linked terms`），第一个 Tab
  顶部是 `shared/ui/search-input.tsx`，在名称（Schema 还包含描述）里即时过滤，右侧显示 `n of m`。
- 描述不再是摘要区的一行文本：Catalog / Schema / Table 详情各有一个 `Description` Tab，
  用 `widgets/markdown-description` 包住术语页同款的 `MarkdownEditor`（默认渲染 GFM，点内容或右上角
  铅笔进入编辑，Save / Ctrl+⌘+Enter / 失焦提交）。Catalog 与 Schema 的修改走原有 PATCH；Table 的
  `description` 是本轮新增字段（聚合 `Table.Changed.description`、`catalog_tables.description`
  列 + 启动时自动补列），`TablePatch` 同时接受 name / description。
- 保存后立刻看到新内容：`MarkdownEditor` 的只读视图渲染本地 draft（服务端 `value` 变化时才覆盖它），
  因此 commit 的瞬间就换成新 markdown，不用等读模型；同时 `useChangeCatalog` / `useChangeSchema` /
  `useChangeTable` 在**只有描述变更**时 invalidate 各自的 detail key 并补一次
  `invalidateLater(..., detail)`（700ms，等待投影追平），只有真正重命名时才
  `removeQueries(detail)`，避免旧名字 404 或详情被无谓清空。
- `Linked terms` Tab 用 `features/term-actions` 的 `LinkedTermsList`：调用
  `GET /vocabulary/terms-for-target?target_id=&target_kind=&field_name=`，每行是颜色点 + 术语名（链到术语详情）
  - `path` + 状态徽标，右侧常驻灰色 `Unlink` 图标（hover 变红，走 `useUnlinkTerm`，成功后 toast
    `Link removed` 并自动刷新）；只有 draft 术语可解绑，其他状态按钮置灰并在 title 里说明原因。
    空态提示 `No linked terms`；对应的 hook 是 `entities/term` 的 `useTermsForTarget`。
    Catalog / Schema / Table 的 Tab 都只列**绑定到该对象本身**的术语：Table 不再提供字段下拉框，
    字段级术语在 Column 详情页用同一组件（`targetKind="field"`）查看；`field_name` 只在这类请求里非空。
- 列表头部自带 `Link term`：`features/term-actions/ui/TermLinkDialog.tsx` 打开
  `TermTree`（域 → 术语 → 子术语，带关键词检索的树形浏览器，见 `entities/term/model/term-tree.ts`）。
  检索框为空时只渲染域，展开某个域才 `GET /vocabulary/domains/{id}/terms`；一旦输入关键词就走
  `GET /vocabulary/search`（名称 / 定义 / 别名，跨全部域），命中项按路径补上祖先占位行，
  所以每个结果都能看到完整层级。非 draft 术语置灰不可选，因为链接本质是编辑术语。
  link / unlink 成功后都会立刻 `refetch()` 当前这份列表，`useLinkTerm` / `useUnlinkTerm` 还会
  `invalidateQueries(termKeys.all, refetchType: 'all')` 并补一次 `invalidateLater`，
  等读模型追平后再次拉取。
- `CatalogLayout` 用 `useOutlet()` + `AnimatePresence mode="wait"` 做路由切换：
  新页面 `opacity 0→1 / y 10→0` 入场，旧页面上移淡出（`exit={{ opacity: 0, y: -10 }}`）。
- 路径拼接与解析集中在 `shared/lib/catalog-routes.ts`
  （`catalogPath` / `schemaPath` / `tablePath` / `columnPath` / `parseCatalogPath`），Schema 与 Table 段既可用
  名称也可用 id。
- Table 详情的字段表格（`widgets/field-table`）里，字段名是指向 Column 详情的链接（`active:scale-95`
  做按压反馈）；行尾的 `Edit` / `···` 默认 `opacity-0 translate-x-1`，行 hover 或键盘聚焦时滑入，
  避免表格被操作按钮撑满。
- Column 详情页（`pages/column-detail`）把字段当成一等资源：摘要区展示类型（`info` 蓝底 Badge）、
  必填/可空与 `schema.table`；`Linked terms` 复用 `features/term-actions` 的 `LinkedTermsList`，`Settings` 展示
  类型、可空、默认值与表 id，并提供 Edit / Delete 图标操作。
- 页面自己负责滚动与内边距：`AppShell` 的白卡只提供 `rounded-xl bg-bg-surface shadow-sm`，
  普通页面用 `shared/ui/page-container.tsx`（`h-full overflow-y-auto p-8` + `max-w-7xl`）。

## Business terms 工作区（左树 + 右详情）

`/api/vocabulary` 与数据目录同架构，路由在 `app/routes/router.tsx` 中嵌套：

| 路径                                  | 右侧面板                                                               |
| ------------------------------------- | ---------------------------------------------------------------------- |
| `/api/vocabulary`                         | 域概览（域卡片网格 + New domain）                                      |
| `/api/vocabulary/:domainId`               | 域详情：描述 + 状态徽标筛选 + 术语表格                                 |
| `/api/vocabulary/:domainId/terms/:termId` | 术语详情：标题区（状态下拉 + 别名标签）+ Markdown 定义 + Catalog links |

- `app/layouts/VocabularyLayout.tsx`：左侧 `w-80` 的 `widgets/term-explorer`（`bg-bg-surface` +
  `border-r`，独立滚动），右侧 `flex-1` 白底 + `mx-auto w-full max-w-5xl p-8`，切换节点用
  `motion.div key={pathname}` 淡入；树放在布局路由里，展开状态不会丢失。
- 树是 域 ▸ 术语 ▸ 子术语：`TreeRow`（来自 `shared/ui/tree-row.tsx`，与数据目录共用）负责
  chevron 旋转、选中态、悬浮 `+`/`···`；域展开后才会挂 `useTerms(domainId)`，术语按 `parent_id`
  在客户端组树。术语行右侧的 1.5px 圆点表示状态（approved 绿 / draft 灰 / deprecated 橙）。
- URL 里带术语时，树的祖先链会自动展开（按 `parent_id` 回溯），因此深链与刷新都能定位到原位置。
- 术语支持 HTML5 拖拽改父级：拖到另一个术语 → 成为其子级，拖到域行或空白 → 回到顶层，
  统一调用 `POST .../terms/{id}/move`。
- 行悬浮菜单：域 → 重命名/编辑、删除；术语 → 重命名/编辑、移动、链接（仅 draft）、删除。
  编辑/移动/链接/删除需要完整的 `Term`（含 aliases、links），因此选中菜单项时才 `useTerm` 拉取。
  菜单组件是 `TermActionsMenu`（树和表格共用），`TreeRow` 通过 `actions` 插槽接收它。
- `shared/ui/dropdown-menu.tsx` 用 portal + `position: fixed` 渲染菜单，并按触发按钮位置
  自动翻转，因此不会在侧栏滚动容器或表格的 `overflow-x-auto` 里被裁剪。
- 树顶只有一行：搜索框 + `New domain` 的 `+`，不再有冗余的分区标题，标签过长时 `truncate`。
- 树顶搜索框输入≥1 个字符即切换到跨域扁平结果（`GET /vocabulary/search?q=`），
  每行显示术语名、状态、`域 / 术语路径`，命中别名时额外提示；无命中时提示检索范围
  （名称 / 定义 / 别名，跨全部域）。
- 每个术语可带一个颜色（后端 `#rrggbb`，空字符串表示不设色）：树与表格里的 `Tag` 图标、
  搜索结果与术语详情的色块都用它。颜色是元数据，草稿 / 已批准 / 已废弃都能改，
  只有已删除的术语拒绝。`shared/ui/color-picker.tsx` 提供色板 + 原生取色器 + hex 输入，
  `EditTermDialog` / `CreateTermDialog` 共用它。
- 父级选择不再手输路径：`entities/term/ui/TermPicker.tsx` 用域里的术语树做选择器
  （可折叠、可过滤、默认排除被移动的术语及其后代），`CreateTermDialog` 与
  `MoveTermDialog` 都用它；移动时未选新父级前 `Move` 按钮禁用，避免误把术语移到顶层。
- 术语详情页是「文档式」布局，没有卡片堆叠：顶部一行是面包屑 + `Term` 徽标 + 右上角
  `features/term-actions/ui/TermHeaderActions.tsx` 的纯图标按钮组（`Pencil` / `ArrowRightLeft` /
  `Link2` / `Trash2`，每个都包一层 `Tooltip` 显示名称；`Link` 前用 `w-px h-4` 竖线把删除操作
  隔开，`Delete` hover 变红）；第二行是 `ColorDot` + 标题 + 状态徽标（点击展开当前允许的流转，
  draft → Approve、approved → Reopen / Deprecate、deprecated → Reactivate，颜色灰 / 绿 / 红）；
  第三行是别名药丸 + `路径`。正文用 `Tabs` 分成 `Definition` 与 `Catalog links (n)` 两个面板。
- 标题前的颜色圆点本身是按钮（`shared/ui/popover.tsx` 的 `Popover` + `TermColorPicker`）：
  点开是色板 / 原生取色器 / hex 输入，选中即以 350ms 防抖 `PATCH` 颜色（拖动原生取色器不会
  一次一帧地发命令），Esc 或点外部关闭。
- 别名（`features/term-actions` 的 `AliasTags`）是圆角药丸，`X` 直接删除，末尾的 `+ Alias`
  幽灵药丸点下去原地变成输入框，回车添加；非 draft 状态只读。
- 定义用 Markdown（`react-markdown` + `remark-gfm`）：默认渲染富文本，点内容或右上角铅笔进入
  编辑器（工具栏：加粗 / 斜体 / 标题 / 行内代码 / 链接 / 列表 / 引用），点 Save、Ctrl/⌘+Enter
  或点击块外（blur）都会 `PATCH` 定义并立即渲染。表格里的定义预览用 `markdownToText` 压成单行。
- 详情内容整体收在居中的 `max-w-4xl` 里；Markdown 渲染区是极浅底（`bg-bg-hover-subtle/50`）+
  `border-border-base` 的圆角文档卡，标题 / 段落 / 列表有统一的上间距，引用块左侧是主题黄
  `border-brand` 竖线。铅笔按钮常驻右上角（60% 不透明度，hover 变实），一眼能看出可编辑。
  别名行以 `Aliases:` 前缀开头，标签用细边框药丸，`+ Alias` 用虚线边框区分；`Term` 徽标是
  无边框的小号大写灰字，不再抢面包屑的视觉重量。
- 颜色圆点（`shared/ui/color-dot.tsx`）同时出现在标题前、资源树节点、搜索结果和术语表格；
  没设颜色时渲染空心圆，保持对齐。
- Catalog 链接不再手输 kind + id：`features/term-actions/ui/CatalogObjectPicker.tsx` 里直接放一棵
  目录树（与实体表单共用 `entities/catalog/ui/CatalogObjectTree.tsx`），点任意一层——catalog /
  schema / table / field——即选中并回填 `target_kind` / `target_id` / `field_name`，对话框只显示
  只读摘要（无需先「下钻到某一层」再点确认）。
- 链接列表（`features/term-actions/ui/TermLinksList.tsx`）每行左侧是层级图标（`Database` /
  `Folder` / `Table2` / `Columns3`，对应 catalog / schema / table / field），`px-4 py-3`、
  hover `bg-bg-hover`；整行内容是指向对应页面的链接（catalog → `/api/catalog/:id`，schema / table /
  column 用后端解析出的 `catalog_id` / `schema_id` / `table_id` 拼深链，dangling 时不可点）；
  草稿术语在行尾常驻一个灰色 `Unlink` 图标（hover 变红），点击即
  `DELETE .../links?target_id=&target_kind=&field_name=` 并用 Toast 提示 `Link removed`。
  右侧只在 `dangling` 时显示红色徽标。「+ Link object」保持幽灵按钮。
- 选择器没有面包屑：整棵树一次展开到表，比逐层下钻少点几下。搜索是**树形过滤**（不是跨层扁平
  列表）：命中的 catalog / schema / table 留在原位，祖先保留并自动展开，不命中的兄弟隐藏，命中
  字符用 `<mark>` 高亮；列命中走 `GET /catalog/search-objects`（拿不到全量列，代价太高），命中
  的字段挂在自己的表下面，所以每条结果都带着完整路径。树区高度固定（`h-80`，实体表单里是
  `h-64`），检索/清空时对话框不会跟着伸缩；底部固定一行 “42 tables available / 23 tables match”。
- 右侧：面包屑用 `shared/ui/breadcrumbs.tsx`（父级术语可点，路径按 `useTerms` 反查 id），
  面包屑后面跟一个小号大写的灰字标签标明节点类型（`Domain` / `Term`），一眼看出当前层级；
  术语详情的 Catalog links 中 `catalog` 类型可直接跳到 `/api/catalog/:id`。
- 域详情的状态筛选是一排可点的徽标（不是 Tabs）：`All / Draft / Approved / Deprecated`
  各自带计数，选中态加深边框（`border-current` + `shadow-sm`），未选中态 `opacity-70`；
  approved 用 `success`、deprecated 用 `warning-ink`，与表格里的状态徽标同色系。
- 术语列表是 TanStack Table：`Term`（名称 + 父路径副标题）、`Definition`、`Status`（彩色徽标）、
  空表头 `Actions`（行级 `···` 菜单，与树里的菜单同一组件 `features/term-actions`）。
  列表接口只返回 `TermSummary`（无 aliases），因此别名只在术语详情页展示，避免 N+1 请求。
- 空列表不再画大灰框：`EmptyState` 新增 `plain`（去边框/底色），`DataTable` 新增 `emptyAction`，
  于是空的域显示居中的 `No terms yet` + 幽灵按钮 `Create the first term`。
- 路径助手在 `shared/lib/vocabulary-routes.ts`（`domainPath` / `termPath` / `parseVocabularyPath`），
  术语只能用 id 做 URL 段（`path` 含 `/`）。

## Ingestion 工作区（Data sources）

`/api/ingestion` 与目录/术语同构，只是没有左侧树：`app/layouts/IngestionLayout.tsx` 让页面从右向左
滑入（`initial={{ opacity: 0, x: 20 }}` → `0`，退出时反向），容器 `max-w-6xl p-8`。

| 路径                                  | 页面                                                           |
| ------------------------------------- | -------------------------------------------------------------- |
| `/api/ingestion`                          | 两个 Tab：`Connections`（卡片网格）+ `Import runs`（全局历史） |
| `/api/ingestion/:connectionId`            | 连接详情：`Import history` + `Settings`                        |
| `/api/ingestion/:connectionId/new-import` | 三步导入向导                                                   |

- 侧边栏只有一条 `Data sources` 入口（图标 `Earth`）；导入历史不再是独立页面，
  而是 `/api/ingestion` 的第二个 Tab，两个 Tab 都带计数，切换用 `AnimatePresence` 微淡入。
  搜索框与 `New connection` 只属于 `Connections` Tab。
- 一级界面的 `Connections` 是**卡片网格**（唯一保留卡片的列表）：`motion.li` 用
  `whileHover={{ y: -2 }}` + `hover:border-border-strong`，整卡是 `Link` 的
  `absolute inset-0` 覆盖层。搜索在名称 / kind / endpoint / 默认 catalog 上即时过滤。
- 连接详情复用 `ResourceDetailLayout`：面包屑 `Data sources / 名称`、kind 徽标 + endpoint，
  右上角图标组 `New import` / `Edit` / `Delete`。`Import history` 是默认 Tab，
  用 `widgets/import-run-table` 渲染：短 Run ID、目标 catalog（链到目录）、状态徽标、
  `Schemas / Tables / Fields` 计数（`schema_count / table_count / field_count`，
  即本次导入写入的 schema、表、字段数量）、`Started`（读模型 `created_at`）、`Details` 弹窗。
  空历史时工具栏不重复按钮，只在空态里放 `Start new import`。
- 状态徽标 `RunStatusBadge` 用 `key={status}` 重挂载，状态一变就播一次 spring 弹跳；
  `pending` 下面还有一条无限循环的黄色进度条。历史列表在有 `pending` 行时按
  `refetchInterval: 2000` 轮询（`useImportRuns(connectionId, true)`），状态变化后自动停止。
- `Settings` Tab 展示 kind / endpoint / 默认 catalog / 凭据（内联 token 只显示
  “encrypted at rest”，从不回显密文）、`options` 的等宽键值片，以及 `Edit` /
  `Rotate credential`（弹窗里可顺手 `Test connection`）/ `Test connection`。
- 新建连接表单字段与后端的映射：`Name` / `Source kind` / `Endpoint` / `Default catalog`、
  `Database` → `options.database`、`Username` → `options.user`、`Secret reference` →
  `credential_ref`、`Password`（kind 为 postgres 时这样标注，其他 kind 叫 `Inline token`）
  → 加密后写入的内联 token；两个凭据字段只能填一个。`Default catalog` 同时兼作
  postgres 的库名兜底（adapter 的顺序是 `options.database` → `default_catalog` → endpoint 里的库名）。
  `Edit connection` 只改元数据（含 `Database` / `Username`，会与已有 options 合并），
  密码永不在编辑表单里出现，只能用 `Rotate credential` 替换。
- `shared/ui/dialog.tsx` 的面板现在是 `max-h-[calc(100vh-2rem)]` 的纵向 flex：
  header / footer 固定，内容区 `overflow-y-auto`，所以字段多的表单也不会把按钮挤出屏幕。
- 向导三步（`pages/import-wizard`）：
  1. `Target catalog`（`GET /catalog/catalogs`）+ 可选 `Source catalog`（默认走连接配置）；
  2. 左树 `widgets/source-explorer` 逐层懒加载 `GET /ingestion/connections/{id}/inspect`
     （catalogs → schemas → tables），展开用 `motion.ul` 动画 `height: 0 → auto`，
     Loading 行带 `Loader2` 旋转；每个表前是自绘 checkbox（`whileTap={{ scale: 0.8 }}`），
     勾 schema 会级联选中它已加载的所有表（父节点显示 `mixed` 态）。右侧
     `ImportSelectionPanel` 按源 schema 分组，每组的 `Target schema` 输入框对应
     `schema_mapping`，已选表是带 `layout` 的 chip，可单个移除或 `Clear`；
  3. 确认步调用 `POST /ingestion/connections/{id}/plan` 预览：schema/table/field 三个大数字、
     新建清单、无法映射的类型（黄色警示块）与 warnings，然后 `Start import`。
- 后端 `POST /import` 是**同步**的：点 `Start import` 后按钮进入 loading，右下角浮出
  `ProgressPanel`（`y: 50 → 0` 进场，`Loader2` 无限旋转），文案用
  `AnimatePresence mode="wait"` 逐条淡入淡出（连接数据源 → 扫描目录 → 比对元数据 → 写入）。
  完成后跳回连接详情的 `Import history` 并弹 toast，记录本身是可轮询的 run 行。
- 实体层 `entities/ingestion`：`connectionSchema` / `importRunSchema` / `sourceInspectSchema` /
  `importPlanSchema`，`ingestionKeys` 覆盖 connections / connection / runs / run / inspect / plan；
  `startImport` 用 `LONG_RUNNING_TIMEOUT_MS`（0 = 不限时）。
- 路径助手在 `shared/lib/ingestion-routes.ts`（`ingestionPath` / `connectionPath` /
  `importWizardPath`）。

## Semantic models 工作区（Gallery → Explorer + Canvas + Tabs）

语义建模分两条路由：

| 路径                                                | 布局 | 左侧内容 | 页面                       |
| --------------------------------------------------- | ---- | -------- | -------------------------- |
| `/api/semantic`                                         | A    | 无       | 模型卡片画廊 + 搜索框      |
| `/api/semantic/:modelId?diagram=&entity=&relationship=` | B    | Explorer | Canvas + 底部 Diagram Tabs |

- **模式 A**（`app/layouts/SemanticLayout.tsx`）：单列 `max-w-6xl` 全宽画廊，
  `pages/semantic-list` 的 `PageHeader` 右侧是 `SearchInput` + `New model`；搜索在模型名称与
  描述上即时过滤，无命中时空态提示。**没有左侧模型列表**：模型的重命名 / 删除放在卡片右上角
  的 hover 菜单（`···`，`relative z-10` 盖在整卡 `Link` 之上）。新建模型后直接进入它的
  workspace。
- **模式 B**（`app/layouts/SemanticWorkspaceLayout.tsx`）：`grid` 上是 Explorer（固
  定 272px）+ Canvas，底部横跨整行的是 `widgets/semantic-diagram-tabs`
  （Excel sheet tabs 风格，`All` 固定在最左并带锁图标）。布局层先读
  `GET /semantic/models/{id}`：模型不存在就 `replace` 回 `/api/semantic` 并清掉
  `semantic:lastDiagram:{id}`，避免 Explorer / Tabs / Canvas 各发一次 404。
- **URL 即状态**：当前 diagram、选中的实体、选中的关系分别是
  `?diagram=` / `?entity=` / `?relationship=`，所以刷新、分享链接、前进后退都还原
  同一视图。`shared/lib/semantic-routes.ts` 提供 `modelPath` / `workspacePath` /
  `parseWorkspaceSearch`；web 页面只负责把缺省的 `diagram` 补成
  `localStorage` 记住的上一张图（`semantic:lastDiagram:{modelId}`）。
- **Explorer**（`widgets/semantic-explorer`）：顶部一行关键词搜索框（`SearchInput`），
  下方只有 `Entities` / `Relationships` 两个可折叠分组（**不再有 `Diagrams` 分组**，图的切换与
  管理都在底部 tab 栏），展开状态存 `semantic:explorerExpanded`。搜索同时过滤两组：实体按名称，
  关系按 `A → B` 摘要与 `entity.field` 配对文本，分组计数显示过滤后的条数。实体行**在当前图上**时
  右侧带一个绿色小圆点（`bg-success`，不在图上则什么也不显示）；名称过长时在剩余宽度内省略号截断
  （`shared/ui/tree-row.tsx` 的标签是 `min-w-0 truncate`），所以圆点与 hover 菜单的位置不会被长名字
  挤走。所有写操作（新建 / 编辑 / 删除 / “Add to this diagram”）都从各行的
  hover 菜单发起，弹窗复用 `features/semantic-*-actions`。
- **Canvas**（`widgets/semantic-canvas`，`@xyflow/react` 12）：节点位置来自读模型的
  `list_nodes`，边由“两端实体都在本图上的关系”推导，标签是
  `1:N · id → customer_id` 形式。拖动节点时只改本地 `useNodesState`，`onNodeDragStop`
  才发 `move_node`，并且不做即时 invalidate（否则投影未落地会让卡片弹回原位），只
  `invalidateLater(…, 1200)`。viewport（缩放/平移）按
  `semantic:viewport:{modelId}:{diagram}` 缓存在 localStorage，回到同一张图时用
  `defaultViewport` 恢复；第一次打开才 `fitView`（`maxZoom: 1`，避免两个实体被放到
  巨大比例）。
- **画布工具**：左下角是 React Flow 的原生控件组（缩放 +、−、Fit View），`Auto layout`
  （`LayoutGrid` 图标，`ControlButton`）作为第 4 个按钮挂在同一个 `<Controls>` 组里，样式与其它
  控件一致。点它用 **dagre**（`@dagrejs/dagre`，`model/layout.ts` 的 `layoutDiagram`）重排：按关系
  排成左右若干列（`rankdir: 'LR'`），列内间距用**实测卡片高度**而不是固定行高，所以展开到全部列的
  卡片不会压住下面那张。位置用 `requestAnimationFrame` 逐帧缓动（340ms，`easeOutCubic`，
  `prefers-reduced-motion` 时直接到位），因为节点 `transform` 由 React Flow 掌管，用 CSS transition
  会连拖动一起动画化；动画结束后再由 `useLayoutNodes` 串行发 `move_node` 落库（并发命令会撞同一个
  聚合的版本号），排完仍然可以继续拖动微调。
  **右下角**是 `MiniMap`（168×112，可拖拽/缩放，`attributionPosition="top-right"` 让出角落）。
- **布局随详情级别自动重排**：切换 `Table` / `Relations` / `All columns` 会改变每张卡的高度，旧网格
  必然不再合适，所以画布会在尺寸稳定后自动重排（`REFLOW_CHECK_INTERVAL` 100ms 轮询实测尺寸，连续
  2 次不变且已过 260ms 才动手，4s 后停止观察）。"All columns" 的字段是异步加载的，尺寸会二次变大，
  因此尺寸再次稳定时还会再排一次；每次重排都是动画过渡，而不是跳变。自动重排的落库延迟 1.5s
  （`saveLater`），只保存最终布局，中间态不会被写进模型。首屏也做一次**只在重叠时**修复，这样恢复
  的详情级别和上次保存的布局不一致时（比如上次是 Table、这次是 All）卡片不会互相覆盖。
  从读模型重建节点时保留已有卡片的本地坐标和测量值（投影落后于写入，直接采信会撤销刚做的布局或
  拖动）。
- **边的走向**：关系边跟着 dagre 的列序走，绝大多数是从左卡右侧连到右卡左侧，不会出现"右边表
  的右侧边绕回左边表的左侧边"的回头路。卡片的 `Handle` 在左右边中点，所以同一对实体之间若有多组
  字段引用，边会完全重合、标签叠在一起——`pathOptions.offset` 按第几条并行边递增
  （`18 + n * 16`），让它们扇形错开；`borderRadius: 16` 让拐角更圆。**边上只标基数**（`1:N` /
  `N:M` …，`cardinalityLabel`），字段配对放到 Inspector 里，标签不再挤在线上。**边的两种强调
  状态都用实线**（不加 `animated`，没有虚线/流动动画）：鼠标悬停时 2px 品牌色，选中时 2.5px
  品牌色且标签加粗。两者都把 `zIndex` 提到 `1000`——卡片默认在 `0`，所以被强调的边连带它的小标签
  会画在卡片之上，不会被别的卡片盖住（`.react-flow__edges` 没有 `transform`，不会自建层叠上下文，
  因此这个 z-index 生效）。
- **关系高亮**：悬停或选中一条关系时，`highlightId = hovered ?? selected`（悬停优先，指针移开
  就回到选中那条），两端实体的卡片加 `ring-2 ring-brand/25`，参与该关系的列
  （`model/highlight.ts` 的 `fieldsByEntity` 把 `from_refs`/`to_refs` 按实体合并去重）用
  `orderColumns` 移到列表最前面并用 `motion` 的 `layout` 做 FLIP 位移，行本身加 `bg-brand/15`
  品牌底色；所以列很多、列表需要滚动时，相关列也一定在可视区域顶部。
- **浮动 Inspector**：选中实体或关系时从画布右侧滑出 320px 面板（覆盖而不是挤压画布），
  `Esc` 或点空白画布关闭。它是**属性检查器**而不是详情页，按分区（`Section`）组织：
  - 实体：`CATALOG TABLE` 只显示 `schema.table` 链接（UUID 不再平铺，旁边一个复制按钮按需
    复制到剪贴板），`RELATIONSHIPS (n)` 渲染成可点击卡片（带基数徽标，未激活的关系用虚线边框），
    点一下就切换画布上对应的那条边；标题旁 ✏️ 打开编辑实体弹窗，底部是
    `Add to this diagram` / `Remove from diagram` 与 `Delete`（二次确认）。
  - 关系：`STATUS` 区块直接给优先级数字框，输入即时生效（`PRIORITY_SAVE_DELAY` 600ms 防抖，
    失焦/回车立刻提交），草稿值决定 `Active` / `Inactive` 徽标与画布边的灰色虚线，无需弹窗；
    `FIELDS` 把每组字段配对渲染成卡片（`Entity.field` ⬇ `Entity.field`），复杂改动走
    `Edit fields…` 打开双栏弹窗；`CARDINALITY` / `FILTER DIRECTION` 是就地下拉框，`onChange`
    即保存。面板内的保存调用 `useChangeRelationship(..., { notify: false })`，不弹 toast，
    面板与画布本身就是反馈；底部只留 `Delete`。
- **Diagram Tabs**：单击切换（同时清空画布选中），双击打开重命名，**直接拖动 tab 调整顺序**
  （原生 HTML5 DnD：拖动中的 tab `opacity-50`、落点 `border-l-brand`；`All` 不可拖也不做落点，
  永远第一位），键盘上 `Alt+←/→` 也能左右移动。落盘时把手动图重新编号为 `1..n`，只对真正变化的
  行串行调用 `change_diagram_order`（`useReorderDiagrams` 先做乐观更新，失败回滚）；菜单里
  **不再有 `Set order`**。`+` 在右端，新建后 `order` 取 `max(order) + 1` 并直接切到新图；
  删除当前图后回到 `All`。
  样式是 Excel / VS Code 的 sheet tab：条带用 `bg-bg-canvas`，**没有底部黄线**——激活的 tab 是
  一块 `bg-bg-surface`（纯白）+ `rounded-t-md` 的“纸片”从灰色条带里升起，未激活的 tab 透明、
  只留一条 `border-t` 与画布分隔，hover 时整块（含菜单区）变 `bg-bg-hover`；文字左右各 16px、
  激活 500 字重。拖拽把手已去掉（整个 tab 就是拖拽热区），`···` 菜单绝对定位在右侧、
  只在 hover / focus / 激活时出现，因此常驻的 `All` 只有一个锁图标，其余 tab 默认只有文字。
- **关系编辑**：`features/semantic-relationship-actions/ui/RelationshipDialog.tsx` 是双栏字段
  编辑器（BI 风格）：左右各一栏（`From` / `To`，栏内可切实体、搜索字段），中间是交换按钮
  （`motion` 的 `layout` 让两栏对调位置，同时互换所有配对和基数；`one_to_many` 没有
  `many_to_one` 镜像值，所以只在下方提示复核）。先点一侧字段、再点另一侧即完成配对，
  **再点一次已配对字段就取消配对**；配对状态只由字段前的**序号标记**表示，不再有单独的
  mapping 列表。`from_refs` / `to_refs` 按位置成对提交；字段列表走
  `GET /catalog/tables/{table_id}/fields`（实体只存 `table_id`，这是为此新增的目录
  路由）。实体被关系引用时，编辑弹窗里的目录表选择器被锁住并说明原因（后端
  `EntityInUseError` 的前置对齐）。priority `-1` 表示关系未激活：编辑器里状态变灰，
  画布上该边画成灰色虚线，悬停时底部提示"不参与筛选传播"。
- **实体表单的表选择**：`New entity` / `Edit entity` 里除了名称，目录表不再用扁平搜索列表挑，
  而是复用数据目录左侧那棵资源树（`entities/catalog/ui/CatalogObjectTree.tsx`，术语的
  「Link object」弹窗也用同一棵树，只是 `selectable` 放开到四层）：Catalog → Schema → Table 的
  层级、搜索框（`model/object-tree.ts` 的 `filterCatalogTree` 保留命中祖先、隐藏
  不命中兄弟、层级不变，命中字符用 `<mark>` 高亮，`countTables` 给出 “42 tables available / 2
  tables match”）。整棵树一次加载（几十张表），所以过滤是本地的、无需输入长度门槛；树区高度固定
  （`h-64`），结果多少都不改变弹窗高度；选中一张表后树收成 `catalog / schema / table` 芯片 +
  `Change` 按钮，实体被关系引用时芯片只读。
- **卡片上的表 URI**：实体卡片第二行不再显示 `table <id 前 8 位>`，而是用
  `GET /catalog/tables/{table_id}` 解析出 `schema.table`（如 `raw.crm_accounts`、
  `mart.fct_orders`），渲染成 `<a target="_blank" rel="noreferrer">`，点一下就在新窗口打开
  该表的目录详情页；`nodrag nopan` 让链接不触发节点拖动/画布平移，`stopPropagation` 避免同时
  选中节点。解析中回退成短 id。浮动 Inspector 的 `Catalog table` 也改成同一个链接，并在下面保留
  完整 id。
- **卡片信息密度**：画布 header 右上角是分段控件 `Table` / `Relations` / `All columns`
  （`widgets/semantic-canvas/ui/DetailLevelSwitch.tsx`，选中项用 `motion` 的 `layoutId` 滑块）。
  `Table` 只显示实体名 + `schema.table`；`Relations` 追加该实体被关系引用的列（由前端关系集合推导，
  不额外请求）；`All columns` 追加目录表的全部字段（`GET /catalog/tables/{id}/fields`，只在这一档
  才发请求）。选择存 `semantic:entityDetailLevel`，刷新后保持。卡片展开/收起用测高 +
  `motion` 高度动画：`height: auto` 无法插值，所以测量内层容器的 `offsetHeight` 作为目标，
  从 `Relations` 切到 `All columns` 时先保留旧行、等字段到了再长高，避免“先塌后张”。
  **列表最多显示若干行**（`MAX_VISIBLE_COLUMNS`，行距 18px），超过就在列表内部滚动
  （`maxHeight` + `overflow-y-auto` + `nowheel`，`nowheel` 保证滚轮滚列表而不是缩放画布），
  所以“全列”视图的卡片高度有上限，自动布局也不会被超高的卡片撑开。滚动条是**隐藏**的
  （`scrollbarWidth: none` + `[&::-webkit-scrollbar]:hidden`），滚动区域与卡片同宽、不占布局，
  内容被截断本身就是“还有更多”的提示。
- 读模型是最终一致：重命名实体会同时改写关系引用和节点键，所以 `useChangeEntity`
  一并失效 entities / relationships / nodes，并各补一次 `invalidateLater`。

## 讨论（Comments / Discussions）

讨论挂在**任意可寻址对象**上：后端按 `target_type` + `target_id`（UUID）定位，所以前端只传
`{ type, id, label }`（`entities/comment/model/target.ts` 的 `CommentTarget`）。**实体（entity）
与字段（field）在后端不是 UUID 寻址的**，因此画布实体卡片的讨论落在整个模型上
（`target_type=semantic_model`），字段没有讨论入口。

- **数据层**：`entities/comment`（`GET/POST /comments/threads`、`POST .../resolved`、
  `PATCH/DELETE comments`、`GET /comments/threads/{id}`）。`list_threads` 支持
  `target_type` / `target_id` / `author_user_id` / `mention_user_id` / `status`，前端
  `useThreads(query)` 直接把整个过滤条件放进 query key。标题与首条评论一起创建；列表行只带
  `comment_count`，评论体按需在展开时才 `GET /comments/threads/{id}`（一张卡片一次请求，而不是
  每行一次）。
- **回复树**：`buildCommentTree`（`entities/comment/model/tree.ts`）按 `parent_comment_id`
  组装，顺序即创建顺序；父评论缺失或出现在子评论之后时该行成为根，因此坏数据不会形成环。
  缩进用 `indentFor(depth)` 夹到 4 层，更深的回复同层显示。
- **面板**：`widgets/comment-drawers` 在 `AppShell` 里只挂一次，`features/comment-threads/model/store.ts`
  的 zustand store 负责 `openPanel(target)` / `openInbox()`，任何页面、树节点或 Inspector 只需
  调 `openComments(target)`。抽屉标题是**可点击的对象名**（`TARGET_NOUNS[type] + 名称` 链接）：
  入口自己带 `href`，来自 Inbox 时用 `GET /comments/targets/{type}/{id}` 现查名字，再交给
  `targetHref` 用路由助手拼链接（后端只回 id，URL 只有前端知道）。面板内是 `Open` / `Resolved` 两个 Tab（带计数）、线程卡片列表
  与**固定在底部的编辑器**（可选标题、`⌘↵` 发送）。`CommentPanelBody` 自带滚动区，抽屉变矮时
  列表用 `min-h-40` 保底，超出部分交给抽屉滚动。
- **@提及**：输入 `@` 弹出下拉（`GET /iam/users/search?term=`，最多 6 条，方向键 + Enter 选择），
  插入的是 `@显示名` 文本；提交时 `resolveMentions(body, picks)` 从正文里反查被提及的用户 id
  （上限 20），所以删掉 `@名字` 也就撤销了提及。这条搜索路由只要会话、不要求系统管理员，普通用户
  也能看到下拉；`term` 不是必填，只打一个 `@` 就会请求一次（150ms 防抖）并列出前几名用户，输入后
  再用缓存结果本地收窄，所以不会每敲一个字母就发请求。作者名走 `GET /iam/users/{id}`（同样只要
  会话），每个 id 一次请求并被缓存。
- **卡片头部就是操作区**：`Resolve`（OPEN）或 `Reopen`（RESOLVED）与被收进图标按钮的 `Delete` 都在卡片
  标题行右侧，点击标题以外区域不会误触发折叠；卡片正文区只留阅读内容，不再有底部操作行。`Delete`
  只对 `isAdmin || 作者本人` 渲染（`Resolve` / `Reopen` 保持可见，后端还会按 target 权限放行或
  403）。`depth_warning` 返回时在编辑器上方显示黄色提示条，深回复的编辑器保持打开，方便读完建议再
  决定是否另开 Thread。
- **编辑器把提示交给 placeholder**：`Reply… (@ to mention, ⌘↵ to send)` / `Start a discussion about
X… (@ to mention, ⌘↵ to send)`，输入后自然消失，底部只留 `Add title` / `Cancel` / 发送按钮。
- **面板内的检索**：Tab 下面是一个关键词框，本地过滤当前 Tab 的列表，匹配线程标题、评论正文与作者
  名；评论正文只在**开始搜索后**才批量拉取（`useThreadDetails`，一次 `GET /comments/threads/{id}`
  每行），空闲时列表仍然只有一个请求。搜索在 `Resolved` Tab 同样生效，无命中时给出 `Nothing
matches`。
- **入口**：目录 / schema / 表详情页标题栏的 `Discuss`（`ActionIconButton` + 黄色计数徽标）、
  字段列表每行的 `Discuss this field`（hover 出现）、术语详情页的第三个 Tab、画布 Inspector 的
  `Properties` / `Discussion` Tab、以及顶栏 💬（全局 Inbox：`All open discussions` /
  `Started by me` / `Mentioning me`，点一行直接打开对应对象的讨论并展开该 Thread）。
- **字段与实体都能单独讨论**：目录字段和语义实体现在各有 `field_id` / `entity_id`（见下），
  `target_type` 增加了 `field` 与 `semantic_entity`。Inbox 只用 `target_type` + `target_id`，
  所以一次 `POST /comments/targets/lookup` 批量取回名字与路径（`Customer 360 / crm / contacts /
contact_id`），行尾再叠一个关键词框按标题 / 路径 / 类型过滤，输入即筛，不用再发请求。

## Agent 工作区（悬浮窗 + 全屏页）

Agent 有两个入口，共享同一个 zustand store（`entities/agent/model/store.ts` 的
`useAgentStore`：`conversations` / `activeConversationId` / `transcripts` / `widgetOpen`），
所以在悬浮窗里发的消息，展开成全屏页时已经在屏幕上，反之亦然。

| 入口   | 位置                                  | 说明                                                                           |
| ------ | ------------------------------------- | ------------------------------------------------------------------------------ |
| 全屏页 | `/api/agent`、`/api/agent/:conversationId`    | 左侧会话列表（260px，可折叠）+ 右侧对话区，挂在左侧主导航第一项 `Agent`        |
| 悬浮窗 | `AppShell` 里的 `AgentFloatingWidget` | 全局可拖拽的圆形按钮 + 弹出面板；在 `/api/agent*` 上自动隐藏，避免同一会话出现两份 |

悬浮窗挂在 `AppShell` 而不是 `App.tsx` 里与 `RouterProvider` 平级：它要"展开至全屏"就得
`useNavigate()`，而 `RouterProvider` 之外没有 router 上下文；`AppShell` 已经是所有登录后页面的
外层，效果与"全局组件"一致。

- **路由**：`/api/agent` 是"当前会话"，`/api/agent/:conversationId` 是深链；`params.conversationId`
  是 source of truth，选中会话时同步改写 URL，因此刷新不会丢上下文。深链指向已删除的会话
  （`GET .../messages` 回 404）时会清空选中并回到 `/api/agent`，并提示一句 `toast`。
- **流式传输**：`shared/api/sse.ts` 用 `fetch` 读 `text/event-stream`（`EventSource` 既不能
  带 JSON body 也不能带 `Authorization`），`parseSseBuffer` 负责跨 chunk 的帧切分、多行
  `data:` 合并与 `: ping` 注释丢弃；`entities/agent/model/events.ts` 的 `parseAgentEvent`
  把帧解码成事件，未知事件名或坏 JSON 返回 `null`（新服务端加事件不会打断旧客户端）。
- **归约**：`applyAgentEvent` 是纯函数，负责 token 累加、`tool.started`/`tool.finished`
  配对成一张卡片（服务端不给 `args_hash` 时按工具名配对）、`approval.required`
  追加卡片、`message.completed` 用 `final_answer` 覆盖正文并补上完成帧里才出现的审批、
  `done`/`error` 落终态。令牌只进 store，组件不接触协议细节。
- **思考与步骤折叠**：`llm.reasoning` 累加进 `message.reasoning`，同时按到达顺序记入
  `message.steps`（推理段与工具调用交替），折叠块里就是这个时间线。新一轮提问开始时
  消息是展开的，正文 token 到达也不折叠，整轮运行期间推理和工具调用都实时可见；只有
  `message.completed` 带着 `status: 'completed'` 时才把 `stepsCollapsed` 置为
  `true`（暂停等审批不算完成，恢复后由 `unfoldSteps` 重新展开并清掉该消息的手动折叠
  记录）。用户手动展开的意图存在 store 的 `collapsedOverrides[messageId]`，与消息分开
  存放，所以后续流式更新不会把它冲掉；`useStepsCollapsed(message)` 返回两者合成后的
  折叠状态。历史消息按"已完成即折叠"渲染。
- **每条消息只属于一个 run**：`transcript.run.streamingMessageId` 记住当前流写入的那条消息，
  事件里缺 `message_id` 或换了 id 都仍然写同一条；`beginRun` 只在新提问时清空它，
  审批恢复时保留。否则审批后的工具调用会各自生成一条消息，堆在最终回答后面。
- **渲染靠新对象**：reducer 原地修改 transcript，`applyEvent` 先用 `cloneTranscript` 复制再归约，
  这样 `useTranscript` 的引用才变，token / 思考 / 审批才会实时出现（否则只能刷新页面才看见）。
- **审批卡只在等待时出现**：`message.completed` 的 approvals 是整个 run 的列表，客户端只补
  "未知且仍在等待"的那条；`MessageList` 也只在 `run.status === 'awaiting_approval'` 时渲染
  `status === 'pending'` 的卡，所以决定之后不会残留卡片。暂停时服务端会发
  `message.completed` + `done{status: awaiting_approval}` 结束本条流，客户端不会一直"生成中"。
- **不会为同一个决定弹两次窗**：审批 id 由 `(run_id, tool, args_hash)`（同一轮里重复的同调用再加序号）
  派生，恢复 run 时重跑工具再问一次会用同一个 id，服务端写入是幂等的，因此不会冒出第二张卡。若卡片已经
  被决定（另一个标签页先点了，或恢复已经记下这次决定），服务端答 `409`
  `approval … is already approved|denied`：`decide` 会把它当成"已经解决"——丢掉这张卡并
  `settleRun`（不弹错误提示），随后的 `refresh` 用真实状态填回来。
- **多条待审批命令逐条询问**：一轮里模型要求多个破坏性工具时，服务端每次暂停只给出一张卡，
  决定后恢复 run，下一条才会发 `approval.required`（`ap-1` 标成 `approved` 留作记录，
  `ap-2` 才是新的 pending 卡）。所以界面上永远只有一张待办卡，断线重连后 `GET .../approvals`
  返回的也正好是这一张。`hydrateApprovals` 以服务端为准：服务端不再列出的 pending 卡会被丢掉
  （它已经被决定了），已决定的卡保留作记录——否则旧卡会以"待审批"的样子重新出现。
- **自动滚动**：`MessageList` 底部有一个哨兵节点，`shared/lib/scroll.ts::keepInView` 在
  正文/思考/工具卡增长时把容器滚到底；对话切换时直接跳到底。用户自己往上翻时不打扰
  （只有正在流式输出时才强制跟随）。页面和悬浮窗共用这一份实现。
- **资源读取也是工具卡**：`read_mcp_resource` 在服务端和普通工具一样发 `tool.started` /
  `tool.finished`，所以步骤折叠里出现的是一张卡片（抽屉里能看到 `{"uri": …}` 和结果预览），
  `resource.read` 同时把它记进消息的 sources 列表。刷新后卡片仍在，因为它落在消息 trace 里。
- **URN 链接**：回答里出现 `urn:catalog/<id>/schema/<id>/table/<id>`、
  `urn:vocabulary/<id>/term/<id>`、`urn:semantic/<id>/entity/<name>` 时，
  `shared/lib/urn.ts` 把它解析成站内路径，`shared/lib/remark-urn-links.ts` 作为 remark 插件
  只改文本节点（代码块、行内代码、已有链接都不碰），`shared/ui/markdown.tsx` 把站内链接渲染成
  react-router `Link`。正文里看到的是 `table 76fc724e…` 这样的短标签，悬停显示完整 URN，
  点击跳到对应页面。
- **悬浮窗也渲染 markdown**：`MessageList` 的 `AssistantBody` 在紧凑模式下仍是同一个
  `shared/ui/markdown.tsx`（只把字号收到 13px，表格/代码块在各自盒子里横向滚动），
  所以表格、代码块和 URN 链接在悬浮窗里同样可读；只有表格或代码块的回答额外给一个
  `Open full screen` 链接，不再把正文截成纯文本摘要。
- **悬浮窗路由上下文**：`shared/config/navigation.ts::describeLocationContext` 把当前路径拆成
  “`Data catalog › catalog crm › table contacts`” 这样的链，`locationContextNote` 再补上
  `Path: /catalog/...`。`Composer` 的 `contextNote` 作为请求字段 `page_context` 发给服务端
  （`RunRequest.page_context`，由 `_system_prompt` 拼进系统提示），不进用户消息正文、也不落库，
  所以浮窗开着浏览、随手提问时不必手打“我在看哪个表”，聊天记录里也不会多出一段路径；
  路径每次渲染都重算，随手换页面就换上下文。
- **悬浮窗形变**：点 icon 时 icon 同时淡出缩小（`aria-hidden` + `pointer-events: none`），
  面板以 icon 中心为 `transformOrigin` 从 0.15 缩放展开，两者不会同时显示；右上角的最小化
  按钮（`Minus`）把面板收回 icon，Escape 同样是"最小化"。`AnimatePresence` 常驻在 portal 里，
  所以关闭动画也会播完。
- **自动审批开关**：对话框右上角和全屏页的头部各有一个 `<span>auto-approve</span>` 开关（同一个
  `shared/ui/switch.tsx` `role="switch"`，共用 `useAgentStore.autoApprove`，状态存
  `etlalchemy.agent.auto-approve`），默认打开。开着时每条消息带 `auto_approve: true`，服务端对
  `require_approval` 的工具直接执行、不产生审批事件与卡片；`agent.tools.approval.default: deny`
  兜底拒绝的破坏性工具（例如只配了 `discard_*` 规则时的 `remove_diagram`）同样放行，
  只有规则里显式写的 `deny` 仍然拒绝。关掉后恢复逐条审批。
- **悬浮窗历史搜索**：历史 Popover 顶部有搜索框，用 `filterConversations` 按标题过滤（最多 20 条），
  无结果时提示 `No conversation matches that search.`；输入框里按 Escape 只关搜索，不关整个浮窗。
- **面板尺寸**：宽度下限是视口宽度的 25%（再兜底 320px），所以它永远不是一根窄条；默认 400×600。
  右下角的 grip 可拖拽宽高（指针捕获 + 视口夹紧，不会把面板推到屏幕外），尺寸存
  `etlalchemy.agent.panel-size`；窗口变小时自动夹回可视范围。
- **头部拖拽**：header 的空白区（标题所在的 `flex-1` 区域）是把手，`cursor-grab` /
  `active:cursor-grabbing`，按住即可移动面板，且不改动 icon 的位置；按钮区不参与拖拽。
- **不出现横向滚动条**：面板是 `fixed` 定位，不会撑出页面滚动；正文滚动容器（页面与浮窗各一处）
  都加了 `overflow-x-hidden`，长代码块和表格各自在内部横向滚动。
- **工具详情抽屉**：`ToolCallCard` 是按钮（`aria-haspopup="dialog"`），点击后由
  `MessageList` 的本地 state 打开 `ToolCallDrawer`；抽屉复用 `shared/ui/drawer.tsx`，
  展示脱敏后的参数 JSON 与截断后的结果预览。服务端的 `args_json` / `result_preview`
  同样落在消息 trace 里，刷新后内容不变。
- **耗时口径**：`model/timing.ts` 同时给两套值——`工具` 是各次调用 `durationMs` 之和，
  `总` 是首个事件到正文第一个 token 的墙钟（`streamStartedAt` / `answerStartedAt`，
  来自事件的 `timestamp`）；历史消息没有时间戳时不显示 `总`。
- **审批（HITL）**：暂停时 `message.completed.status = awaiting_approval` 且没有 `done`；
  `POST /agent/runs/{id}/approvals/{approval_id}:stream` 续流，事件继续写同一条
  assistant 消息。悬浮窗里是精简卡片（工具名 + 两个按钮），全屏页额外显示 digest 与策略原因；
  参数只以脱敏、截断后的预览形式离开服务端（`agent.tools.redact_argument_keys`），
  所以审批卡仍只展示 digest 与原因，完整参数在工具抽屉里。
- **停止生成**：`features/agent-chat/model/use-agent-chat.ts` 用 `AbortController` 中断读取，
  本地把该条消息标成 `interrupted`；服务端同样把 run 持久化成 `interrupted`。
- **会话列表**：`groupConversations` 按本地日历日分成 Today / Yesterday / Previous 7 Days /
  Older（空分组不渲染），`filterConversations` 做标题的本地搜索；hover 行的 `⋯` 打开
  重命名 / 删除。
- **悬浮窗定位**：位置存 `localStorage`（`etlalchemy.agent.widget-position`，读取时按视口夹取）；
  面板方向由 `shared/lib/floating-placement.ts::placePanel` 计算——顶部开向下、底部开向上、
  中间带开向侧边，最后再夹到视口内，所以拖到任何角落都不会出屏。没有引入
  `floating-ui`：规则只有三条且都有单元测试，与仓库既有 `DropdownMenu`/`Popover` 的
  自研定位保持一致。
- **配色**：`--color-agent-rail` / `--color-agent-panel` / `--color-agent-canvas`
  三层，暗色下是 `#181818` / `#1e1e1e` / `#252526`，与主导航形成深浅层次。
- **时间戳**：`shared/lib/date.ts` 统一走 `shared/lib/timestamp.ts::parseTimestamp`，
  没有时区的字符串按 UTC 解析（SQLite 的列会丢掉时区，Postgres 不会），否则东八区浏览器
  会把"刚刚"显示成"8 h ago"。

已知限制：

- SSE 重连（`Last-Event-ID`）没有实现；服务端的回放缓冲只在单进程内有效，客户端目前
  以 `GET .../messages` 的持久化历史兜底。审批卡不靠回放：`GET .../approvals` 返回仍在等待的
  决策，打开会话时（`hydrateApprovals`）补回，所以刷新不会丢卡。
- Mermaid 图表按普通代码块渲染（项目没有 mermaid 依赖），表格与代码高亮走
  `shared/ui/markdown.tsx`（`remark-gfm`）。

## 鉴权模型（与早期需求文档不同）

后端已经统一为 **Bearer Token**，请求里不再有 `session_id`：

- `POST /iam/auth/password`、`POST /iam/auth/api-key` 返回
  `{ access_token, session_id, identity_id, user_id, tenant_id, expires_at, refresh_at }`；
- 之后所有 `/api/iam/*`（除 `/auth/*`、`/bootstrap`）与 `/api/comments/*` 请求都带
  `Authorization: Bearer <access_token>`；`catalog`、`semantic`、`vocabulary`、`ingestion`
  目前免鉴权；
- `POST /iam/auth/refresh` 与 `POST /iam/auth/logout` 没有请求体，靠 bearer 识别会话；
- 当前会话用 `GET /iam/sessions/current`；
- 会话响应不含 `is_system_admin`，登录后额外调用 `GET /iam/users/{user_id}` 取得该标记。

`shared/api/client.ts` 统一注入 `Authorization` 和 `X-Request-ID`。token 由
`app/main.tsx` 通过 `bindAccessToken()` 注入，避免 `shared` 反向依赖 `entities`。

### 自动续期

每个会话响应都带 `refresh_at = expires_at - iam.session_refresh_lead_minutes`。提前量由后端
配置决定（`config.*.yaml`），前端只按 `refresh_at` 设置定时器静默调用 `/api/iam/auth/refresh`；
失败时清空会话，`RequireAuth` 会把用户送回登录页。

### token 存储

`access_token` 通过 zustand `persist` 存在 `localStorage`，以满足"刷新页面仍保持登录"。
这意味着任何能在页面里执行的脚本都能读到它。若安全要求提高，可改为 `sessionStorage`
（代价是刷新即掉登录）或由后端改用 httpOnly cookie。

## 环境与代理

- `VITE_` 前缀的环境变量可在 `src/shared/config` 中读取（当前 No. 需要）。
- 生产部署有两种方式：与 API 同源提供静态文件，或给后端配置
  `api.cors_origins`（YAML 列表；环境变量用 JSON 数组
  `ETLALCHEMY_API__CORS_ORIGINS='["https://app.example.com"]'`）。

## 阶段进度

| 阶段 | 内容                                                                             | 状态 |
| ---- | -------------------------------------------------------------------------------- | ---- |
| 0    | 后端配置面：`api.cors_origins`、`iam.session_refresh_lead_minutes`、`refresh_at` | ✅   |
| 1    | 地基：脚手架、Tailwind、FSD 分层、shared/api、shared/ui、路由、格式与 lint       | ✅   |
| 2    | 会话与 IAM 只读                                                                  | 🚧   |
| 3    | Catalog CRUD 与树形导航                                                          | ⬜   |
| 4    | Vocabulary 术语树与状态机                                                        | ⬜   |
| 5    | Comment 讨论组件                                                                 | ⬜   |
| 6    | Semantic 与 react-flow 画布                                                      | ✅   |
| 7    | Ingestion 连接与导入                                                             | ✅   |
| 8    | IAM 管理台                                                                       | ⬜   |
| 9    | 打磨与 Playwright E2E                                                            | ⬜   |

## 视觉规范（Power BI 风格）

`src/app/styles/index.css` 的 `@theme` 定义唯一色板，业务组件只允许使用语义化类名：

| 用途                         | 令牌                                                            | 类名                                                |
| ---------------------------- | --------------------------------------------------------------- | --------------------------------------------------- |
| 品牌黄 / 悬停 / 品牌上的文字 | `--color-brand` / `--color-brand-hover` / `--color-brand-text`  | `bg-brand` `hover:bg-brand-hover` `text-brand-text` |
| 可作文字的品牌黄             | `--color-brand-ink`（浅色下压深的品牌黄，暗色下即 `#f2c811`）   | `text-brand-ink`                                    |
| 画布 / 面板 / 悬停行         | `--color-bg-canvas` / `--color-bg-surface` / `--color-bg-hover` | `bg-bg-canvas` `bg-bg-surface` `hover:bg-bg-hover`  |
| 密集列表的极轻悬停           | `--color-bg-hover-subtle`                                       | `hover:bg-bg-hover-subtle`                          |
| 文字三级                     | `--color-text-primary/secondary/disabled`                       | `text-text-primary` 等                              |
| 边框（常规 / 强调）          | `--color-border-base` / `--color-border-strong`                 | `border-border-base` `border-border-strong`         |
| 状态                         | `--color-danger/success/warning`                                | `text-danger` `bg-success/10` 等                    |

第三方控件也要吃同一套令牌：`@xyflow/react` 自带一整套 `--xy-*` 变量并只通过 `colorMode`
切换明暗，本应用的主题是 `html[data-theme]`，所以在 `html[data-theme='dark']` 里把
`--xy-controls-button-background-color(-hover)` / `--xy-controls-button-color(-hover)` /
`--xy-controls-button-border-color` / `--xy-controls-box-shadow` /
`--xy-attribution-background-color` 映射到 `bg-surface` / `bg-hover` / `text-primary` /
`border-base`。不映射时缩放按钮是 `#fefefe` 底 + 继承来的浅色图标，整组看起来就是一条空白白条；
MiniMap 的底色、蒙版与节点色本来就通过组件 props（`style` 里的 `--xy-minimap-*`）给了，不受影响。

布局（上中下三层 + 悬浮卡片）：外层 `h-screen w-screen flex flex-col overflow-hidden bg-bg-canvas`；
顶栏 `h-14` 透明无边框（字标 + 居中搜索 + 右侧动作行）。字标 `shared/ui/brand.tsx` 是 20px
（`text-xl`）的纯排版锁定组：整体 `-skew-x-6` 制造前倾速度感，`ETL` 为
`font-black tracking-tighter text-text-primary`，`Alchemy` 为 `font-bold tracking-tight
text-text-primary`，仅首字母 `A` 使用 `text-brand-ink`；无背景块、无阴影、无图标，hover 只把整体
降到 `opacity-80`（200ms）。全局搜索框绝对居中（`absolute left-1/2 -translate-x-1/2 top-1/2 -translate-y-1/2 w-full max-w-lg`），白底细边 `bg-bg-surface border border-border-strong
shadow-sm`，聚焦时 `focus:border-brand focus:ring-2 focus:ring-brand/40`。
第二层 `flex flex-1 gap-4 overflow-hidden pr-4 pb-4 pt-2` 内是 64px 图标栏与主内容。

图标栏（`w-16`）固定宽度、不可折叠，与主内容卡片共边：外层无 `gap`，卡片四角统一 `rounded-xl`。
`nav` 是 `px-3 pt-5`，菜单项左右各留 12px，首项下移 20px —— 正好让首项的反向圆角从卡片 12px
圆角的终点开始，两者不打架。选中态是一块
`motion.span`（`layoutId="active-nav-indicator"`，`spring(400, 35)`），切换路由时从上一个图标平滑
滑到下一个；它是 `inset-y-1 left-0 right-[-22px] rounded-l-md border border-r-0 border-border-base
bg-bg-surface shadow-sm` 的标签页：上下各留 4px、左侧留 12px，右缘再向右溢出 10px 压过卡片的左边缘，
所以选中的白底与主面板连成一体。选中图标用 `text-brand-ink`（浅色下压深的品牌黄，暗色下即
`#f2c811`），未选中为 `text-text-secondary`；没有黄点、没有黄色边条。hover 显示深色 Tooltip 提示
名称。Discussions 是顶栏图标，IAM 管理台收进顶栏设置菜单（`ADMIN_NAV_ITEMS`）。

顶栏右侧动作行统一 36px（`size-9`，头像按钮 `h-9`），顺序为：Discussions 图标（`/api/comments`，
当前路由高亮）→ Settings 齿轮（仅系统管理员显示，Dropdown 内含 Users / Tenants /
Groups & permissions / Providers / Audit log，当前路由在对应分支时齿轮保持高亮）→ 深浅色切换 →
用户头像菜单。两个下拉共用 `MENU_PANEL`（白底、`rounded-md`、细边框、`shadow-md`）与 `MENU_MOTION`
（`opacity` + `y:-6 → 0`，150ms），同一时刻只会展开一个（`openMenu` 状态）。

主内容是一张悬浮白卡（`rounded-xl bg-bg-surface shadow-sm`），滚动与内边距由页面自己负责：普通
页面用 `shared/ui/page-container.tsx`（`h-full overflow-y-auto p-8` + `max-w-7xl`），数据目录用
`app/layouts/CatalogLayout.tsx` 的左右分栏。

组件：主按钮 `bg-brand text-brand-text h-9 rounded-md`；次级动作用 `variant="secondary"`（透明背景 +
`border border-transparent`，hover 才出现 `hover:border-border-base hover:bg-bg-hover`）和
`variant="danger-ghost"`（hover 变 `hover:bg-danger/10 hover:text-danger`），因此标题区的
Rename/Delete 看起来像轻量图标而不是方框；`index.css` 的 base 层给所有 `button:not(:disabled)`、
`[role='menuitem']`、`[role='tab']` 加上 `cursor: pointer`，保证一律是手型光标；
输入框 `h-9 border-border-strong focus:border-brand`；
表格行高 `h-10`、表头 `bg-bg-canvas text-xs font-semibold`、行分隔 `border-b border-border-base`；
弹窗遮罩 `bg-black/20 backdrop-blur-sm`，Header/Footer 各有 `border-b`/`border-t`。

为兼容早期页面，旧令牌（`surface` / `surface-muted` / `border` / `text` / `text-muted` / `accent`）作为别名
指向同一套颜色；新代码一律使用上表的语义化令牌。

## 读模型的最终一致性

写命令落库后，视图由 projection 异步应用，因此紧接着的读取可能返回旧数据或 404。前端用三层兜底：

1. `QueryClient` 对 `unauthorized`（新会话尚未投影）重试 3 次、`not_found`（刚创建的聚合）重试 2 次；
2. mutation 成功后 `invalidateQueries`，并额外安排一次 700ms 后的重取（`shared/lib/refetch-later`）；
3. 列表页的 loading / empty / error 三态不会把旧数据当成空列表。

## 后端接口现状

以下能力原先只有 MCP 工具，现已全部有 HTTP 路由，界面直接用它们：

| 能力               | HTTP                                                              |
| ------------------ | ----------------------------------------------------------------- |
| 可用数据源类型     | `GET /ingestion/source-kinds`                                     |
| 浏览数据源树       | `GET /ingestion/connections/{id}/inspect?catalog=&schema=&table=` |
| 预演导入（不写库） | `POST /ingestion/connections/{id}/plan`（body 同 import）         |
| 测试连接           | `POST /ingestion/connections/{id}/test`                           |

语义建模还需要两条目录路由（语义实体只保存 `table_id`）：关系编辑器按表列出字段用
`GET /catalog/tables/{table_id}/fields`，画布显示 `schema.table` 用
`GET /catalog/tables/{table_id}`（返回表名 + schema/catalog 名）；未知表 id 都返回 404。

讨论相关的三条路由是为“对象名可点击”与 `@` 联想新增的：

| 能力                   | HTTP                                                                       |
| ---------------------- | -------------------------------------------------------------------------- |
| 单个对象的名称与路径   | `GET /comments/targets/{target_type}/{target_id}`                          |
| 批量解析（Inbox 列表） | `POST /comments/targets/lookup`（body `{refs:[{target_type,target_id}]}`） |
| `@` 用户联想           | `GET /iam/users/search?term=&limit=`（任意会话，不要求系统管理员）         |

前两条只返回 id 与 `path`，真正的 URL 由前端用路由助手拼；`field` / `semantic_entity` 这两类
target 依赖后端为目录字段与语义实体新增的 `field_id` / `entity_id`。

`plan` 用 `POST` 而不是 `GET`，因为它的 `include_tables` / `schema_mapping` 是嵌套结构，
放在 body 里才不用 JSON 字符串塞 query 参数；它不写任何状态。

仍然只有 MCP 的能力：`abandon_import_run`（把残留的 `pending` 运行标记为 abandoned），
界面上没有入口。

## 与需求文档（`../.cache/context-designs/fsd.md`）的已知差异

- `session_id` 的 body/query 传参、`withSessionQuery` / `withSessionBody` 已随 Bearer 改造移除；
- 会话续期不是前端硬编码的 5 分钟，而是后端配置的 `refresh_at`；
- 讨论默认允许同一对象存在多个线程（`comment.allow_multiple_threads: true`），界面按列表展示；
  若部署改为 `false`，重复创建会得到 409 并给出提示；
- 分层检查用 ESLint 核心 `no-restricted-imports` 实现（`eslint-plugin-boundaries` 无法解析
  TypeScript 的目录式导入），跨 slice 统一使用 `@/` 别名。

## 许可证

本前端与仓库其余部分同属 **GNU Affero General Public License v3.0 或更高版本**
（`AGPL-3.0-or-later`），完整条款见仓库根目录的 [LICENSE](../LICENSE)。
`package.json` 的 `license` 字段是同一 SPDX 表达式；`private: true` 只表示不发布到
npm registry，不影响许可证。
