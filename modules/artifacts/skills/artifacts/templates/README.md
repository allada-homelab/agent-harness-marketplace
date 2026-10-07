# Artifact templates

Five starting pages. Each already satisfies the *Local page contract* in `../references/design.md`
and the sandbox the dsh preview runs pages in, so you only change content, not structure.

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
   visible `:focus-visible`; `prefers-reduced-motion` respected.
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
   it, the choice remembered through the try/catch store. Any destructive action uses a two-click
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

**Slots** `title`, `description`, `table-heading`, `DATA`.

**DATA shape**
```
{ period: string,                                           // "1–30 Sep 2026"; the date-range note
  kpis:   [{ label: string, value: number, delta: number, unit: string }],   // delta: change vs the previous period, same unit as value; unit: "%", "ms", "" …
  series: [{ label: string, values: [number, …] }],           // equal-length; ≤5 series
  labels: [string, …],                                        // x labels for series values (same length)
  rows:   [{ <column>: string|number, … }] }                  // the table; first row's keys are the columns
```

**Interactions** KPI tiles row (value with `tabular-nums`, delta with direction shown by sign and
semantic color, never by color alone); one horizontal bar chart in inline SVG comparing the latest
value of each series (or a category breakdown), with one scale, a zero baseline, light gridlines,
ticks at round values and direct value labels; one small line chart (sparkline size or larger) of
`series` over `labels`, drawn to the same scale rules, the last point emphasised and labelled;
both charts colored `--c1`…`--c5` by series index and redrawn from DATA by script; a table whose
column headers are `type="button"` controls that sort ascending/descending on click with
`aria-sort` set; a note naming the date range from `period`. Theme switch; the charts read their
colors from tokens so they follow the theme without redrawing.

**Extend** More KPIs are more entries in `kpis`; the grid wraps. A second chart is one more SVG
built by the same scale helper. Table filters plug in above the table and reuse the sort's
render function.

## report.html

**Use when** the page is mostly prose someone reads top to bottom: a plan, a memo, a design doc, a
post-incident review, a decision record.

**Slots** `title`, `description`, `author`, `summary`, `DATA` (sections are
authored HTML in the page, each `<h2 data-toc>` with its prose, not data).

**DATA shape**
```
{ status: "Draft" | "In review" | "Approved" | string,   // drives the status pill's semantic color
  updated: "YYYY-MM-DD",                                 // the title block's date
  sources: [{ label: string, href: string }] }           // the numbered sources list
```

**Interactions** A title block (title, author line, date and status pill from DATA); a summary callout; a table
of contents built by the script from every `<h2 data-toc>` (ids derived from the heading text,
links jump to them); each section collapsible through a button in its heading with
`aria-expanded`, open by default so the page is complete at rest; a decision/callout box style
for a recommendation or risk; one simple table inside its own `overflow-x: auto` wrapper; a
footnote-style sources list rendered from `DATA.sources`, each link `target="_blank" rel="noopener"`.
Prose measure at most 65ch; print-friendly (`@media print` hides the theme switch and the
collapse buttons and opens every section). Theme switch.

**Extend** A section is one more `<section>` with an `<h2 data-toc>`; the TOC picks it up.
Further callout variants are one modifier class each on the callout box. A figure is a `<figure>`
with inline SVG and a `<figcaption>`.

## compare.html

**Use when** the page helps choose between a few options against stated criteria: tool selection,
vendor comparison, an architecture decision with trade-offs.

**Slots** `title`, `description`, `question`, `DATA`.

**DATA shape**
```
{ options:  [{ name: string, summary: string, pros: [string], cons: [string] }],   // 2–5
  criteria: [{ name: string, weight: 1..5, scores: [1..5, …] }] }   // scores[i] belongs to options[i]
```

**Interactions** A decision matrix with options as columns and criteria as rows, in its own
`overflow-x: auto` wrapper, the criterion column sticky on narrow screens; a weighted total per
option computed from DATA (Σ weight × score, also shown as a percentage of the maximum
Σ weight × 5); a recommendation block naming the top option and its margin over the runner-up in
points, and saying "tie" when the margin is zero; a toggle (segmented `type="button"` control)
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
`--c<i+1>`; edges as paths with an arrowhead marker whose fill is a token, and edge labels on a
small background so they stay legible over lines; a legend mapping each kind to its color.
Clicking (or Enter/Space on) a node highlights it and its incident edges and dims the rest;
clicking empty space clears it. The SVG sits in an `overflow-x: auto` container with a
`viewBox`, scales down to phone width and keeps text at least 12px; below the diagram, the
`caption` slot. Theme switch.

**Extend** Left-to-right layout is a swap of the rank and column axes in the layout function.
Node detail on selection plugs in as a panel below the diagram filled from extra node fields
(`detail: string`). Grouping is a rounded `<rect>` drawn behind a set of nodes before the edges.
