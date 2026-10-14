import type { ReactNode } from "react";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

/** A titled group of settings rows. */
export function SettingsSection({
  id,
  title,
  description,
  aside,
  children,
  className,
}: {
  id?: string;
  title: string;
  description?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section id={id} aria-labelledby={id ? `${id}-title` : undefined} className={cn("surface min-w-0 scroll-mt-24 p-5 sm:p-6", className)}>
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 id={id ? `${id}-title` : undefined} className="font-display text-xl font-normal">
          {title}
        </h2>
        {aside}
      </div>
      {description && <p className="mt-0 mb-2 max-w-prose text-sm text-muted-foreground">{description}</p>}
      <div className="divide-y divide-border">{children}</div>
    </section>
  );
}

/** One setting: what it is on the left, its control on the right (stacked on narrow screens). */
export function SettingRow({
  label,
  description,
  htmlFor,
  aside,
  children,
  stack = false,
}: {
  label: ReactNode;
  description?: ReactNode;
  htmlFor?: string;
  aside?: ReactNode;
  children?: ReactNode;
  stack?: boolean;
}) {
  return (
    <div className={cn("flex flex-wrap items-center justify-between gap-x-6 gap-y-3 py-4", stack && "flex-col items-stretch")}>
      <div className={cn("min-w-0", !stack && "flex-1 basis-56")}>
        <div className="flex items-center gap-2">
          {htmlFor ? (
            <Label htmlFor={htmlFor} className="text-base font-semibold">
              {label}
            </Label>
          ) : (
            <span className="text-base font-semibold">{label}</span>
          )}
          {aside}
        </div>
        {description && <div className="mt-0.5 text-sm text-muted-foreground">{description}</div>}
      </div>
      {children && <div className={cn("flex min-w-0 items-center gap-2", !stack && "max-sm:w-full")}>{children}</div>}
    </div>
  );
}
