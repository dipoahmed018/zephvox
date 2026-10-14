import { ArrowRight, CloudOff, History as HistoryIcon, RotateCcw, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { EmptyState, PageHead } from "@/components/PageHead";
import { QueueBadge } from "@/components/QueueBadge";
import { api } from "@/api";
import { useAction, useEngine } from "@/engine";
import { fmtDate, fmtDuration, plural } from "@/format";
import { inQueue } from "@/lib/sessions";
import { navigate } from "@/router";
import type { SessionSummary } from "@/types";

export function History() {
  const { state } = useEngine();
  const run = useAction();
  const [sessions, setSessions] = useState<SessionSummary[] | null>(null);
  const [deleting, setDeleting] = useState<SessionSummary | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () => run(api.sessions).then((s) => s && setSessions(s));
  useEffect(() => {
    load();
  }, [state.lastAnalysis?.seq, state.sessionsVersion, state.pending]);

  const remove = async () => {
    if (!deleting) return;
    setBusy(true);
    await run(() => api.deleteSession(deleting.id));
    setBusy(false);
    setDeleting(null);
    load();
  };

  return (
    <>
      <PageHead title="History">
        {sessions?.length ? `${plural(sessions.length, "recording")}, newest first.` : "Every recording you've analyzed."}
      </PageHead>

      {sessions === null ? (
        <p className="text-muted-foreground">Loading…</p>
      ) : sessions.length === 0 ? (
        <EmptyState icon={<HistoryIcon />} title="No recordings yet">
          <p className="m-0 max-w-sm text-muted-foreground">Each recording you make is kept here with its report.</p>
        </EmptyState>
      ) : (
        <ul className="surface m-0 list-none divide-y divide-border p-0">
          {sessions.map((s) => (
            <li key={s.id} className="flex items-center gap-2 pr-3 first:rounded-t-[var(--radius-card)] last:rounded-b-[var(--radius-card)]">
              <button
                type="button"
                disabled={s.pending || s.unanalyzed || inQueue(s)}
                onClick={() => navigate("report", s.id)}
                className="group flex min-w-0 flex-1 flex-wrap items-center gap-x-5 gap-y-2 rounded-l-[inherit] px-5 py-4 text-left transition-colors hover:bg-accent disabled:cursor-default disabled:hover:bg-transparent"
              >
                <span className="w-36 shrink-0">
                  <span className="block font-semibold">{fmtDate(s.created)}</span>
                  <span className="block text-sm text-muted-foreground tabular-nums">{fmtDuration(s.duration ?? 0)}</span>
                </span>
                <span className="min-w-0 flex-1 basis-48 truncate text-muted-foreground">
                  {s.unanalyzed
                    ? "The analysis didn't finish. The recording is kept."
                    : s.analyzing
                      ? "Being analyzed now. Its report opens when it's done."
                      : s.queued
                        ? "Waiting for the analysis before it to finish."
                        : s.preview || "…"}
                </span>
                {s.pending ? (
                  <Badge variant="muted" title="Recorded while the server was unreachable">
                    <CloudOff /> Waiting for the server
                  </Badge>
                ) : inQueue(s) ? (
                  <QueueBadge s={s} />
                ) : s.unanalyzed ? (
                  <Badge variant="alert">Not analyzed</Badge>
                ) : (
                  <span className="flex items-center gap-1.5">
                    <Badge variant={s.counts.pronunciation ? "alert" : "muted"}>{plural(s.counts.pronunciation ?? 0, "sound")}</Badge>
                    <Badge variant={s.counts.grammar ? "mint" : "muted"}>{plural(s.counts.grammar ?? 0, "grammar issue")}</Badge>
                    <ArrowRight className="ml-1 size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
                  </span>
                )}
              </button>
              {s.unanalyzed && (
                <Button size="sm" variant="outline" disabled={Boolean(state.job)} onClick={() => run(() => api.reanalyze(s.id))}>
                  <RotateCcw /> Analyze
                </Button>
              )}
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button variant="ghost" size="icon" aria-label={`Delete the recording from ${fmtDate(s.created)}`} disabled={inQueue(s)} onClick={() => setDeleting(s)}>
                    <Trash2 className="text-muted-foreground" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Delete</TooltipContent>
              </Tooltip>
            </li>
          ))}
        </ul>
      )}

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title="Delete this recording?"
        description={deleting ? `The recording from ${fmtDate(deleting.created)} and its report are removed. This can't be undone.` : undefined}
        confirm="Delete"
        danger
        busy={busy}
        onConfirm={remove}
      />
    </>
  );
}
