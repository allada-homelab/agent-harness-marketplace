# Artifact templates

Ten starting pages and a component sheet. Each already satisfies the *Local page contract* in
`../references/design.md` and the sandbox the dsh preview runs pages in, so you only change
content, not structure. When no page fits whole, lift blocks from `components.html`.

**Contents:** How to use one · Rules every template follows · tool.html · dashboard.html · report.html · compare.html · diagram.html · components.html · checklist.html · timeline.html · catalog.html · slides.html · calculator.html

## How to use one

Pick the closest template below, copy it to the output dir from `artifactctl.py prepare` as
`<slug-of-title>.html`, and edit the copy, never the template. Replace the text of every element
that carries `data-slot="<name>"`, including the `<title>` and `<meta name="description">` (the
`title` and `description` slots), then replace the `DATA` object at the top of the script with the
user's content in the same shape. Keep the `:root` token block, the theme switch and the
interaction code: change token values to fit the subject, but keep every token defined on bare
`:root` and redefined in both dark blocks. Add or drop sections as the content needs. Then run
`artifactctl.py check` and `artifactctl.py render` on the copy as SKILL.md step 4 says.

## Rules every template follows

These are the build rules for anyone writing or changing a template. `../../../test/test_templates.py`
enforces the ones marked *(tested)*.

1. **One file that passes the gate.** One self-contained `.html` with no sibling assets.
   `artifactctl.py check` prints `ok` with no `WARN` *(tested)*, and `artifactctl.py render` exits 0
   with no console line *(tested)*.
2. **The whole Local page contract.** The skeleton in order (`<!doctype html>`, `<html lang>`,
   charset, viewport with `viewport-fit=cover`, `<title>`, description meta, `<style>`); a title
   that is a two-to-four-word name; no external script (the CDN allowlist applies if one is ever
   unavoidable); Google Fonts allowed, always with a real fallback stack; phone-first at 390px with
   no horizontal page scroll and a 16px side gutter set once with `padding-inline` on `body`;
   `env(safe-area-inset-top|bottom, 0px)` padding on `:root`; three theme states exactly as
   design.md specifies: every color a token first defined on bare `:root` with
   `color-scheme: light`, redefined in `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { … } }`
   and again in `:root[data-theme="dark"]`, both with `color-scheme: dark`, and `body` taking its
   background from a token; `font-variant-numeric: tabular-nums` on every figure that lines up;
   visible `:focus-visible`; `prefers-reduced-motion` respected. "No `WARN`" in rule 1 includes
   the `check` `theme:` warning, raised for any color literal outside `:root` and the theme blocks.
3. **The sandbox rules.** The dsh preview is an iframe with `sandbox="allow-scripts"` only. So: no
   form submission — every action button is `type="button"` with a `click` handler, Enter on an
   input runs the same function from `keydown`, no `submit` listener, no `action`/`method`
   (`check` fails all of these); no downloads; no `alert`/`confirm`/`prompt`; no `window.open`
   or `window.print`; no `fetch`; storage only inside `try/catch` and only for conveniences (theme
   choice, a draft, a filter), with the page fully working when it throws.
4. **Header comment.** The line right after `<!doctype html>` is
   `<!-- template: <file stem> · slots: title, description, <other slots…>, DATA -->`, listing
   every `data-slot` name, `title` and `description` first and `DATA` last *(tested)*.
5. **Slots and DATA.** Static copy the model must replace carries `data-slot="<name>"`; a
   `data-slot="title"` element is required (the visible page heading) *(tested)*. Everything
   data-driven derives from one `const DATA = { … }` at the top of the page's single inline
   `<script>` *(tested: exactly one inline script)*, placed at the end of `<body>`. A string is either a slot
   or a DATA field, never both: headings, the question and captions are slots. Sample content is
   realistic and specific, never lorem ipsum, and chosen so a reader can see what each part of the
   page is for. Build DOM from DATA with `createElement` and `textContent`, not `innerHTML` with
   data values.
6. **Categorical colors.** Only the validated palettes from SKILL.md step 1, as tokens
   `--c1`…`--c5`: light `#0072B2,#009E73,#D55E00,#B2548F,#C77F00`, dark
   `#357FB5,#009E73,#D55E00,#A64E97,#C77F00`, assigned by fixed index (series or category *i* gets
   `var(--c<i+1>)`), never cycled or reordered by value. Five categories at most; fold the rest
   into "Other". Semantic colors (`--danger`, `--ok`) and the accent are separate tokens.
7. **Sized elements are blocks.** Any element the script gives a width, height or fill is
   `display: block`, flex or grid, never an inline `<span>` left `display: inline` (an inline span
   ignores `width`, which is how a bar chart renders empty). In SVG, every shape has an explicit
   `fill` or `stroke` from a token, and the `viewBox` leaves room for the outermost labels.
8. **Shared controls.** A theme switch in the header: a segmented Auto/Light/Dark group of
   `type="button"` buttons with `aria-pressed`, where Auto removes `data-theme` and Light/Dark set
   it, the choice remembered through the try/catch store, and the pressed button's shadow taken
   from a `--shadow` token defined in all three theme blocks. Any destructive action uses a two-click
   confirm (first click arms and relabels the button, a second within 3 s acts). Copy buttons call
   `navigator.clipboard.writeText` inside the click handler and, on rejection or absence, reveal the
   text in a read-only `<textarea>` and select it. `tool.html` has the reference implementation of
   all three; copy it rather than reinventing it.
9. **Size and libraries.** At most 30 KB per template *(tested)*. No library: charts and diagrams
   are inline SVG drawn by the script from DATA.
10. **Craft.** A deliberate type scale as tokens, neutrals with a slight hue bias instead of pure
    grey, spacing through `gap` on flex/grid, `min-width: 0` on grid/flex children that hold text,
    and a page that opens complete at rest in a working state. `tool.html` is the quality bar.

## tool.html

**Use when** the page is an interactive tool: the user enters items, sees them in a list and
watches totals change (a ledger, a tracker, a checklist with amounts, a log).

**Slots** `title`, `description`, `eyebrow`, `note`, `form-heading`, `list-heading`, `DATA`.

**DATA shape**
```
{ currency: "EUR", locale: "en-IE", budget: number,
  categories: [string, …≤5],
  entries: [{ date: "YYYY-MM-DD", label: string, category: one of categories, amount: number }] }
```

**Interactions** Add with the *Add expense* button or Enter in any field, with inline validation
messages (empty label, empty or non-positive amount, missing date); per-row Remove with two-click
confirm; KPI tiles (spent, left or over budget, per day over the span of dates) and per-category
bars recomputed on every change; *Copy as text* (tab-separated, clipboard or selected fallback);
*Clear all* with two-click confirm; theme switch; entries kept in `localStorage` when the browser
allows it, keyed by the page title, with a banner saying the starting rows are examples. Stable ids
`entry-label`, `entry-amount`, `entry-category`, `entry-date`, `entry-add` and rows
`#entries > li[data-id]` are what the sandbox test drives; keep them.

**Extend** A new field is one `.field` in the form, one property read in `addEntry()`, and one
cell in `row()`. Different KPIs are computed at the top of `render()`. For a tool without money,
drop `budget` and the currency formatter and keep the add/list/remove skeleton.

## dashboard.html

**Use when** the page summarises numbers someone scans for state and trend: a metrics review, a
weekly report, a service health summary.

**Slots** `title`, `description`, `line-heading`, `bars-heading`, `table-heading`,
`notes-heading`, `notes`, `DATA`. Chart units live in the heading slots.

**DATA shape**
```
{ period: string,                                           // "1–30 Sep 2026"; the date-range note
  kpis:   [{ label: string, value: number, delta: number, unit: string,      // delta: change vs the previous period, same unit as value; unit: "%", "ms", "" …
             better?: "down" }],                                  // a falling value is good news (latency, errors)
  series: [{ label: string, values: [number, …] }],           // equal-length; ≤5 series
  labels: [string, …],                                        // x labels for series values (same length)
  rows:   [{ <column>: string|number, … }] }                  // the table; first row's keys are the columns
```

**Interactions** KPI tiles row (value with `tabular-nums`, delta with direction shown by sign and
semantic color, never by color alone; `better: "down"` flips which direction is good, and a delta
on a `%` value shows as `pp`); one horizontal bar chart in inline SVG comparing the latest
value of each series (or a category breakdown), with one scale, a zero baseline, light gridlines,
ticks at round values and direct value labels; one small line chart (sparkline size or larger) of
`series` over `labels`, drawn to the same scale rules, the last point emphasised and labelled;
both charts colored `--c1`…`--c5` by series index and redrawn from DATA by script, the line chart
labelling series directly and showing a legend only when those labels cannot fit; a table whose
column headers are `type="button"` controls that sort ascending/descending on click with
`aria-sort` set; a note naming the date range from `period`; a notes list under its own heading.
Theme switch; the charts read their
colors from tokens so they follow the theme without redrawing.

**Extend** More KPIs are more entries in `kpis`; the grid wraps. A second chart is one more SVG
built by the same scale helper. Table filters plug in above the table and reuse the sort's
render function.

## report.html

**Use when** the page is mostly prose someone reads top to bottom: a plan, a memo, a design doc, a
post-incident review, a decision record.

**Slots** `title`, `description`, `author`, `summary`, `DATA` (sections are authored HTML in the
page, not data: write only `<section><h2 data-toc>…</h2>…</section>`; the script wraps everything
after the heading in a collapsible body, turns the whole heading into the collapse button and
derives the id).

**DATA shape**
```
{ status: "Draft" | "In review" | "Approved" | string,   // drives the status pill's semantic color
  updated: "YYYY-MM-DD",                                 // the title block's date
  sources: [{ label: string, href: string }] }           // the numbered sources list
```

**Interactions** A title block (title, author line, date and status pill from DATA); a summary callout; a table
of contents built by the script from every `<h2 data-toc>` (ids derived from the heading text,
links jump to them and open a collapsed target); each section collapsible through its heading,
which the script makes one button with `aria-expanded`, open by default so the page is complete at
rest; a callout box for a recommendation, with `.callout.risk` as the second variant, its wash
tokens (`--accent-wash`, `--danger-wash`) a `color-mix` of tokens defined once on `:root`; one simple table inside its own `overflow-x: auto` wrapper; a
footnote-style sources list rendered from `DATA.sources`, each link `target="_blank" rel="noopener"`.
Prose measure at most 65ch; print-friendly (`@media print` resets the tokens to light, hides the
theme switch and the collapse chevrons and opens every section). Theme switch.

**Extend** A section is one more `<section>` with an `<h2 data-toc>`; the TOC and the collapse
button pick it up.
Further callout variants are one modifier class each on the callout box. A figure is a `<figure>`
with inline SVG and a `<figcaption>`.

## compare.html

**Use when** the page helps choose between a few options against stated criteria: tool selection,
vendor comparison, an architecture decision with trade-offs.

**Slots** `title`, `description`, `eyebrow`, `question`, `matrix-heading`, `cards-heading`, `DATA`.

**DATA shape**
```
{ options:  [{ name: string, summary: string, pros: [string], cons: [string] }],   // 2–5
  criteria: [{ name: string, weight: 1..5, scores: [1..5, …] }] }   // scores[i] belongs to options[i]
```

**Interactions** A decision matrix with options as columns and criteria as rows, in its own
`overflow-x: auto` wrapper, the criterion column sticky on narrow screens, a read-only weight
column, and the best score in each row bold with a triangle; a weighted total per option computed
from DATA (Σ weight × score, also shown as a percentage of the maximum Σ weight × 5), its bar
drawn on one fixed-width track shared by every option; a recommendation block naming the top
option and its margin over the runner-up in points, saying "tie" when the margin is zero, and a
"what would flip it" line naming the criterion where the runner-up leads by the most weighted
points and the weight it would need there; a toggle (segmented `type="button"` control)
between raw scores and weighted scores in the cells; per-option cards with pros and cons lists
under the matrix; option *i* colored `--c<i+1>` wherever it is marked (column header swatch,
total bar). Theme switch.

**Extend** Editable weights are one `<input type="number" min="1" max="5">` per criterion row
whose `input` handler rewrites `DATA.criteria[i].weight` and re-runs the render. A per-criterion
note is one more field on the criterion and one row cell.

## diagram.html

**Use when** the page explains a flow or process as nodes and arrows: a request path, a pipeline,
a state machine, an approval process. Read `../references/diagramming.md` for the craft.

**Slots** `title`, `description`, `caption`, `DATA`.

**DATA shape**
```
{ nodes: [{ id: string, label: string, kind: string }],   // kind → legend entry and color index (≤5 kinds)
  edges: [{ from: id, to: id, label?: string }] }
```

**Interactions** The diagram is inline SVG laid out by the script from DATA: a layered
top-to-bottom layout where a node's rank is its longest path from a source (cycles broken by
ignoring back edges for ranking) and nodes in a rank sit in columns, centred; rounded-rectangle
nodes sized to their wrapped labels, filled from a surface token and stroked with their kind's
`--c<i+1>`, kinds numbered by first appearance in `DATA.nodes` (a sixth kind shares `--c5`,
labelled "Other"); edges as paths with an arrowhead marker whose fill is a token, a long edge
routed through the ranks it skips, a back edge dashed, and edge labels on a small background so
they stay legible over lines; a legend mapping each kind to its color. Clicking (or Enter/Space
on) a node highlights it and its incident edges, dims the rest and names it in a status line;
*Clear highlight*, Escape or clicking empty space clears it. A *Fit* / *1:1* scale control: Fit
shrinks the SVG to the panel but keeps text at least 12px, and the `overflow-x: auto` container
scrolls the rest. Below the diagram, the `caption` slot, then "Every step in words", the edge list
as text with *Copy as text*. An edge naming an unknown node id throws, so `render` reports it.
Theme switch.

**Extend** Left-to-right layout is a swap of the rank and column axes in the layout function.
Node detail on selection plugs in as a panel below the diagram filled from extra node fields
(`detail: string`). Grouping is a rounded `<rect>` drawn behind a set of nodes before the edges.

## components.html

**Use when** no template fits whole and you need a tested block: a chart, a sortable table, a
sandbox-safe action group, a confirm, a toast, a callout, tabs, a code block with copy. It is a
valid page itself, so it also serves as the visual reference for every block.

**Slots** `title`, `description`, `DATA` (the sample rows and series the chart and table blocks
render).

**How to lift a block** Each block is three contiguous pieces with the same name: markup between
`<!-- component: <name> -->` and `<!-- /component: <name> -->`, CSS under `/* component: <name> */`
in the single `<style>`, and script under `// component: <name>` in the single `<script>`. Copy all
three into a page that already has the token block, plus the shared `/* base */` CSS and
`// base` script pieces; the block's colors are tokens, so it follows the theme. The `line-chart`
CSS also needs `bar-chart`'s `.chart`/`.ch` rules. Charts draw through a `ResizeObserver` on the
next frame, and their hover tooltips are native SVG `<title>`. Blocks: `tokens`, `theme-switch`, `header`, `kpi`, `bar-chart` (`barChart(el, rows)`),
`line-chart` (`lineChart(el, labels, series)`), `table` (sortable, `overflow-x: auto`), `field`
(label, input, inline validation, `type="button"` action, Enter on keydown), `confirm` (two-click),
`toast` (aria-live), `callout` (note / warning / decision), `empty`, `pill` (ok / warn / fail /
neutral), `tabs`, `details`, `code` (copy button), `toc`.

**Extend** A new block is one more comment-delimited triple following the same naming; keep the
sheet under 30 KB by sharing classes rather than adding decoration.

## checklist.html

**Use when** the page is a procedure someone works through and ticks off: a runbook, a release
checklist, an onboarding list, a packing list with notes.

**Slots** `title`, `description`, `intro`, `DATA`.

**DATA shape**
```
{ groups: [{ name: string,
             steps: [{ id: string, text: string, detail?: string, optional?: boolean }] }] }
```

**Interactions** Steps grouped under headings, each a `type="button"` toggle row with a visible
check mark state (`aria-pressed`), optional steps marked; a progress header (done / total, "N
required left", a block-level progress bar in `--accent`, per-group counts; groups are not
categories, so no `--c` tokens); a per-step notes field (a `<textarea>` revealed by a
*Note* button, its text kept with the step); *Reset* with two-click confirm; *Copy as text*
producing a Markdown task list with notes (clipboard inside the click handler, selected fallback);
a filter segmented control All / Open / Done with an empty state when it hides everything; state
(checks, notes and the filter choice) kept through the try/catch store keyed by the page title,
with the page fully working without it. The DOM is built once and updated in place, so focus and
typing survive a toggle. Theme switch.

**Extend** A step with a sub-list is a step whose `detail` holds a short `<ul>`-worth of text split
on newlines. Timing is one `started`/`finished` timestamp pair recorded in the toggle handler and
shown in the progress header.

## timeline.html

**Use when** the page shows when things happen or happened: a roadmap, a project schedule, a
changelog, an incident timeline, a release history.

**Slots** `title`, `description`, `caption`, `DATA`.

**DATA shape**
```
{ unit: "day" | "week" | "month",                               // tick spacing of the axis
  lanes: [{ name: string,
            items: [{ label: string, start: "YYYY-MM-DD", end?: "YYYY-MM-DD",   // no end = a point event
                      kind?: string, note?: string }] }] }      // kind → color index (≤5 kinds)
```

**Interactions** Two views of the same DATA behind a segmented control: a *Chart* view (inline
SVG: one time axis across the top with ticks per `unit` and labelled month boundaries, one lane
per `lanes` entry, ranges as rounded bars (a 20% tint of the kind color with a solid stroke and
left cap) and point events as diamonds, colored `--c<i+1>` by kind in order of first appearance,
capped at five, a "today" line when today falls in range, labels in `--fg` inside bars that are
wide enough and beside the others; on a week axis month boundaries carry the month name) inside an
`overflow-x: auto` container where lane names stay pinned and which opens scrolled to today, and
a *List* view (lanes as headings, items in date order with their dates and notes). The chosen view
is remembered; without one the default is List at ≤640px, else Chart. Tapping an item in either
view opens a detail panel below with label, dates, duration, status and note; a legend of kinds.
Theme switch.

**Extend** Dependencies are `after: <label>` on an item and one arrow path per dependency drawn in
the chart view. Milestones are point events with `kind: "milestone"`. Grouping lanes is one
heading row per group.

## catalog.html

**Use when** the page is a browsable set of similar things: servers, modules, tools, recipes,
candidates, options the user picks from.

**Slots** `title`, `description`, `intro`, `DATA`.

**DATA shape**
```
{ facets: [string, …≤3],                                        // item keys that become filter chips
  items:  [{ name: string, summary: string, tags: [string], url?: string,
             <facet>: string, … , <number key>?: number,              // e.g. memory: 1536 → a sort option
             fields?: [{ label: string, value: string }] }] }      // what the card displays
```

**Interactions** A search field (filters on name, summary and tags as the user types; `Escape`
clears), one row of filter chips per facet built from the distinct values in `items`
(`type="button"`, `aria-pressed`, multi-select within a facet, AND across facets, each showing its
live match count and disabled at zero), a sort control (name, or any top-level numeric key), a
result count, and a responsive card grid (one column at phone width) where each card shows name,
summary, tags and `fields`, with an optional link (`target="_blank" rel="noopener"`). The first
facet colors the card border and its chip swatch (`--c1`…`--c5` by value order); other facets show
as a status dot, `--ok`/`--warn`/`--danger` when the value slugs to running/degraded/stopped. A
number shown on the card needs both the numeric key (to sort) and a `fields` entry (to display). An empty state when nothing matches with a *Clear filters*
button. Filter and search state kept through the try/catch store. Theme switch.

**Extend** A detail view is a panel opened from a card showing every field. A compare mode is a
"pin" button per card and a table of the pinned items' fields under the grid.

## slides.html

**Use when** the content is meant to be presented or paged through one screen at a time: a
briefing, a walkthrough, a short pitch, a lesson.

**Slots** `title`, `description`, `DATA` (slide bodies are authored HTML `<section>`s in the
page, not data).

**DATA shape**
```
{ footer: string,            // deck name or date shown on every slide
  notes: { [slideId]: string } }   // optional presenter notes per slide id
```

**Interactions** Each `<section class="slide" id="…">` is one screen sized to the viewport
(`height: 100%` on html/body, safe-area insets respected); navigation by Previous / Next
`type="button"` controls, left/right arrow keys, and horizontal swipe on touch (pointer events);
a slide counter and a thin progress bar; an *Overview* toggle that shows every slide as a scaled
grid and jumps on tap; a *Notes* toggle that shows the current slide's note from DATA below the
slide; `DATA.footer` and the slide number added to each slide by script; overview cards
fixed-height with their content scaled through `font-size`; the slide-in animation only after the
first move, so the first paint is at rest; the current slide index remembered through the
try/catch store; a theme switch on the first slide, initialised with
`setTheme(store.get("theme") ?? root.dataset.theme)` so an authored `data-theme` survives. At phone width slides stack vertically with scroll-snap as a fallback when scripts are off.
Content slides include a title slide, a bullet slide, a two-column slide, a big-number slide, an
image-or-figure slide (inline SVG placeholder) and a closing slide, so every layout is demonstrated.

**Extend** A new layout is one more `.slide` modifier class. Speaker timing is a timer started on
the first *Next*. Fragments (reveal bullets one at a time) are a `data-fragment` attribute on list
items and a step within the Next handler.

## calculator.html

**Use when** the page turns a few inputs into computed outputs the user wants to play with: a cost
estimate, a capacity plan, a unit converter, a what-if model with the formula shown.

**Slots** `title`, `description`, `intro`, `formula`, `DATA`. `description` is only the meta; the
visible lede is `intro`.

**DATA shape**
```
{ inputs:  [{ id: string, label: string, unit?: string, value: number, min?: number, max?: number,
              step?: number, help?: string }],
  outputs: [{ id: string, label: string, unit?: string, compute: "<expression over input ids only>",
              digits?: number }],                         // a term shared by outputs is repeated in each
  presets: [{ name: string, values: { [inputId]: number } }] }
```

**Interactions** One `.field` per input (an `inputmode="decimal"` text field that accepts a comma
plus, when `min`/`max` exist, a paired range slider kept in sync), recomputed on every `input` event, never on submit; outputs as KPI tiles
with units and `tabular-nums`, the primary output first and larger; a breakdown block that shows
each output's formula with the current numbers substituted (the `formula` slot explains the model
in one sentence above it); preset buttons (`type="button"`) that load `presets[i].values`; a
*Reset* button; *Copy as text* of inputs and outputs; invalid or out-of-range input shows an
inline message and the dependent outputs show "—". `compute` strings are evaluated by a small
safe evaluator over the input ids (no `eval`/`Function` with user text: parse numbers, ids, `+ - *
/ ( )` and `min`/`max`/`round(x, d)` with optional digits), so DATA stays data. Numbers format in
the viewer's locale; only the theme is stored. Theme switch.

**Extend** A sensitivity row is one more output computed at ±10% of a chosen input. A chart of an
output across one input's range is a `lineChart` from `components.html` fed by sampling the
evaluator.
