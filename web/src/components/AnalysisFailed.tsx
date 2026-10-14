import { Copy, RotateCcw, Settings, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { explainError } from "@/lib/errors";
import { navigate } from "@/router";

/** Why the last analysis failed, how to fix it, and a way to run it again. */
export function AnalysisFailed({ message, onRetry }: { message?: string; onRetry?: () => void }) {
  // After a reload only the kept recording is known, not the error.
  const e = message ? explainError(message) : null;
  const [copied, setCopied] = useState(false);
  return (
    <section role="alert" className="surface mb-8 border-alert/50 p-5">
      <div className="flex gap-3">
        <TriangleAlert className="mt-1 size-5 shrink-0 text-alert-ink" />
        <div className="min-w-0 flex-1">
          <h2 className="m-0 font-display text-xl font-normal">Your recording couldn't be analyzed</h2>
          {e ? (
            <>
              <p className="mt-1 mb-0 font-semibold">{e.title}.</p>
              <p className="mt-0.5 mb-0 text-sm text-muted-foreground">{e.detail}</p>
            </>
          ) : (
            <p className="mt-1 mb-0 text-sm text-muted-foreground">Run it again. If it fails, the reason shows here.</p>
          )}
          {e?.command && (
            <div className="mt-3 flex max-w-full items-center gap-2 rounded-xl bg-foreground/[0.04] py-1.5 pr-1.5 pl-3">
              <code className="min-w-0 flex-1 truncate font-mono text-sm">{e.command}</code>
              <Button
                size="sm"
                variant="ghost"
                onClick={() =>
                  navigator.clipboard?.writeText(e.command!).then(
                    () => setCopied(true),
                    () => undefined,
                  )
                }
              >
                <Copy /> {copied ? "Copied" : "Copy"}
              </Button>
            </div>
          )}
          <div className="mt-4 flex flex-wrap gap-2">
            {onRetry && (
              <Button onClick={onRetry}>
                <RotateCcw /> Analyze again
              </Button>
            )}
            {e?.settings && (
              <Button variant="outline" onClick={() => navigate("status")}>
                <Settings /> Open settings
              </Button>
            )}
          </div>
          <p className="mt-3 mb-0 text-xs text-muted-foreground">Your recording is kept. You'll find it in History.</p>
        </div>
      </div>
    </section>
  );
}
