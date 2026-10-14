# Breeze: speakcheck's design

Speaking is breath, and breath is moving air. The interface is calm, airy and light-first, like a
meditation app for your voice. Thin lines of moving air are the signature element, and they always
mean something: they show what the app is doing.

## Layout

- **The sky** (`components/Sky.tsx`) is a persistent column on the left (≥1024px). It holds the wind,
  a status line and the **one primary control** (Record / Stop / Say it), so the state is visible
  from every page. That matters because people start recordings with a global shortcut from other
  apps.
- On narrower screens the sky folds into a 64px sticky strip (status + round button), and the
  pages move to a bottom tab bar on phones.
- Pages sit in a single reading column, max 920px wide, with one clear primary action each.

## Tokens (`src/index.css`)

| Role | Light | Dark | Use |
|---|---|---|---|
| Ground | `#F2F7FB` | `#0E1721` | page background |
| Surface | `#FFFFFF` | `#15212E` | cards, popovers |
| Ink | `#1C2B3A` | `#E2EBF4` | text |
| Muted | `#5A6B7D` | `#92A3B5` | secondary text |
| Border | `#DAE5EF` | `#24364A` | |
| Sky (primary) | `#3A78AE` | `#7EB4E2` | the primary action, wind lines; `--link` `#336C9E` for sky-coloured text |
| Alert | `#CF7652` / text `#B4532F` | `#EB9C7C` | sounds that went wrong, recording |
| Mint | `#5FAEA6` / text `#2F7F77` | `#86CFC6` | grammar |
| Success | `#3A9470` / text `#2D7A5B` | `#74C49F` | passed |

The fill colours of alert, mint and success are too light for text on white, so each has an
`-ink` version that passes WCAG AA. Use the `-ink` colour for any text.

There are no other accent colours. Semantic colours never stand in for the sky accent.

## Type

- **Fraunces** (variable, optical sizing), light 300 and italic, for page titles, the transcript and
  the word being practiced.
- **Nunito Sans** (variable) for everything else.
- **Noto Sans** for phonetic symbols (`.ipa`).
- Scale (1.2 from 15px): 12 · 14 · 15 · 18 · 21.6 · 26 · 34 · 44.

Fonts are bundled with `@fontsource`, so the app works offline.

## Shape and depth

- Cards: 20px radius (`--radius-card`), thin border, very soft sky-tinted shadow (`shadow-soft`),
  via the `.surface` class.
- Controls: 12px radius. Chips, segmented controls and tabs are pills.
- Cards only where grouping needs them; otherwise spacing and hairline dividers.

## Wind (`components/wind/WindCanvas.tsx`)

| State | The air |
|---|---|
| Idle | barely moving, low opacity |
| Recording | amplitude and speed follow the live mic level (it replaces a level meter) |
| Analyzing | soft capsules (the words) drift through gates, one per check (Transcribe, Sounds, Grammar), and wait at the one still running; the gates come from the engine's real stage events (`lib/stages.ts`) |
| Pass | smooth air with a soft green glow |
| Miss | a knot of turbulence in the alert colour |
| Offline | almost still while the engine reconnects |

With `prefers-reduced-motion`, the scene is settled and drawn once per change, with no animation.

## Components

shadcn/ui (Radix) in `components/ui`, restyled to these tokens. No native browser controls:
use `Select`, `Switch`, `ToggleGroup` (segmented), `Dialog` (never `window.confirm`), `Tooltip`,
`Collapsible`, and sonner toasts (engine notices become toasts in `components/Notices.tsx`).

Settings save as they change and confirm inline with `SavedMark`. There is no Save button.

## Copy

Plain and from the user's side ("Where analysis runs", not "remote mode"). American spelling
("practice" as noun and verb). Errors say what happened and what to do next.
