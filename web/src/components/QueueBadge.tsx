import { Clock, LoaderCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { SessionSummary } from "@/types";

/** "Analyzing" or "In the queue" for a recording whose report isn't ready yet. */
export function QueueBadge({ s }: { s: SessionSummary }) {
  if (s.analyzing) {
    return (
      <Badge variant="sky">
        <LoaderCircle className="animate-spin" /> Analyzing
      </Badge>
    );
  }
  if (s.queued) {
    return (
      <Badge variant="muted">
        <Clock /> In the queue
      </Badge>
    );
  }
  return null;
}
