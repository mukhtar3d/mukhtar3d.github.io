/** Builds a single-file design preview from the real frontend source.
 *
 *  The markup is produced by importing the same modules the app uses and the
 *  CSS is the compiled Tailwind bundle from `npm run build`, so the preview
 *  cannot drift from the running app. Only the parts that need a live backend
 *  (fetching, routing) are replaced with static behaviour.
 */

import { readFileSync, writeFileSync, readdirSync } from "fs";

import { landingView } from "/tmp/psrc/pages/landing.js";
import { navMarkup, footerMarkup } from "/tmp/psrc/ui/nav.js";
import {
  pickCard,
  comparisonTable,
  detailModal,
} from "/tmp/psrc/ui/components.js";
import {
  costChart,
  admissionChart,
  radarChart,
  gapChart,
  scatterChart,
  timelineList,
} from "/tmp/psrc/ui/charts.js";

const plan = JSON.parse(readFileSync("/tmp/plan.json", "utf8"));

// The compiled stylesheet from the production build.
const distDir = "/home/claude/unipath/frontend/dist/assets";
const cssFile = readdirSync(distDir).find((f) => f.endsWith(".css"));
const css = readFileSync(`${distDir}/${cssFile}`, "utf8");

const money = (n) => "€" + Number(n).toLocaleString("en-IE");

const chips = [
  "IELTS 7", "SAT 1380", "GPA 3.60/4.0", "€22,000 a year",
  "computer science and artificial intelligence", "Netherlands, Germany, Italy",
]
  .map(
    (c) =>
      `<span class="rounded-full bg-slate-900/[0.04] px-3 py-1 text-xs font-medium text-slate-700 dark:bg-white/10 dark:text-slate-300">${c}</span>`
  )
  .join("");

const chartCard = (title, body) => `
  <div class="panel p-5">
    <h3 class="mb-4 text-sm font-semibold text-slate-900 dark:text-white">${title}</h3>
    ${body}
  </div>`;

const adviceLabels = {
  ielts: "Your English",
  sat: "Your SAT",
  gpa: "Your grades",
  budget: "The money",
  next_step: "Do this first",
};

const advice = Object.entries(adviceLabels)
  .filter(([k]) => plan.advice?.[k])
  .map(
    ([k, label]) => `
    <div class="border-t border-slate-900/[0.07] py-4 first:border-t-0 first:pt-0 dark:border-white/10">
      <h3 class="text-sm font-semibold text-slate-900 dark:text-white">${label}</h3>
      <p class="mt-1.5 text-[15px] leading-relaxed text-slate-600 dark:text-slate-400">${plan.advice[k]}</p>
    </div>`
  )
  .join("");

const resultsMarkup = `
  <div class="mx-auto max-w-6xl px-5 py-12 sm:px-8">
    <div class="flex flex-wrap items-start justify-between gap-4">
      <div class="max-w-2xl">
        <h2 class="text-section font-semibold tracking-tight text-slate-900 dark:text-white">
          Your four universities
        </h2>
        <div class="mt-3 flex flex-wrap gap-1.5">${chips}</div>
      </div>
      <div class="flex gap-2">
        <button type="button" class="btn btn-ghost btn-sm">Download plan</button>
        <button type="button" class="btn btn-ghost btn-sm" onclick="window.print()">Print</button>
        <a href="#top" class="btn btn-primary btn-sm">Change my answers</a>
      </div>
    </div>

    <p class="mt-6 max-w-3xl text-[17px] leading-relaxed text-slate-700 dark:text-slate-300">
      ${plan.summary}
    </p>

    ${
      plan.budget_warning
        ? `<div class="mt-5 flex gap-3 rounded-xl bg-amber-50 p-4 text-sm leading-relaxed text-amber-900 dark:bg-amber-500/10 dark:text-amber-200">
             <span>${plan.budget_warning}</span></div>`
        : ""
    }

    <p class="mt-4 text-xs text-slate-500">
      Static preview rendered from a real API response. In the running app this line names the model
      that made the choice and how many universities it chose from.
    </p>

    <div class="mt-10 grid gap-5 sm:grid-cols-2">
      ${plan.picks.map((p, i) => pickCard(p, i)).join("")}
    </div>

    <section class="mt-14">
      <h2 class="text-xl font-semibold tracking-tight text-slate-900 dark:text-white">Side by side</h2>
      <p class="mt-1.5 text-sm text-slate-500">Every figure here comes from the university database, not the model.</p>
      <div class="mt-5">${comparisonTable(plan.comparison, plan.picks)}</div>
    </section>

    <section class="mt-14">
      <h2 class="text-xl font-semibold tracking-tight text-slate-900 dark:text-white">The numbers</h2>
      <div class="mt-5 grid gap-5 lg:grid-cols-2">
        ${chartCard("Yearly cost against your budget", costChart(plan.charts.cost))}
        ${chartCard("Estimated chance of admission", admissionChart(plan.charts.admission))}
        ${chartCard("How your profile sits against each bar", radarChart(plan.charts.radar))}
        ${chartCard("Budget gap", gapChart(plan.charts.gaps))}
        <div class="lg:col-span-2">${chartCard("Cost against odds", scatterChart(plan.charts.scatter))}</div>
      </div>
    </section>

    <section class="mt-14">
      <h2 class="text-xl font-semibold tracking-tight text-slate-900 dark:text-white">What to do, and when</h2>
      <p class="mt-1.5 text-sm text-slate-500">Worked backwards from the deadline you entered.</p>
      <div class="mt-5">${timelineList(plan.timeline)}</div>
    </section>

    <section class="mt-14">
      <h2 class="text-xl font-semibold tracking-tight text-slate-900 dark:text-white">Reading your profile</h2>
      <div class="mt-5"><div class="panel p-5">${advice}</div></div>
    </section>
  </div>`;

const modals = plan.picks.map((p) => detailModal(p));

const page = `<!doctype html>
<html lang="en" class="h-full">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>UniPath — design preview</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,300..800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />
<style>
${css}
</style>
</head>
<body class="h-full">
<div id="top"></div>
${navMarkup()}

<main>
  <div class="mx-auto max-w-6xl px-5 pt-5 sm:px-8">
    <div class="rounded-xl bg-sky-50 px-4 py-3 text-sm text-sky-900 ring-1 ring-sky-500/20 dark:bg-sky-500/10 dark:text-sky-200 dark:ring-sky-400/20">
      Static design preview. The landing page and a real results page are stacked below so you can see both.
      Photos are absent because image lookup was switched off when this response was captured — the app draws
      these gradient placeholders whenever the database has no picture.
    </div>
  </div>

  ${landingView()}

  <div class="mx-auto mt-16 max-w-6xl border-t border-slate-900/[0.07] px-5 pt-10 sm:px-8 dark:border-white/10">
    <p class="font-mono text-xs text-sky-600 dark:text-sky-400">results view</p>
  </div>
  ${resultsMarkup}
</main>

${footerMarkup()}

<script>
(function () {
  var MODALS = ${JSON.stringify(modals)};

  // Theme toggle
  var toggle = document.getElementById("theme-toggle");
  var SUN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" class="h-4 w-4"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M4.9 4.9l1.4 1.4m11.4 11.4l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4" stroke-linecap="round"/></svg>';
  var MOON = toggle.innerHTML;
  function apply(dark) {
    document.documentElement.classList.toggle("dark", dark);
    toggle.innerHTML = dark ? SUN : MOON;
    try { localStorage.setItem("unipath:theme", dark ? "dark" : "light"); } catch (e) {}
  }
  var stored = null;
  try { stored = localStorage.getItem("unipath:theme"); } catch (e) {}
  apply(stored ? stored === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches);
  toggle.addEventListener("click", function () {
    apply(!document.documentElement.classList.contains("dark"));
  });

  // The nav button: centred at the top, docked to the right once you scroll.
  var slot = document.getElementById("cta-slot");
  var cta = document.getElementById("cta");
  var links = document.getElementById("nav-links");
  function setDocked(docked) {
    if (slot.dataset.docked === String(docked)) return;
    var first = slot.getBoundingClientRect();
    slot.dataset.docked = String(docked);
    slot.classList.toggle("left-1/2", !docked);
    slot.classList.toggle("-translate-x-1/2", !docked);
    slot.classList.toggle("right-14", docked);
    slot.classList.toggle("sm:right-32", docked);
    cta.classList.toggle("btn-sm", docked);
    if (links) links.classList.toggle("sm:hidden", docked);
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    var last = slot.getBoundingClientRect();
    var dx = first.left - last.left;
    if (Math.abs(dx) < 1) return;
    slot.animate(
      [{ transform: "translate(" + dx + "px, 0)" }, { transform: "translate(0,0)" }],
      { duration: 420, easing: "cubic-bezier(0.16, 1, 0.3, 1)" }
    );
  }
  function sync() { setDocked(window.scrollY > 24); }
  sync();
  window.addEventListener("scroll", sync, { passive: true });

  // Detail modal + lightbox
  function closeModal() {
    var h = document.getElementById("modal-host");
    if (h) h.remove();
    if (!document.getElementById("lightbox-host")) document.body.style.overflow = "";
  }
  function closeLightbox() {
    var h = document.getElementById("lightbox-host");
    if (h) h.remove();
    if (!document.getElementById("modal-host")) document.body.style.overflow = "";
  }

  document.addEventListener("click", function (event) {
    var open = event.target.closest("[data-open-detail]");
    if (open) {
      var host = document.createElement("div");
      host.id = "modal-host";
      host.innerHTML = MODALS[Number(open.dataset.openDetail)];
      document.body.appendChild(host);
      document.body.style.overflow = "hidden";
      var close = host.querySelector("[data-close-modal]");
      if (close) close.focus();
      return;
    }
    if (event.target.closest("[data-close-modal]")) { closeModal(); return; }
    var backdrop = event.target.closest("[data-modal-backdrop]");
    if (backdrop && !event.target.closest("[data-modal-panel]")) { closeModal(); return; }
    if (event.target.closest("[data-close-lightbox]")) { closeLightbox(); return; }

    // Internal app links do nothing useful in a static preview.
    var link = event.target.closest('a[href^="#/"]');
    if (link) {
      event.preventDefault();
      document.querySelector("main").scrollIntoView({ behavior: "smooth" });
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") { closeLightbox(); closeModal(); }
  });
})();
</script>
</body>
</html>`;

writeFileSync("/mnt/user-data/outputs/unipath-design-preview.html", page, "utf8");
console.log("wrote preview:", (page.length / 1024).toFixed(0) + "KB");
console.log("css inlined:", (css.length / 1024).toFixed(0) + "KB from", cssFile);
console.log("picks:", plan.picks.length, "| modals:", modals.length);
