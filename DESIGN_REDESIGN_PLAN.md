# VORTEX Design-Only Redesign Plan

## 1. Review scope and baseline

This plan covers the entire operator-facing application: the local web
workbench, Electron window chrome, responsive layouts, first-run and utility
surfaces, and the Android client presentation. It is deliberately a visual,
interaction-design, information-architecture, accessibility, and motion plan.
It does **not** change backend routes, API payloads, request timing, execution
policy, Guardian approval, PTY behavior, persistence, authentication,
capabilities, or any other operational behavior.

### Current product map reviewed

| Area | Existing purpose that must remain intact |
| --- | --- |
| New Task / overview | Conversation-led request intake, typed-plan review, Guardian decision, real streamed evidence, task context, telemetry, diagnostics, and recent activity. |
| Terminal | Explicitly opened real host PTY with sessions, tabs, split view, resize, input, paste, and stop controls. |
| Engagements | Operator-declared scope gate for authorized active security work. |
| Operations record | Conversations, durable tasks, activity/audit verification, reports, observed assets, local memory, and learned procedures. |
| Intelligence and host readiness | Advisory agents, local GGUF/Ollama models, system health, tool probes, dependency proposals, and settings. |
| Supporting surfaces | First-run checks, dependency planner, report preview, help, about, capability prompt, toasts, and desktop window controls. |

### Design observations

1. The application already has a credible dark tactical palette and truthful
   status vocabulary, but its dense overview presents too many simultaneous
   panels before an operator has a task in progress.
2. Navigation contains many primary and secondary destinations. The hierarchy
   is technically complete but does not sufficiently distinguish the
   high-frequency workflow (task, terminal, review) from supporting reference
   and configuration areas.
3. Existing panels, labels, buttons, and badges are visually similar, which
   makes approval, stop, recovery, and ordinary refresh actions compete for
   attention.
4. The current responsive rail preserves controls, but a design pass should
   make destination context, overflow actions, and long operational content
   easier to scan on compact screens without hiding a required action.
5. Current motion is intentionally restrained and honors reduced-motion. The
   redesign must retain that restraint: a security workbench should feel alive
   through real state changes, not decorative animation.

## 2. Redesign outcome

Create a focused **VORTEX Operations Console**: a black, deep-green command
environment that feels like a credible hacker workstation while remaining
calm, legible, truthful, and professional. The interface will make the
operator's next safe action unmistakable, keep real terminal/evidence content
dominant, and reveal depth progressively rather than crowding every view.

### Non-negotiable preservation rules

- Preserve every view, control, DOM hook/ID relied on by JavaScript and tests,
  keyboard flow, API call, status text meaning, terminal renderer behavior,
  download/install workflow, and Guardian confirmation boundary.
- Treat tool output as evidence only; visual presentation must never imply a
  command has run, a model is installed, a service is healthy, or a security
  conclusion is proven when the existing data says otherwise.
- Preserve explicit labels alongside color and icons for every state; retain
  focus visibility, skip navigation, semantic landmarks, dialog behavior, and
  the reduced-motion experience.
- Add no canvas rain, fake terminal stream, background particle loop, or
  animation that consumes continuous CPU/GPU work.

## 3. Information architecture and navigation plan

### 3.1 Organize destinations by operator intent

Keep all current destinations, while regrouping their visual presentation into
four labeled navigation zones:

1. **Operate** — New Task, Terminal, Tasks, Engagements.
2. **Investigate** — Conversations, Activity, Reports, Assets.
3. **Intelligence** — Agents, Models, Tools, Memory, Learning.
4. **Control** — System, Settings, Help, About.

The active destination remains visibly named in the top bar and in the rail.
No existing destination will be removed, renamed at the routing level, or
made inaccessible at any viewport. On compact widths, the icon rail will use
existing accessible button names and a compact current-view label/overflow
mechanism rather than silently losing context.

### 3.2 Establish an operation-first shell

- Keep desktop title-bar controls and the local/offline identity, but simplify
  the title bar into a quiet identity strip.
- Make the top bar a persistent **command status line**: current location,
  compact real telemetry, backend/connection state, and a clearly separated
  emergency Stop All control.
- Introduce a contextual secondary action area per view, using the existing
  actions rather than inventing workflow. For example, Terminal shows session
  actions; Reports shows export/system report actions; Tools shows refresh and
  dependency actions.
- Use a consistent content frame with page title, truthful description, action
  cluster, and content modules. Long pages retain their current scroll model.

## 4. Visual system: black-and-green hacker logic

### 4.1 Color roles

Use a tokenized palette rather than per-component color decisions:

| Role | Direction | Use |
| --- | --- | --- |
| Void black | Near-black base with subtly differentiated layers | Canvas, terminal, primary depth. |
| Phosphor green | One principal green family with low/medium/high emphasis steps | Active navigation, positive/ready state, primary action, terminal prompt. |
| Signal cyan | Cool, restrained secondary accent | Links, selected data, focus ring, informational state. |
| Amber | Caution and needs-review only | Guardian review, in-progress, unavailable recovery actions. |
| Red | Stop, reject, error, destructive controls only | Never used as decorative contrast. |
| Neutral graphite | High-legibility gray scale | Body text, borders, inactive controls, metadata. |

Green glow will be limited to the active command field, keyboard focus,
terminal cursor, and status indicators. Backgrounds will use faint gridlines,
scanline texture, and radial vignettes at static opacity; they will never
obscure evidence or resemble a fake data feed.

### 4.2 Typography, icons, and surfaces

- Use one highly legible UI sans/monospace pairing already available in the
  application. Reserve monospace for commands, IDs, telemetry, evidence, and
  state values; use the UI face for navigation and explanatory copy.
- Introduce a clear type scale: page title, module title, command/data label,
  body, and metadata. Avoid all-caps for explanatory paragraphs.
- Replace inconsistent symbolic decoration with a small, consistent line-icon
  vocabulary while retaining accessible text labels and current button names.
- Standardize surface levels: canvas, command surface, panel, inset/evidence,
  and modal. Each needs one border treatment, one spacing scale, and one
  hover/focus treatment.

### 4.3 State design

Create one shared state grammar for all panels, rows, badges, and buttons:
`ready`, `running`, `review required`, `paused`, `unavailable`, `failed`,
`completed`, and `unknown`. Every state shows an icon/shape, explicit label,
and color. This keeps health, Guardian, downloads, task lifecycle, and
terminal session states visually consistent without altering their source data.

## 5. Screen-by-screen redesign plan

### 5.1 New Task command deck

1. Make the request composer the clear first focal point, with high-contrast
   prompt treatment, example prompts, shortcut hint, and visible send state.
2. Use a three-stage layout that adapts to task state: **request**, **review
   plan**, then **observed result**. Empty-state support modules stay present
   but are de-emphasized until data exists.
3. Present typed argv, risk, Guardian decision, authorization reason, and
   approval/rejection controls in a dedicated review card. The approval action
   must be visually strongest only when existing behavior allows it; Stop,
   Reject, and Pause retain distinct destructive/caution hierarchy.
4. Keep live terminal evidence in a large contrast-safe inset with sticky
   labels for source and state. Do not cover, synthesize, truncate differently,
   or change streaming behavior.
5. Consolidate task state, AI pipeline, host telemetry, diagnostics, and host
   context into a collapsible/right-hand intelligence stack on wide screens and
   ordered modules below the evidence on narrow screens. All current data stays
   available.

### 5.2 Terminal workspace

- Preserve the real PTY pane as the visual anchor and maintain all session,
  split, focus, keyboard, paste, stop, minimize, maximize, and close behavior.
- Redesign chrome as a minimal green-on-black terminal frame: a clear session
  tab strip, compact connection/cwd status, separated safe session controls,
  and a stronger input focus state.
- Ensure ANSI output remains readable and unchanged semantically; surrounding
  decoration must not add contrast noise or reduce usable terminal height.

### 5.3 Record and investigation views

- **Conversations and Tasks:** make lifecycle, timestamp, risk, and primary
  action scannable in list rows; group secondary actions behind deliberate
  visual hierarchy while retaining every existing action.
- **Activity, Reports, and Assets:** use evidence-first cards with outcome,
  provenance, date, and export/verify action ordering. Keep unobserved versus
  observed language and badges distinct.
- **Engagements:** frame scope creation as a short authorization checklist;
  make expiry, allowed target, excluded target, and close action conspicuous.

### 5.4 Intelligence and control views

- **Agents, Models, Tools, System:** standardize cards into status header,
  factual detail, remediation/action row, and optional advanced detail. Do not
  make unavailable dependencies look installable without the existing proposal
  process.
- **Memory and Learning:** provide calmer records-oriented layouts that
  communicate local persistence and validation without overusing alerts.
- **Settings:** group choices by execution safety, privacy/connectivity, local
  intelligence, and interface preference; preserve existing setting values and
  save interactions exactly.

### 5.5 Dialogs, onboarding, Help, and About

- Give first-run, dependencies, report preview, capability confirmation, Help,
  and About a shared modal/window chrome with a clear title, state marker,
  close/minimize/maximize affordances where they already exist, and a stable
  footer action hierarchy.
- Make first-run checks a readable checklist that distinguishes required,
  optional, unavailable, and complete states using the shared state grammar.
- Keep Help and About documentation-focused, with strong internal navigation,
  readable command examples, and no change to links or disclosures.

## 6. Responsive, accessibility, and animation plan

### Responsive behavior

- Validate desktop (1440+), laptop (1024–1439), tablet (768–1023), narrow
  mobile (375–767), and 320px minimum layouts.
- Reflow grids rather than hiding data. The command composer, Guardian review,
  terminal input, safety actions, and active navigation state always remain
  reachable without horizontal page scrolling.
- Preserve terminal split behavior where supported; at tight widths, retain the
  existing single-column fallback and clear session affordances.

### Accessibility

- Meet WCAG 2.2 AA contrast for text and interactive controls, including green
  text on black and muted operational metadata.
- Preserve semantic headings/landmarks, keyboard-only flows, focus trapping in
  dialogs, Escape behavior, descriptive labels, and status text beyond color.
- Test 200% zoom, forced colors/high contrast, reduced motion, focus order,
  and screen-reader names for all existing controls.

### Motion

- Motion is state feedback, never background spectacle: 120–200 ms opacity or
  position transitions for navigation, panel reveal, focus, and genuine status
  change; no looping decorative movement.
- Retain only necessary existing progress/cursor indicators and ensure the
  `prefers-reduced-motion` mode removes nonessential transitions, shimmer, and
  animated indicators without hiding status.
- Do not use a Matrix rain effect, animated code, fake scan output, particles,
  `requestAnimationFrame`, or autoplay visualizations.

## 7. Implementation sequence (design-only)

1. **Freeze the functional contract.** Capture screenshots and DOM/API/test
   baselines; list selectors, IDs, keyboard behavior, and state vocabulary that
   the renderer and tests depend on.
2. **Create design foundations.** Define CSS tokens, spacing, typography,
   surface, state, focus, and motion rules. Apply them without changing
   JavaScript interfaces or markup hooks.
3. **Restructure visual shell.** Retheme title bar, sidebar grouping, top
   status line, page headers, and responsive navigation presentation while
   keeping routes and view IDs untouched.
4. **Redesign critical workflow.** Apply the command-deck layout to New Task,
   then terminal chrome and Guardian/evidence hierarchy. Test an idle, planned,
   approved, running, rejected, failed, paused, and unavailable state.
5. **Apply reusable modules.** Convert record lists, cards, status rows,
   buttons, forms, empty states, toasts, and dialogs to the shared system.
6. **Complete remaining views.** Redesign every reviewed view and supporting
   surface in the order documented above, preserving all controls and content.
7. **Perform responsive and accessibility polish.** Verify target breakpoints,
   zoom, keyboard traversal, screen-reader names, contrast, reduced motion,
   Electron title bar controls, and modal behavior.
8. **Regression proof.** Run lint and the full automated suite; manually smoke
   test the real backend, task/approval flow, streamed output, terminal,
   dependencies, models, dialogs, navigation, and desktop window operations.

## 8. Acceptance criteria

- Every existing route, view, control, shortcut, action, live value, truthful
  unavailable state, and Guardian boundary continues to work unchanged.
- The overview makes the current workflow and next safe action clear in five
  seconds at both idle and active-task states.
- The terminal is visually dominant in its view, usable by keyboard, and never
  covered by decorative design.
- Black/green hacker aesthetics are coherent without sacrificing contrast,
  credibility, performance, or evidence readability.
- All interactive states have text, icon/shape, and color representation;
  focus and reduced-motion behavior remain first-class.
- Visual QA covers the complete screen inventory and target breakpoints with
  before/after screenshots and no unreviewed regressions.

Once done, Review the design more and more, resolve, test and debug again and so on, only stop when you're convinced that the design is effective and passes 10/10 (100%) and its effectively working with perfect integration and navigation.
