import { useEffect, useState } from "react";

export type View = "home" | "report" | "practice" | "history" | "progress" | "status";

export interface Route {
  view: View;
  id?: string;
  params: URLSearchParams;
}

const VIEWS: View[] = ["home", "report", "practice", "history", "progress", "status"];

export function parseHash(hash: string): Route {
  const [path, query = ""] = hash.replace(/^#\/?/, "").split("?");
  const [view, id] = path.split("/");
  return {
    view: VIEWS.includes(view as View) ? (view as View) : "home",
    id: id ? decodeURIComponent(id) : undefined,
    params: new URLSearchParams(query),
  };
}

export function navigate(view: View, id?: string, params?: Record<string, string | undefined>): void {
  const query = new URLSearchParams();
  Object.entries(params ?? {}).forEach(([k, v]) => v !== undefined && query.set(k, v));
  const q = query.toString();
  window.location.hash = `/${view}${id ? `/${encodeURIComponent(id)}` : ""}${q ? `?${q}` : ""}`;
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseHash(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}
