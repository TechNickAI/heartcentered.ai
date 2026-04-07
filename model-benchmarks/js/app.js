/**
 * HeartCentered AI — Model Benchmarks
 * Vanilla JS: sort, filter, search, render from model-data.json
 */

(function () {
    "use strict";

    function esc(s) {
        return String(s ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    let models = [];
    let sortKey = "eq_elo";
    let sortDir = "desc";
    let searchQuery = "";
    let activeFilters = new Set();

    const capabilities = [
        "tool_use",
        "reasoning",
        "vision",
        "web_search",
        "structured_output",
    ];

    const capLabels = {
        tool_use: "Tools",
        reasoning: "Reasoning",
        vision: "Vision",
        web_search: "Web Search",
        structured_output: "Structured",
    };

    async function init() {
        const tbody = document.getElementById("table-body");
        const cards = document.getElementById("mobile-cards");
        tbody.innerHTML = `<tr><td colspan="9" class="text-center py-8 text-of-muted">Loading models...</td></tr>`;
        cards.innerHTML = `<div class="text-center py-8 text-of-muted">Loading models...</div>`;

        try {
            const resp = await fetch("data/model-data.json");
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data = await resp.json();
            models = data.models;

            document.getElementById("last-updated").textContent = new Date(
                data.generated
            ).toLocaleDateString("en-US", {
                month: "short",
                day: "numeric",
                year: "numeric",
            });

            renderFilters();
            bindEvents();
            render();
        } catch (err) {
            tbody.innerHTML = `<tr><td colspan="9" class="text-center py-8 text-of-muted">Failed to load model data. Try refreshing the page.</td></tr>`;
            cards.innerHTML = `<div class="text-center py-8 text-of-muted">Failed to load model data. Try refreshing the page.</div>`;
        }
    }

    function renderFilters() {
        const container = document.getElementById("capability-filters");
        container.innerHTML = capabilities
            .map(
                (cap) =>
                    `<button class="filter-btn" data-cap="${cap}">${capLabels[cap]}</button>`
            )
            .join("");
    }

    function bindEvents() {
        document.getElementById("search-input").addEventListener("input", (e) => {
            searchQuery = e.target.value.toLowerCase();
            render();
        });

        document.getElementById("capability-filters").addEventListener("click", (e) => {
            const btn = e.target.closest(".filter-btn");
            if (!btn) return;
            const cap = btn.dataset.cap;
            if (activeFilters.has(cap)) {
                activeFilters.delete(cap);
                btn.classList.remove("active");
            } else {
                activeFilters.add(cap);
                btn.classList.add("active");
            }
            render();
        });

        document.querySelectorAll("th.sortable").forEach((th) => {
            th.addEventListener("click", () => {
                const key = th.dataset.sort;
                if (sortKey === key) {
                    sortDir = sortDir === "desc" ? "asc" : "desc";
                } else {
                    sortKey = key;
                    sortDir = key === "name" ? "asc" : "desc";
                }
                updateSortIndicators();
                render();
            });
        });
    }

    function updateSortIndicators() {
        document.querySelectorAll("th.sortable").forEach((th) => {
            th.classList.remove("sort-asc", "sort-desc");
            if (th.dataset.sort === sortKey) {
                th.classList.add(sortDir === "asc" ? "sort-asc" : "sort-desc");
            }
        });
    }

    function getSortValue(model, key) {
        switch (key) {
            case "name":
                return model.name.toLowerCase();
            case "reasoning":
                return model.scores?.reasoning ?? -1;
            case "coding":
                return model.scores?.coding ?? -1;
            case "agentic":
                return model.scores?.agentic ?? -1;
            case "eq_elo":
                return model.benchmarks?.eq_bench?.elo ?? -1;
            case "arena_elo":
                return model.benchmarks?.arena?.elo ?? -1;
            case "speed":
                return model.speed?.output_tokens_per_sec ?? -1;
            case "cost":
                return model.pricing?.blended_per_m ?? 9999;
            case "context":
                return model.context_window ?? -1;
            default:
                return 0;
        }
    }

    function filterModels() {
        return models.filter((m) => {
            if (searchQuery) {
                const hay = `${m.name} ${m.provider} ${m.id}`.toLowerCase();
                if (!hay.includes(searchQuery)) return false;
            }
            for (const cap of activeFilters) {
                if (!m.capabilities?.[cap]) return false;
            }
            return true;
        });
    }

    function sortModels(list) {
        return list.sort((a, b) => {
            const va = getSortValue(a, sortKey);
            const vb = getSortValue(b, sortKey);

            // Null sentinels always sort to bottom
            const aNull = sortKey === "cost" ? va === 9999 : va === -1;
            const bNull = sortKey === "cost" ? vb === 9999 : vb === -1;
            if (aNull && !bNull) return 1;
            if (!aNull && bNull) return -1;
            if (aNull && bNull) return 0;

            if (sortKey === "name") {
                return sortDir === "asc" ? va.localeCompare(vb) : vb.localeCompare(va);
            }
            // For cost, lower is better — flip sort
            if (sortKey === "cost") {
                return sortDir === "desc" ? va - vb : vb - va;
            }
            return sortDir === "desc" ? vb - va : va - vb;
        });
    }

    function render() {
        const filtered = sortModels(filterModels());
        document.getElementById("model-count").textContent =
            `${filtered.length} model${filtered.length !== 1 ? "s" : ""}`;

        updateSortIndicators();
        renderTable(filtered);
        renderCards(filtered);
    }

    function scoreHtml(value, max) {
        if (value == null) return `<span class="score-na">—</span>`;
        const pct = Math.min((value / max) * 100, 100);
        const tier = pct >= 70 ? "score-high" : pct >= 45 ? "score-mid" : "score-low";
        return `
      <span class="score-bar ${tier}">
        <span class="score-bar-bg"><span class="score-bar-fill" style="width:${pct}%"></span></span>
        <span class="score-value">${Math.round(value)}</span>
      </span>`;
    }

    function eloHtml(value, note) {
        if (value == null) return `<span class="score-na">—</span>`;
        const noteHtml = note ? `<span class="data-note" title="${note}">*</span>` : "";
        return `<span class="score-value">${Math.round(value)}</span>${noteHtml}`;
    }

    function eqHtml(model) {
        const eq = model.benchmarks?.eq_bench;
        if (!eq || !eq.elo) return `<span class="score-na">—</span>`;
        const note = eq.note
            ? `<span class="data-note" title="${esc(eq.note)}">*</span>`
            : "";
        const traits = [
            ["Empathy", eq.empathy],
            ["Social IQ", eq.social_iq],
            ["Insight", eq.insight],
            ["Humanlike", eq.humanlike],
            ["Warm", eq.warm],
        ]
            .filter(([, v]) => v != null)
            .map(([k, v]) => `${k}: ${v}`)
            .join("  ·  ");

        return `
      <span class="eq-detail">
        <span class="score-value">${Math.round(eq.elo)}</span>${note}
        ${traits ? `<span class="eq-tooltip">${traits}</span>` : ""}
      </span>`;
    }

    function costHtml(pricing) {
        const blended = pricing?.blended_per_m;
        if (blended === 0 || blended == null) {
            if (pricing?.input_per_m === 0)
                return `<span class="cost-free">FREE</span>`;
            return `<span class="score-na">—</span>`;
        }
        const inp = pricing?.input_per_m;
        const out = pricing?.output_per_m;
        const tooltip =
            inp != null && out != null
                ? `Input: $${esc(inp)}/M · Output: $${esc(out)}/M`
                : "";
        return `<span class="cost-detail" title="${tooltip}"><span class="cost-value">$${blended < 1 ? blended.toFixed(2) : blended.toFixed(1)}</span></span>`;
    }

    function speedHtml(speed) {
        const tps = speed?.output_tokens_per_sec;
        if (!tps) return `<span class="score-na">—</span>`;
        const cls = tps >= 70 ? "speed-fast" : tps >= 40 ? "speed-mid" : "";
        return `<span class="speed-value ${cls}">${Math.round(tps)} t/s</span>`;
    }

    function contextHtml(ctx) {
        if (!ctx) return `<span class="score-na">—</span>`;
        return `<span class="context-value">${Math.round(ctx / 1000)}K</span>`;
    }

    function arenaHtml(model) {
        const arena = model.benchmarks?.arena;
        if (!arena || !arena.elo) return `<span class="score-na">—</span>`;
        const note = arena.note
            ? `<span class="data-note" title="${esc(arena.note)}">*</span>`
            : "";
        return `<span class="score-value">${arena.elo}</span>${note}`;
    }

    function renderTable(list) {
        const tbody = document.getElementById("table-body");
        if (!list.length) {
            tbody.innerHTML = `<tr><td colspan="9" class="text-center py-8 text-of-muted">No models match your filters.</td></tr>`;
            return;
        }
        tbody.innerHTML = list
            .map(
                (m, i) => `
      <tr style="animation-delay: ${i * 0.03}s">
        <td>
          <a href="https://openrouter.ai/${esc(m.id)}" target="_blank" rel="noopener" class="model-link">
            <div class="model-name">${esc(m.name)}</div>
            <div class="model-provider">${esc(m.provider)}${m.notes ? ` <span class="data-note" title="${esc(m.notes)}">*</span>` : ""}</div>
          </a>
        </td>
        <td class="score-cell">${scoreHtml(m.scores?.reasoning, 100)}</td>
        <td class="score-cell">${scoreHtml(m.scores?.coding, 100)}</td>
        <td class="score-cell">${scoreHtml(m.scores?.agentic, 100)}</td>
        <td class="score-cell eq-cell">${eqHtml(m)}</td>
        <td class="score-cell">${arenaHtml(m)}</td>
        <td class="score-cell">${speedHtml(m.speed)}</td>
        <td class="score-cell">${costHtml(m.pricing)}</td>
        <td class="score-cell">${contextHtml(m.context_window)}</td>
      </tr>`
            )
            .join("");
    }

    function renderCards(list) {
        const container = document.getElementById("mobile-cards");
        if (!list.length) {
            container.innerHTML = `<div class="text-center py-8 text-of-muted">No models match your filters.</div>`;
            return;
        }
        container.innerHTML = list
            .map(
                (m, i) => `
      <div class="model-card" style="animation-delay: ${i * 0.05}s">
        <div class="flex items-center justify-between">
          <a href="https://openrouter.ai/${esc(m.id)}" target="_blank" rel="noopener" class="model-link">
            <div class="model-name">${esc(m.name)}</div>
            <div class="model-provider">${esc(m.provider)}${m.notes ? ` <span class="data-note" title="${esc(m.notes)}">*</span>` : ""}</div>
          </a>
          <div class="text-right">
            ${costHtml(m.pricing)}
          </div>
        </div>
        <div class="card-scores">
          <div class="card-score-item">
            <div class="card-score-label">Reasoning</div>
            <div class="card-score-value ${scoreTier(m.scores?.reasoning)}">${m.scores?.reasoning != null ? Math.round(m.scores.reasoning) : "—"}</div>
          </div>
          <div class="card-score-item">
            <div class="card-score-label">Coding</div>
            <div class="card-score-value ${scoreTier(m.scores?.coding)}">${m.scores?.coding != null ? Math.round(m.scores.coding) : "—"}</div>
          </div>
          <div class="card-score-item">
            <div class="card-score-label">Agentic</div>
            <div class="card-score-value ${scoreTier(m.scores?.agentic)}">${m.scores?.agentic != null ? Math.round(m.scores.agentic) : "—"}</div>
          </div>
          <div class="card-score-item">
            <div class="card-score-label">EQ</div>
            <div class="card-score-value">${m.benchmarks?.eq_bench?.elo ? Math.round(m.benchmarks.eq_bench.elo) : "—"}</div>
          </div>
          <div class="card-score-item">
            <div class="card-score-label">Chat</div>
            <div class="card-score-value">${m.benchmarks?.arena?.elo ?? "—"}</div>
          </div>
          <div class="card-score-item">
            <div class="card-score-label">Speed</div>
            <div class="card-score-value">${m.speed?.output_tokens_per_sec ? Math.round(m.speed.output_tokens_per_sec) + " t/s" : "—"}</div>
          </div>
        </div>
        <div class="card-meta">
          <span>Context: ${m.context_window ? Math.round(m.context_window / 1000) + "K" : "—"}</span>
          <span>${m.speed?.ttft_seconds ? "TTFT: " + m.speed.ttft_seconds + "s" : ""}</span>
        </div>
      </div>`
            )
            .join("");
    }

    function scoreTier(val) {
        if (val == null) return "";
        if (val >= 70) return "score-high";
        if (val >= 45) return "score-mid";
        return "score-low";
    }

    init();
})();
