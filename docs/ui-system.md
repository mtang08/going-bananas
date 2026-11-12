# Going Bananas UI system

The frontend uses **shadcn/ui components backed by Radix UI**, **Tailwind CSS v4**,
and a small shared theme. React Query continues to manage server data; Recharts
continues to render charts. This is a UI migration, not a new planning engine.

## Why this stack

We need consistent controls and readable implementation more than a distinctive
palette. shadcn supplies component source that lives in this repository, so we
can adapt the app without adding a provider to every page or hiding behavior
behind a large wrapper. Radix supplies dialog behavior, including focus trapping
and Escape dismissal. We retain native select, date, checkbox, and radio semantics
where a more complex widget offers no clear benefit.

Tailwind is our default styling tool because it works directly with these
components and makes responsive layout and variants explicit. It is not a rule
to turn every page into a long utility string: repeated styling belongs in the
shared component or a domain component. CSS Modules would also be a sound choice
with a library such as Mantine. Adding both styling systems here would create
extra conventions without addressing a current need.

Official references: [shadcn Vite installation](https://ui.shadcn.com/docs/installation/vite),
[Radix-backed Dialog](https://ui.shadcn.com/docs/components/radix/dialog),
[Tailwind Vite integration](https://tailwindcss.com/docs/installation/using-vite),
and [Mantine's CSS Modules guidance](https://mantine.dev/styles/css-modules/).

## Where changes belong

| Layer | Location | Responsibility |
| --- | --- | --- |
| Theme | `frontend/src/theme.css` | Semantic colors, typography, radius, and base defaults |
| UI primitives | `frontend/src/components/ui/` | Buttons, cards, fields, badges, tables, dialogs, and disclosures |
| Shared behavior | `frontend/src/components/Modal.tsx` | The app's controlled-dialog interface and focus return |
| Domain components | `frontend/src/components/` | Workout structure, weekly plans, mileage, and activity displays |
| Pages | `frontend/src/pages/` | Queries, actions, validation, and composition |
| Existing feature layouts | `frontend/src/styles/legacy.css` and feature stylesheets | Layout rules retained during migration; avoid adding shared control styling here |

Shared primitives are exported from `components/ui/index.ts`. The `@/` alias
points at `frontend/src`. `cn` combines conditional classes and resolves Tailwind
conflicts so a deliberate caller override works.

## Component conventions

- Use `Button` variants for visual priority: `default` for the main action,
  `outline` or `secondary` for alternatives, `ghost` or `link` for quiet actions,
  and `destructive` for destructive actions. Use `asChild` for a link that should
  look like a button. Set button `type` explicitly in new form code.
- `Card` is a padded surface that accepts direct children. This is an intentional
  adaptation of the upstream source. Do not add another padding wrapper by
  default. `CardHeader` and `CardContent` are available for more structured layouts;
  account for their padding if using them.
- Use `Input`, `Textarea`, and `NativeSelect` with real labels, existing validation,
  and standard HTML events. Keep numeric conversion and missing-value handling in
  the page or domain logic. Styling must not turn an unknown value into zero.
- Use `Table` and its header/body/row/cell components for tabular data. Keep the
  accessible name and meaningful headers. Use expandable detail when a long
  table would overwhelm the main view.
- Use `Disclosure` for native expandable content, preserving `summary`, `open`,
  and `onToggle`. Use `variant="card"` when the disclosure is a whole panel.
- Use the shared `Modal` for an app dialog. Supply its accessible `label`,
  optional `description`, and `close` handler. Do not implement another backdrop,
  Escape listener, or focus trap in a page.
- Use `Badge` for short status labels. Keep the label explicit; color alone must
  not carry completion, provisional, error, or missing-data meaning.

```tsx
import { Button, Card, Input } from '@/components/ui'

<Card className="space-y-4">
  <h2>Session notes</h2>
  <label className="grid gap-2">
    Note
    <Input value={note} onChange={(event) => setNote(event.target.value)} />
  </label>
  <Button type="button" disabled={saving} onClick={save}>
    Save notes
  </Button>
</Card>
```

## Styling and iteration

Use semantic tokens such as `bg-card`, `text-muted-foreground`, `border-border`,
and `text-primary`. Prefer spacing and responsive utilities to new global
selectors. Extract repeated compositions when they have a shared purpose; avoid
building a generic framework around one page.

Existing feature CSS is layered below utilities. Keep those files readable and
limited to their feature. Do not reintroduce broad global `button`, `input`,
`table`, or `.panel` styling that competes with the UI primitives.
Load `styles.css` before app modules in `main.tsx`: it establishes the layer
order before feature styles register their `components` layer. Keep spacing
between cards explicit in the containing page or domain component.

Format touched files with Prettier. From `frontend`, use
`npx prettier --write src/pages/YourPage.tsx`, then run the relevant tests.
For broad UI changes, run `npm test`, `npm run lint`, and `npm run build`.
Check desktop and mobile layouts, keyboard navigation, loading/errors, and
missing-data states. Exercise mutations with synthetic data; visual checks
against the athlete's live app should stay read-only.

Component sources include their official registry URLs; the shadcn MIT notice is
in `frontend/src/components/ui/LICENSE.md`. Review upstream changes before
replacing a local component because our Card, native-select, and dialog adapters
have deliberate app-specific behavior. Keep dependency changes in the lockfile.
