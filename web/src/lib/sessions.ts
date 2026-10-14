import type { SessionSummary } from "@/types";

/** Recorded, and its analysis hasn't finished (running now, or waiting for its turn). */
export const inQueue = (s: SessionSummary) => Boolean(s.analyzing || s.queued);

/** Has a report to open. */
export const hasReport = (s: SessionSummary) => !s.pending && !s.unanalyzed && !inQueue(s);
