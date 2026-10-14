import { useEffect, useRef } from "react";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

/** What the air is doing. Every mode maps to real app state; nothing moves for decoration. */
export type WindMode = "idle" | "recording" | "analyzing" | "pass" | "miss" | "offline";

export interface Gate {
  label: string;
  state: "waiting" | "running" | "done";
}

interface Props {
  mode: WindMode;
  /** Live microphone level, 0–1 (recording). */
  level?: number;
  /** Analysis stages drawn as gates the words flow through (analyzing). */
  gates?: Gate[];
  /** A smaller version with fewer lines and no gate labels (the phone strip). */
  compact?: boolean;
  className?: string;
}

interface Capsule {
  x: number;
  w: number;
  lane: number;
  speed: number;
}

interface Sim {
  amp: number;
  speed: number;
  turb: number;
  glow: number;
  phase: number;
  level: number;
  capsules: Capsule[];
}

const TARGETS: Record<WindMode, { amp: number; speed: number; turb: number; glow: number }> = {
  idle: { amp: 2.5, speed: 0.3, turb: 0, glow: 0 },
  recording: { amp: 4, speed: 0.8, turb: 0, glow: 0 },
  analyzing: { amp: 5, speed: 1.0, turb: 0, glow: 0 },
  pass: { amp: 2, speed: 0.5, turb: 0, glow: 1 },
  miss: { amp: 6, speed: 0.85, turb: 1, glow: 0 },
  offline: { amp: 1, speed: 0.08, turb: 0, glow: 0 },
};

const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

function rgba(color: string, alpha: number): string {
  const hex = color.trim().replace("#", "");
  if (!/^[0-9a-f]{6}$/i.test(hex)) return `rgba(58,120,174,${alpha})`;
  const n = parseInt(hex, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
}

const reducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

/** Thin lines of moving air that answer to the voice, the analysis stages and practice results. */
export function WindCanvas({ mode, level = 0, gates = [], compact = false, className }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const props = useRef({ mode, level, gates, compact });
  props.current = { mode, level, gates, compact };
  const { dark } = useTheme();

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let w = 0;
    let h = 0;
    let colors = { wind: "#3a78ae", alert: "#cf7652", success: "#3a9470", ink: "#1c2b3a", muted: "#5a6b7d" };
    const readColors = () => {
      const cs = getComputedStyle(canvas);
      const get = (name: string, fallback: string) => cs.getPropertyValue(name).trim() || fallback;
      colors = {
        wind: get("--wind", colors.wind),
        alert: get("--alert", colors.alert),
        success: get("--success", colors.success),
        ink: get("--foreground", colors.ink),
        muted: get("--muted-foreground", colors.muted),
      };
    };
    readColors();
    const sim: Sim = { amp: 2.5, speed: 0.3, turb: 0, glow: 0, phase: Math.random() * 10, level: 0, capsules: [] };

    const render = (dt: number) => {
      if (!w || !h) return;
      const { mode, level, gates, compact } = props.current;
      const t = TARGETS[mode];
      const k = Math.min(1, dt * 4);
      sim.level = lerp(sim.level, mode === "recording" ? level : 0, Math.min(1, dt * 12));
      const amp = mode === "recording" ? t.amp + 22 * sim.level : t.amp;
      const speed = mode === "recording" ? t.speed + 2.6 * sim.level : t.speed;
      sim.amp = lerp(sim.amp, amp * (compact ? 0.45 : 1), k);
      sim.speed = lerp(sim.speed, speed, k);
      sim.turb = lerp(sim.turb, t.turb, Math.min(1, dt * 2.5));
      sim.glow = lerp(sim.glow, t.glow, Math.min(1, dt * 2.5));
      sim.phase += sim.speed * dt;

      ctx.clearRect(0, 0, w, h);
      if (sim.glow > 0.01) {
        const g = ctx.createRadialGradient(w / 2, h * 0.45, 0, w / 2, h * 0.45, Math.max(w, h) * 0.6);
        g.addColorStop(0, rgba(colors.success, 0.18 * sim.glow));
        g.addColorStop(1, rgba(colors.success, 0));
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, w, h);
      }

      const n = compact ? 5 : Math.max(7, Math.min(16, Math.round(h / 44)));
      const cy = h * 0.45;
      const sigma = h * 0.2;
      const energy = mode === "recording" ? 0.3 + sim.level : mode === "offline" ? 0.15 : 0.45;
      for (let i = 0; i < n; i++) {
        const y0 = h * (0.08 + (0.84 * i) / Math.max(1, n - 1));
        const mid = Math.abs(i - (n - 1) / 2) / Math.max(1, (n - 1) / 2);
        ctx.beginPath();
        for (let x = -10; x <= w + 10; x += 6) {
          let y =
            y0 +
            sim.amp * (1 - mid * 0.5) * Math.sin(x * 0.012 + sim.phase + i * 0.6) +
            sim.amp * 0.45 * Math.sin(x * 0.031 - sim.phase * 1.6 + i * 1.3);
          if (sim.turb > 0.01) {
            const r = Math.hypot(x - w * 0.55, y0 - cy);
            y += sim.turb * Math.exp(-(r * r) / (2 * sigma * sigma)) * 26 * Math.sin(r * 0.06 - sim.phase * 3);
          }
          if (x === -10) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        const warm = sim.turb * Math.exp(-((y0 - cy) ** 2) / (2 * (h * 0.12) ** 2));
        ctx.strokeStyle =
          warm > 0.35 ? rgba(colors.alert, 0.35 + 0.5 * warm) : rgba(colors.wind, 0.12 + 0.42 * (1 - mid) * energy);
        ctx.lineWidth = 1 + (1 - mid) * 1.3;
        ctx.setLineDash([w * 0.16, w * 0.06 + i * 9]);
        ctx.lineDashOffset = -sim.phase * 70 - i * 40;
        ctx.stroke();
      }
      ctx.setLineDash([]);

      if (mode === "analyzing" && gates.length) drawGates(dt, gates, compact, cy);
      else sim.capsules = [];
    };

    // Words (as soft capsules) drift along the stream and wait at the stage still running.
    const drawGates = (dt: number, gates: Gate[], compact: boolean, cy: number) => {
      const xs = gates.map((_, i) => w * (0.2 + (0.6 * i) / Math.max(1, gates.length - 1)));
      if (gates.length === 1) xs[0] = w * 0.55;
      const open = gates.findIndex((g) => g.state !== "done");
      const stopAt = open === -1 ? Infinity : xs[open] - 10;

      if (!compact) {
        ctx.font = `600 11px ${getComputedStyle(canvas).fontFamily}`;
        ctx.textAlign = "center";
        gates.forEach((g, i) => {
          const on = g.state === "running";
          const done = g.state === "done";
          ctx.strokeStyle = rgba(on ? colors.wind : colors.muted, on ? 0.65 : done ? 0.35 : 0.22);
          ctx.lineWidth = on ? 1.5 : 1;
          ctx.setLineDash([3, 5]);
          ctx.beginPath();
          ctx.moveTo(xs[i], cy - h * 0.2);
          ctx.lineTo(xs[i], cy + h * 0.14);
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.fillStyle = rgba(done ? colors.success : on ? colors.wind : colors.muted, done || on ? 1 : 0.75);
          ctx.fillText((done ? "✓ " : "") + g.label.toUpperCase(), xs[i], cy + h * 0.14 + 18);
        });
      }

      const lanes = compact ? 1 : 3;
      if (sim.capsules.length < (compact ? 6 : 14) && Math.random() < dt * 3) {
        sim.capsules.push({ x: -40, w: 16 + Math.random() * 40, lane: Math.floor(Math.random() * lanes), speed: 40 + Math.random() * 30 });
      }
      const laneY = (lane: number) => cy + (lane - (lanes - 1) / 2) * (compact ? 0 : 22);
      // Keep a gap between capsules in a lane so they queue instead of overlapping.
      const byLane = new Map<number, Capsule[]>();
      sim.capsules
        .sort((a, b) => b.x - a.x)
        .forEach((c) => {
          const lane = byLane.get(c.lane) ?? [];
          const ahead = lane[lane.length - 1];
          const limit = Math.min(stopAt - c.w, ahead ? ahead.x - c.w - 8 : Infinity);
          c.x = Math.min(c.x + c.speed * dt, Math.max(c.x, limit));
          lane.push(c);
          byLane.set(c.lane, lane);
        });
      sim.capsules = sim.capsules.filter((c) => c.x < w + 20);
      sim.capsules.forEach((c) => {
        const y = laneY(c.lane) + 6 * Math.sin(c.x * 0.012 + sim.phase + c.lane);
        ctx.fillStyle = rgba(colors.wind, compact ? 0.45 : 0.32);
        ctx.beginPath();
        ctx.roundRect(c.x, y - 4, c.w, compact ? 5 : 8, 4);
        ctx.fill();
      });
    };

    let frame = 0;
    let last = performance.now();
    let still = reducedMotion();
    const loop = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      if (!document.hidden) render(dt);
      frame = requestAnimationFrame(loop);
    };
    // Reduced motion: settle the scene and draw it once per change.
    const settle = () => {
      for (let i = 0; i < 90; i++) render(1 / 60);
    };

    const resize = () => {
      const r = canvas.getBoundingClientRect();
      if (!r.width || !r.height) return;
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      w = r.width;
      h = r.height;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (still) settle();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);
    resize();
    if (still) settle();
    else frame = requestAnimationFrame(loop);

    const motion = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    const onMotion = () => {
      still = reducedMotion();
      cancelAnimationFrame(frame);
      if (still) settle();
      else frame = requestAnimationFrame(loop);
    };
    motion?.addEventListener("change", onMotion);
    const recolor = () => {
      readColors();
      if (still) settle();
    };
    (canvas as HTMLCanvasElement & { recolor?: () => void }).recolor = recolor;

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      motion?.removeEventListener("change", onMotion);
    };
  }, []);

  // Theme changes recolour the lines; with reduced motion, state changes redraw the still scene.
  useEffect(() => {
    (canvasRef.current as (HTMLCanvasElement & { recolor?: () => void }) | null)?.recolor?.();
  }, [dark, mode, gates.map((g) => g.state).join()]);

  return <canvas ref={canvasRef} aria-hidden="true" className={cn("pointer-events-none absolute inset-0 size-full", className)} />;
}
