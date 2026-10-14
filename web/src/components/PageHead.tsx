import type { ReactNode } from "react";

/** The page title in the display face, with an optional line underneath and actions on the right. */
export function PageHead({ title, children, actions }: { title: ReactNode; children?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="m-0 font-display text-3xl leading-tight font-light tracking-tight sm:text-4xl">{title}</h1>
        {children && <p className="mt-2 mb-0 max-w-prose text-muted-foreground">{children}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

/** A small heading over a group of content. */
export function SectionLabel({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="mb-3 flex items-center gap-3">
      <h2 className="eyebrow m-0 shrink-0">{children}</h2>
      <span className="h-px flex-1 bg-border" aria-hidden="true" />
      {aside}
    </div>
  );
}

/** Shown when a page has nothing yet: what will appear here and how to get there. */
export function EmptyState({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="surface grid justify-items-center gap-3 px-6 py-12 text-center">
      <span className="grid size-14 place-items-center rounded-full bg-primary/10 text-link [&>svg]:size-6">{icon}</span>
      <h2 className="m-0 font-display text-xl font-normal">{title}</h2>
      {children}
    </div>
  );
}
