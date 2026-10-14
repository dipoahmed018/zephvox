// zephvox website: theme, copy buttons, install tabs, and the wind in the hero.
(() => {
  const root = document.documentElement;
  const dark = matchMedia("(prefers-color-scheme: dark)");
  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)");
  const isDark = () => (root.dataset.theme ? root.dataset.theme === "dark" : dark.matches);

  // ---- theme ------------------------------------------------------------------------------
  const shot = document.getElementById("shot");
  function applyTheme() {
    if (shot) shot.src = `assets/screenshots/report-${isDark() ? "dark" : "light"}.png`;
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = isDark() ? "#0e1721" : "#f2f7fb";
    wind.recolor();
  }
  document.getElementById("theme")?.addEventListener("click", () => {
    root.dataset.theme = isDark() ? "light" : "dark";
    try {
      localStorage.setItem("zephvox.site.theme", root.dataset.theme);
    } catch (e) {
      /* private window: the choice lasts for this visit */
    }
    applyTheme();
  });
  dark.addEventListener("change", applyTheme);

  // ---- copy buttons -----------------------------------------------------------------------
  document.querySelectorAll(".copy").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const code = document.getElementById(btn.dataset.copy);
      if (!code) return;
      const label = btn.querySelector("span");
      const done = () => {
        btn.dataset.done = "true";
        label.textContent = "Copied";
        setTimeout(() => {
          btn.dataset.done = "false";
          label.textContent = "Copy";
        }, 1800);
      };
      try {
        await navigator.clipboard.writeText(code.textContent);
        done();
      } catch (e) {
        const range = document.createRange();
        range.selectNodeContents(code);
        const sel = getSelection();
        sel.removeAllRanges();
        sel.addRange(range); // let the visitor press Ctrl+C
        label.textContent = "Press Ctrl+C";
      }
    });
  });

  // ---- operating system switch: one choice controls every command on the page -------------
  const osTabs = [...document.querySelectorAll("[data-os-tab]")];
  function setOs(os) {
    osTabs.forEach((t) => {
      const on = t.dataset.osTab === os;
      t.setAttribute("aria-selected", String(on));
      t.tabIndex = on ? 0 : -1;
    });
    document.querySelectorAll("[data-os]").forEach((el) => {
      el.hidden = el.dataset.os !== os;
    });
  }
  osTabs.forEach((t, i) => {
    t.addEventListener("click", () => setOs(t.dataset.osTab));
    t.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      const next = osTabs[(i + (e.key === "ArrowRight" ? 1 : osTabs.length - 1)) % osTabs.length];
      setOs(next.dataset.osTab);
      next.focus();
    });
  });
  setOs(/Windows/i.test(navigator.userAgent) ? "win" : "unix");

  // ---- the wind ---------------------------------------------------------------------------
  const wind = (() => {
    const canvas = document.getElementById("wind");
    const ctx = canvas.getContext("2d");
    const sim = { phase: 0, amp: 3, speed: 0.3, level: 0 };
    let w = 0, h = 0, color = "#3a78ae", speaking = false, onScreen = true, last = performance.now();

    const voice = (t) => {
      const phrase = Math.sin(t * 0.8) + Math.sin(t * 1.9 + 2) * 0.5;
      const syllable = Math.pow(Math.abs(Math.sin(t * 5.3 + Math.sin(t * 1.3))), 0.7);
      return Math.min(1, (phrase > -0.6 ? 1 : 0.06) * syllable * (0.55 + 0.45 * Math.sin(t * 0.7 + 1)));
    };
    const rgba = (hex, a) => {
      const n = parseInt(hex.replace("#", ""), 16);
      return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
    };
    function recolor() {
      color = getComputedStyle(root).getPropertyValue("--wind").trim() || color;
      if (reduceMotion.matches) settle();
    }
    function resize() {
      const r = canvas.getBoundingClientRect();
      if (!r.width) return;
      const dpr = Math.min(2, devicePixelRatio || 1);
      w = r.width;
      h = r.height;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (reduceMotion.matches) settle();
    }
    function render(dt, t) {
      if (!w) return;
      const target = speaking ? voice(t) : 0;
      sim.level += (target - sim.level) * Math.min(1, dt * 12);
      const amp = 3 + 24 * sim.level;
      const speed = 0.3 + (speaking ? 0.5 + 2.6 * sim.level : 0);
      sim.amp += (amp - sim.amp) * Math.min(1, dt * 4);
      sim.speed += (speed - sim.speed) * Math.min(1, dt * 4);
      sim.phase += sim.speed * dt;
      ctx.clearRect(0, 0, w, h);
      const n = Math.max(7, Math.min(15, Math.round(h / 42)));
      const energy = 0.35 + sim.level * 0.9;
      for (let i = 0; i < n; i++) {
        const y0 = h * (0.06 + (0.88 * i) / (n - 1));
        const mid = Math.abs(i - (n - 1) / 2) / ((n - 1) / 2);
        ctx.beginPath();
        for (let x = -10; x <= w + 10; x += 7) {
          const y = y0 + sim.amp * (1 - mid * 0.5) * Math.sin(x * 0.012 + sim.phase + i * 0.6) +
            sim.amp * 0.45 * Math.sin(x * 0.031 - sim.phase * 1.6 + i * 1.3);
          x === -10 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        }
        ctx.strokeStyle = rgba(color, 0.1 + 0.4 * (1 - mid) * Math.min(1, energy));
        ctx.lineWidth = 1 + (1 - mid) * 1.3;
        ctx.setLineDash([w * 0.16, w * 0.06 + i * 9]);
        ctx.lineDashOffset = -sim.phase * 70 - i * 40;
        ctx.stroke();
      }
      ctx.setLineDash([]);
    }
    // Reduced motion: no animation, a settled scene redrawn when something changes.
    function settle() {
      for (let i = 0; i < 90; i++) render(1 / 60, 2.5 + i / 60);
    }
    function frame(now) {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      if (onScreen && !document.hidden && !reduceMotion.matches) render(dt, now / 1000);
      requestAnimationFrame(frame);
    }
    new ResizeObserver(resize).observe(canvas);
    new IntersectionObserver(([e]) => (onScreen = e.isIntersecting)).observe(canvas);
    reduceMotion.addEventListener("change", () => (reduceMotion.matches ? settle() : null));
    resize();
    recolor();
    requestAnimationFrame(frame);

    const toggle = document.getElementById("wind-toggle");
    toggle?.addEventListener("click", () => {
      speaking = !speaking;
      toggle.setAttribute("aria-pressed", String(speaking));
      toggle.textContent = speaking ? "Stop the voice" : "Make the wind hear a voice";
      if (reduceMotion.matches) {
        sim.level = speaking ? 0.7 : 0;
        settle();
      }
    });
    return { recolor };
  })();

  applyTheme();
})();
