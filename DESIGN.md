---
name: sito
description: A sieve-analysis worksheet for keyword research. Each pipeline step is a sieve, and the interface shows what passes through it.
colors:
  paper: "#e9edeb"
  sheet: "#f7f9f8"
  side: "#eef1ef"
  field: "#ffffff"
  hover: "#e8ecea"
  ink: "#1b211e"
  ink-2: "#454e4a"
  ink-3: "#5f6864"
  rule: "#d3d9d6"
  rule-strong: "#a3aca8"
  brass: "#86590f"
  brass-strong: "#86590f"
  brass-hover: "#6f4909"
  brass-fill: "#c28f35"
  brass-wash: "#f1e3c6"
  on-brass: "#ffffff"
  link: "#2a57a0"
  blue: "#2a57a0"
  green: "#2e7a4b"
  red: "#b8392a"
  hatch-ink: "rgba(27, 33, 30, 0.22)"
  hatch-soft: "rgba(27, 33, 30, 0.07)"
typography:
  headline:
    fontFamily: "Golos Text, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "1.375rem"
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: "-0.01em"
  title:
    fontFamily: "Golos Text, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "1.0625rem"
    fontWeight: 650
    lineHeight: 1.25
  subtitle:
    fontFamily: "Golos Text, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 650
    lineHeight: 1.25
  body:
    fontFamily: "Golos Text, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: 1.5
  prose:
    fontFamily: "Golos Text, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: 1.65
  body-small:
    fontFamily: "Golos Text, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.5
  control:
    fontFamily: "Golos Text, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 600
    lineHeight: 1
  label:
    fontFamily: "Golos Text, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 650
    letterSpacing: "0.06em"
  label-small:
    fontFamily: "Golos Text, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "0.6875rem"
    fontWeight: 600
    letterSpacing: "0.06em"
  numeral:
    fontFamily: "Golos Text, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "1.0625rem"
    fontWeight: 700
    lineHeight: 1.2
    fontFeature: "tnum"
  numeral-large:
    fontFamily: "Golos Text, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 750
    fontFeature: "tnum"
  mono:
    fontFamily: "ui-monospace, Cascadia Mono, SFMono-Regular, Consolas, monospace"
    fontSize: "0.8125rem"
rounded:
  hairline: "1px"
  sm: "2px"
  md: "3px"
  dot: "50%"
spacing:
  s1: "4px"
  s2: "8px"
  s3: "12px"
  s4: "16px"
  s5: "24px"
  s6: "32px"
  s7: "48px"
components:
  button:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    typography: "{typography.control}"
    rounded: "{rounded.md}"
    padding: "0 12px"
    height: "32px"
  button-hover:
    backgroundColor: "{colors.hover}"
  button-primary:
    backgroundColor: "{colors.brass-strong}"
    textColor: "{colors.on-brass}"
    typography: "{typography.control}"
    rounded: "{rounded.md}"
    padding: "0 12px"
    height: "32px"
  button-primary-hover:
    backgroundColor: "{colors.brass-hover}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.md}"
  button-ghost-hover:
    backgroundColor: "{colors.hover}"
    textColor: "{colors.ink}"
  button-danger:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.red}"
  button-sm:
    padding: "0 8px"
    height: "28px"
  input:
    backgroundColor: "{colors.field}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "0 10px"
    height: "32px"
  tag:
    textColor: "{colors.ink-2}"
    rounded: "{rounded.sm}"
    padding: "0 6px"
    height: "20px"
  tag-accent:
    textColor: "{colors.brass}"
  topbar:
    backgroundColor: "{colors.sheet}"
    padding: "0 24px"
    height: "48px"
  nav-link:
    textColor: "{colors.ink-2}"
    padding: "0 12px"
  nav-link-active:
    textColor: "{colors.ink}"
  tab:
    textColor: "{colors.ink-2}"
    padding: "10px 14px"
  panel:
    backgroundColor: "{colors.sheet}"
    rounded: "{rounded.md}"
  panel-head:
    textColor: "{colors.ink-2}"
    typography: "{typography.label}"
    padding: "10px 16px"
  readout:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    typography: "{typography.numeral}"
    padding: "6px 14px"
  tray:
    backgroundColor: "{colors.sheet}"
    rounded: "{rounded.md}"
    padding: "12px 12px 10px"
  tray-number:
    textColor: "{colors.ink-2}"
    rounded: "{rounded.sm}"
    height: "22px"
  pass-bar:
    backgroundColor: "{colors.side}"
    rounded: "{rounded.hairline}"
    height: "10px"
  pass-bar-passing:
    backgroundColor: "{colors.brass-fill}"
  progress:
    backgroundColor: "{colors.rule}"
    rounded: "{rounded.hairline}"
    height: "4px"
  progress-fill:
    backgroundColor: "{colors.blue}"
  table-header:
    backgroundColor: "{colors.side}"
    textColor: "{colors.ink-2}"
    padding: "0 10px"
    height: "32px"
  table-row:
    textColor: "{colors.ink}"
    typography: "{typography.body-small}"
    padding: "0 10px"
    height: "32px"
  table-row-selected:
    backgroundColor: "{colors.brass-wash}"
  table-row-excluded:
    textColor: "{colors.ink-3}"
  bulkbar:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.sheet}"
    rounded: "{rounded.md}"
    padding: "8px 12px"
---

# Design System: sito

## Overview

**Creative North Star: "The Sieve-Analysis Worksheet"**

sito is laid out like a sieve-analysis worksheet: a lab sheet on cool mesh-gray paper where each pipeline step is a sieve, and the page records how much material each one lets through. A project reads top to bottom as a stack of trays. Each tray shows how many keywords came in, how many it excluded and how many passed, as a bar and as figures, so you can see where keywords drop out without opening anything.

It is a working tool for long sessions next to spreadsheets. It is dense (32px rows and controls) and colourless by default: graphite ink on three close neutral tones, with hairline rules instead of boxes and shadows. The one accent is brass, the colour of a sieve frame, and it marks what acts and what passes. Status colour stays on marks and edges. Material that does not pass is hatched rather than hidden, because sito never destroys a keyword.

It deliberately avoids the SaaS-dashboard default of same-size metric cards over a generic table. Counts sit in one compact readout strip and on the trays themselves. Light and dark themes have equal standing: every token has a dark value, and in dark mode brass lightens to gold with dark text on it.

**Key Characteristics:**
- One typeface (Golos Text), with rank carried by weight, uppercase tracking and rules.
- One accent (brass) for action, selection, focus and the passing fraction.
- Status colour limited to 8px marks, 1px borders, icons and progress fills.
- A 135° diagonal hatch for everything that is not passing.
- Flat surfaces separated by hairlines, with one shadow reserved for floating layers.
- Corners of 3px at most, 32px controls, tabular figures everywhere.
- Empty and zero states drawn as carefully as full ones.

## Colors

A cool, near-neutral gray-green worksheet with graphite ink, one brass accent, and three small status inks.

### Primary
- **Sieve-Frame Brass** (#86590f): the only accent and a text-safe brass. It fills primary buttons (`brass-strong`, the same value), draws the focus outline, text caret, active nav and tab underlines, the checkbox accent, the border of the step being edited and of the open step picker, accent tags, and the needs-setup issue icons.
- **Deep Brass** (#6f4909): hover state of the primary fill.
- **Passing Brass** (#c28f35): the passing fraction of every pass bar, plus the needs-setup diamond. It is a fill for marks only, never for text.
- **Brass Wash** (#f1e3c6): selected table rows, text selection, and the 3px focus ring around inputs.
- **On Brass** (#ffffff): text and icons on a brass fill.

### Secondary
- **Blue Ink** (#2a57a0): links (`link`) and the running state (`blue`): the running dot, the queued ring, the border of a running tray, progress fills.
- **Bottle Green** (#2e7a4b): done and passing dots, success flash icons.
- **Vermilion** (#b8392a): failure dots, the borders of failed trays and error flashes, error text, required-field asterisks, danger buttons.

### Neutral
- **Mesh Paper** (#e9edeb): page ground.
- **Sheet** (#f7f9f8): content surfaces such as panels, trays, the top bar, table bodies and default buttons.
- **Side Tone** (#eef1ef): the second neutral, used for the sieve column, sticky table headers, code and log blocks, the docs aside, and the pass-bar track.
- **Field White** (#ffffff): input backgrounds.
- **Hover Tone** (#e8ecea): hover background for rows, menu items, and default and ghost buttons.
- **Graphite** (#1b211e): primary text, the entry mark on pass bars, the bulk-action bar background.
- **Graphite 2** (#454e4a): secondary text, uppercase labels, inactive nav and tabs.
- **Graphite 3** (#5f6864): hints, meta text, zero readouts, excluded rows, placeholders.
- **Hairline** (#d3d9d6): resting container borders and row dividers.
- **Strong Rule** (#a3aca8): control borders and structural dividers (top bar, page head, sieve column edge, table head, dashed "open" borders).
- **Hatch Ink** (rgba(27, 33, 30, 0.22)) and **Hatch Soft** (rgba(27, 33, 30, 0.07)): the two strengths of the diagonal hatch. Ink is for marks and bar segments, soft is for surfaces.

**Dark theme.** Every colour token has a dark override in `app.css`, declared twice with identical values: under `prefers-color-scheme: dark` (unless the page is forced light) and under `[data-theme="dark"]`. Keep the two blocks in sync. In dark mode the ground goes to near-black green (#101311), brass lightens to #dcaa52, and `on-brass` flips to #1b1408, so primary buttons read as dark text on gold. The theme toggle stores the choice in `localStorage` under `sito-theme`.

### Named Rules
**The Single Brass Rule.** Brass is the only accent. It marks the primary action, the current tab and nav item, focus, selection, the step being edited, and the passing fraction of every pass bar. If you think you need a second colour for emphasis, use weight or a rule instead.

**The Status-at-the-Edge Rule.** Green (done), red (failed or error) and blue (running or queued) appear only as 8px dots, 1px borders, icons, progress fills and short error text. They never fill a surface. The one tint is the 8% red wash on a hovered danger button.

**The Hatch Means Not Passing Rule.** A 135° diagonal hatch marks material that is not passing: excluded keyword rows, the excluded part of a pass bar, disabled buttons and steps, cancelled marks, and empty states and drop zones that hold nothing yet. Never use the hatch as decoration.

## Typography

**Display Font:** none; the interface has no display tier.
**Body Font:** Golos Text (self-hosted variable woff2, weights 400–900, Latin and Cyrillic subsets, with system-ui fallback)
**Label/Mono Font:** Golos Text for labels; the system monospace stack for code, keys and logs only.

**Character:** Golos Text is a plain, sturdy grotesque with good Cyrillic, set tight and a little heavy. The whole hierarchy lives in a 11–22px range and is built from weight steps (400, 500, 550, 600, 650, 700, 750), uppercase tracking and rules, not from large size jumps.

### Hierarchy
- **Headline** (700, 22px, 1.25, -0.01em): the page `h1`, which is the project name or page title. Only one per page.
- **Title** (650, 17px, 1.25): section `h2` on list and settings pages.
- **Subtitle** (650, 15px, 1.25): `h3`, tray titles, empty-state headings (16px there).
- **Body** (400, 15px, 1.5): running text and ledes (lede capped at 70ch). Docs prose uses 1.65 line height, capped at 72ch.
- **Body small** (400, 13px): table cells, hints, meta lines, menu items, flash text.
- **Control** (600, 13px, line-height 1): buttons. Inputs use 14px at 400, nav and tabs 14px at 550–600.
- **Label** (650, 12px, 0.06em, uppercase): panel heads, the sieve column head, group names in pickers and catalogues, value captions. Table headers use the same size and weight without uppercase.
- **Label small** (600–650, 11px, 0.06em, uppercase): readout captions and menu section labels.
- **Numeral** (700, 17px, 1.2, tabular): readout values. The "pan" total under the stack uses 750 at 20px.
- **Mono** (13px, 12px in logs): `code`, `kbd`, `pre`.

### Named Rules
**The One Family Rule.** Golos Text carries everything. Rank comes from weight (400–750), uppercase with tracking, and rules, inside a tight 11–22px ramp. Monospace appears only in code, keys and logs.

**The Tabular Figures Rule.** Every count, percentage and duration uses tabular figures, and numeric table columns are right-aligned.

## Layout

The app is a fixed 48px sticky top bar over one of three shells, all built on a 4px spacing scale (`s1`–`s7`: 4, 8, 12, 16, 24, 32, 48px) for layout gaps and page padding. Component insets step by 2px (6, 10, 14px), and every control height is even: 20px tags, 22px step numbers, 28px small controls, 32px controls and table rows.

- **Workspace** (project screens): a two-column grid. On the left is the sieve column (320–392px, side tone, sticky under the top bar, scrolls on its own). On the right is the page head, then the tab strip, then the active tab's content. The keyword table scrolls inside its own frame with a sticky header.
- **Page** (projects, connections, plugins, docs): centred at 1180px max, or 760px for narrow forms, with 32px top, 24px side and 48px bottom padding. A page head (headline, lede, actions on the right) closes with a strong rule. Sections are separated by 32px.
- **Split** (connector and stage setup): the form beside a sticky side-tone doc aside (280–420px). Docs use a 220px sticky nav beside the prose.

**Responsive.** At 960px and below, every shell collapses to one column: in the workspace the head comes first, then the stack, then the table. Sticky asides and the table's internal scroll switch off. At 640px and below, the brand word and version number hide, the nav scrolls sideways, page padding drops to 16px, and list items stack their actions under the text. On touch devices (`hover: none`), controls that are hover-revealed on desktop stay visible.

**Adding a screen.** Extend `base.html` and keep the default `page` shell (add `narrow` for single forms). Open with a page head, then group content in sections or panels. Project views extend `project.html`, fill its `panel` block and are added to the tab list. Settings forms come from the `field` macro in `_fields.html`, and run states from its `badge` macro. Icons come from `icon(name, label)`.

### Named Rules
**The Pipeline-Left Rule.** In a project, the sieve stack sits in the left column in run order and the current keyword state sits on the right. New project views become tabs in the right column. Nothing goes between the stack and the table.

## Elevation & Depth

The system is flat. Depth comes from three close neutral tones (paper under side under sheet) and from 1px rules, not from shadows. A single soft shadow token is used, and only for layers that float over content. Focus is an outline, not a glow: a 2px brass outline at 2px offset on every focusable element. Inputs replace it with a brass border plus a 3px brass-wash ring.

### Shadow Vocabulary
- **Floating** (`box-shadow: 0 10px 28px -12px rgba(20, 26, 23, 0.35)`; dark theme `0 12px 32px -10px rgba(0, 0, 0, 0.7)`): open menus and the bulk-action bar.
- **Input focus ring** (`box-shadow: 0 0 0 3px var(--brass-wash)`): focused inputs, selects and textareas.

### Named Rules
**The Floating-Only Shadow Rule.** The single shadow token belongs to layers that float over content: open menus and the bulk-action bar. Resting surfaces are flat and separated by hairlines.

## Shapes

Shapes are nearly square. Containers and controls use 3px corners (`md`). Small inset objects use 2px (`sm`): tags, step numbers, inline code, menu items, docs nav links. Bars and progress tracks use 1px (`hairline`). The only circle is the 8px status dot. Failed and cancelled marks are squares, and the needs-setup mark is a rotated square (diamond).

Borders do the structural work. A 1px solid hairline outlines resting containers. A 1px strong rule outlines controls and draws structural dividers. A 2px brass border marks the object being edited (the open tray, the step picker). A 1px graphite border frames the "pan" total at the foot of the stack.

The world has three patterns, all defined as custom properties: the dense hatch (1px lines every 5px, for marks and bar segments), the light hatch (every 6px, for surfaces), and a 12px square mesh that appears only behind the empty-pipeline plate, echoing the mesh in the brand mark.

### Named Rules
**The Dashed-Means-Open Rule.** A dashed border marks something open or unfinished: a step that needs setup, an insertion point, an empty state, a drop zone, a disclosure. Finished, resting material is outlined solid.

## Components

### Buttons
Compact, bordered and quiet. The brass button is the only loud control on a screen.
- **Shape:** 3px corners, 32px tall, 12px side padding, 6px icon gap. Small buttons are 28px tall with 8px padding. Icon-only buttons are square.
- **Default:** sheet background, strong-rule border, graphite text at 13px/600. Hover moves to the hover tone with a Graphite 3 border.
- **Primary:** brass fill and border, white text (dark text on gold in dark mode). Hover deepens the brass. Use at most one per view region (for example "Run all" in the stack, "Save" in a form).
- **Ghost:** no border or fill, Graphite 2 text. Used for secondary icon actions on trays and rows, Cancel links and the theme toggle.
- **Danger:** red text. On hover, a red border and an 8% red wash.
- **Disabled:** Graphite 3 text on a lightly hatched sheet, with a hairline border and a not-allowed cursor.
- **States:** colour transitions over 150ms on the expo-out ease. Press nudges down 1px. While an HTMX request is running, the button's icon spins.
- **Groups:** joined buttons share borders, and only the outer corners are rounded (used by the pager).

### Status badges
Run state is an 8px mark next to plain words: "Not run yet" (hollow gray ring), "Queued" (hollow blue ring), "Running" (pulsing blue dot), "Done · 2 min ago" (green dot), "Failed" (red square), "Cancelled" and "Off" (hatched square), "Needs setup" (passing-brass diamond). Keyword rows reuse the same marks: "Passing" (green dot) and "Excluded" (hatched square) followed by the reason in small Graphite 3 text. Badge text is 12px/600 Graphite 2. The mark carries the colour; the words stay neutral.

### Tags
20px tall, 2px corners, strong-rule outline, 12px Graphite 2 text, truncated at 220px (12rem inside tables). Used for cluster names and stat breakdowns. The accent variant uses a brass outline and brass text.

### Inputs / Fields
- **Style:** white field, strong-rule 1px border, 3px corners, 32px tall, 10px padding, 14px text. Textareas start at 88px and resize vertically. Selects use a drawn two-stroke chevron. Checkboxes and radios are 16px with the brass accent colour.
- **Hover / Focus:** hover darkens the border to Graphite 3. Focus shows a brass border and the 3px brass-wash ring.
- **Error:** red border via `aria-invalid="true"`, 13px red message below, and a red asterisk on required labels.
- **Field layout:** label (13px/600) above the control with a 6px gap, and a 13px Graphite 3 hint below. Long text fields span the full grid row. Fields tile in a 220px-minimum auto-fill grid.

### Navigation
- **Top bar:** 48px sheet strip with a strong rule below. It holds the brand mark (brass ring around a graphite mesh) and wordmark at 17px/750, then the nav links. Links are 14px/550 Graphite 2. The current page gets graphite text and a 2px brass underline sitting on the bar's rule.
- **Tabs:** the project tab strip follows the same pattern at 14px/600, with 10px × 14px padding and Graphite 3 tabular counts after the label. It scrolls sideways when it overflows.
- **Docs nav:** 14px/550 links with 2px corners. The current page gets a sheet background and an inset strong-rule outline.

### Panels
Sheet surface, hairline border, 3px corners. The head (10px × 16px) holds an uppercase 12px label and optional actions, with a hairline below. The body pads 16px. Stacked panels are 16px apart. Panels are never nested; inside them, groups are separated by hairline or dashed rules. The only framed insets are code and log blocks and fieldsets.

### Readouts
The project's counts (Passing, Excluded, Clusters) sit in one joined strip rather than separate cards: a sheet surface with a hairline border, cells divided by hairlines, each cell a 17px/700 tabular value over an 11px uppercase caption. A zero value dims to Graphite 3 at weight 500.

### Sieve tray and pass bar (signature)
The pipeline is an ordered list of trays joined by a dashed vertical line. Each tray is a sheet card with a strong-rule border and 3px corners. Its head holds a 22px step number (square outline), the step title (15px/650) and the status badge. A small kind line sits below, then the pass bar, then a row of small buttons (Run, run-from-here, settings, export, and a "more" menu). Tray states change only the border: blue while running, red when failed, dashed when setup is needed, 2px brass while being edited. A turned-off tray is lightly hatched with a dimmed title.

The **pass bar** is 10px tall on a side-tone track with 1px corners. Bars are scaled against the largest count in the stack, so they visibly narrow from tray to tray. The hatched segment spans what entered the step, the passing-brass segment overlays what passed, and a 2px graphite mark stands at the entry edge. The visible hatch between the brass and the mark is what this step excluded. Below the bar is a 12px tabular legend: "in N", then "excluded N" (a link to the excluded keywords) or "added N", then "pass N · P%". While a step runs, the bar is replaced by a 4px blue progress line (striped and crawling when the total is unknown) and a live "done / total" count, refreshed every second.

Between trays, an insertion point shows on hover (always visible on touch and after the last tray) and opens the step picker. The picker is a 2px brass-bordered list of stages grouped under uppercase labels. At the foot of the stack, the "pan" box (1px graphite border) holds the count passing through every sieve.

### Data table
13px cells, 32px rows, hairline row dividers. The sticky header is 12px/650 Graphite 2 on the side tone, over a strong rule. The keyword column is 550 weight, and numeric columns are tabular and right-aligned. Hovered rows use the hover tone and selected rows the brass wash. Excluded rows keep their place: lightly hatched, Graphite 3 text, keyword struck through in the strong-rule colour. The filter toolbar above wraps as needed and ends with a live tabular match count. When rows are selected, a graphite **bulk-action bar** sticks to the bottom of the viewport with the floating shadow, outline buttons in sheet colour, and the destructive action separated at the far end.

### Menus
Native `details` disclosures. The list floats 4px below its trigger, aligned right, at least 240px wide, with a sheet surface, strong-rule border and the floating shadow. Items are 13px with a leading icon and 2px corners, and use the hover tone. Uppercase 11px section labels name what a group of items acts on (for example "Passing keywords"). Menus close on outside click and Escape.

### Empty states and messages
Empty lists get a dashed strong-rule block on a lightly hatched sheet: a 16px heading, one sentence (max 62ch) and the next action as a primary button. An empty pipeline shows a solid label plate on the 12px mesh instead. Flash messages are a sheet strip with a strong-rule border and a leading icon: green icon for notices, red border and icon for errors.

### Icons
Lucide, stroke 1.75, served from the inline sprite in `templates/_icons.svg` through the `icon()` helper. They are 16px inline (12px in sort headers) and aligned at -3px. Icons take `currentColor`. Only issue icons (brass) and flash icons (status colour) are tinted.

### Motion
Motion is limited to state. Colour, border and opacity transitions run for 150ms on `cubic-bezier(0.16, 1, 0.3, 1)`. The running dot pulses (1.4s), request icons spin (0.9s) and indeterminate progress crawls (0.8s). Under `prefers-reduced-motion: reduce`, all animation and transition collapse to near zero.

### Named Rules
**The Empty-Is-Drawn Rule.** Zero and empty states are designed, not left out. Zero readouts dim to Graphite 3 at weight 500. Empty lists get a dashed, lightly hatched block with a heading, one sentence and the next action. An empty pipeline shows the mesh plate.

## Do's and Don'ts

### Do:
- **Do** use the custom properties in `app.css` for every colour, space and radius. When you add a colour token, add its dark value to both dark blocks.
- **Do** render settings forms through the `field` macro and run states through the `badge` macro, so every stage and connector looks the same.
- **Do** draw excluded, disabled and not-yet material with the hatch (`--hatch` for marks and bar segments, `--hatch-light` for surfaces), and strike through excluded keyword text.
- **Do** set every count in tabular figures and right-align numeric table columns.
- **Do** write state labels in plain words that name the outcome: "Passing", "Excluded", "Needs setup", "Done · 2 min ago".
- **Do** keep controls and table rows at 32px (28px for small controls).
- **Do** give icon-only buttons an accessible label through `icon(name, label)` and a `title`.
- **Do** design the empty state of every new list: a dashed border, the light hatch, a heading, one sentence and the next action.

### Don't:
- **Don't** introduce a second accent colour or a second typeface; brass and Golos Text are the whole vocabulary.
- **Don't** fill a surface or a block of text with green, red or blue; status colour belongs to dots, borders, icons and progress fills.
- **Don't** use the word "retained" in the interface; keywords are passing or excluded.
- **Don't** add shadows to resting containers, and don't nest panels inside panels.
- **Don't** round corners past 3px or use pill shapes; the only circle is the status dot.
- **Don't** place a small uppercase label above a heading as an eyebrow; uppercase labels stand alone and name a group, a column or a value.
- **Don't** use icon fonts, emoji or text glyphs as icons; add missing icons to the Lucide sprite in `_icons.svg`.
- **Don't** hide excluded keywords from the table by default; they stay in place, hatched and struck through, with their reason.
