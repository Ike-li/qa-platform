/**
 * Dashboard.js - Chart.js charts and live data refresh for QA Platform dashboard.
 *
 * Relies on the global Chart object loaded from CDN before this script.
 */

(function () {
    "use strict";

    // -----------------------------------------------------------------------
    // Chart instances (kept so we can destroy before re-render)
    // -----------------------------------------------------------------------

    let passRateChartInstance = null;
    let trendChartInstance = null;
    let queueRefreshTimer = null;

    // Current state
    let currentProjectId = null;
    let currentGranularity = "daily";

    // -----------------------------------------------------------------------
    // Colour palette
    // -----------------------------------------------------------------------

    const STATUS_COLORS = {
        passed:  "#28a745",   // green
        failed:  "#dc3545",   // red
        skipped: "#ffc107",   // yellow
        error:   "#fd7e14",   // orange
    };

    // -----------------------------------------------------------------------
    // Utility helpers
    // -----------------------------------------------------------------------

    /**
     * Format elapsed seconds into a human-readable string.
     * @param {number|null} seconds
     * @returns {string}
     */
    function formatElapsed(seconds) {
        if (seconds === null || seconds === undefined) return "--";
        const s = Math.round(Number(seconds));
        if (s < 60) return s + "s";
        const m = Math.floor(s / 60);
        const rem = s % 60;
        if (m < 60) return m + "m " + rem + "s";
        const h = Math.floor(m / 60);
        const mRem = m % 60;
        return h + "h " + mRem + "m";
    }

    /**
     * Map a queue status string to a Bootstrap badge class.
     */
    function statusBadgeClass(status) {
        switch (status) {
            case "running":   return "bg-primary";
            case "pending":   return "bg-warning text-dark";
            case "cloned":    return "bg-info text-dark";
            case "executed":  return "bg-secondary";
            default:          return "bg-secondary";
        }
    }

    /**
     * Show or hide the loading overlay.
     */
    function setLoading(on) {
        const el = document.getElementById("spinner-overlay");
        if (!el) return;
        if (on) {
            el.classList.add("active");
        } else {
            el.classList.remove("active");
        }
    }

    /**
     * Generic fetch wrapper that returns parsed JSON or null on error.
     */
    async function fetchJSON(url) {
        try {
            const resp = await fetch(url);
            if (!resp.ok) return null;
            return await resp.json();
        } catch (err) {
            console.error("[dashboard] fetch error:", url, err);
            return null;
        }
    }

    // -----------------------------------------------------------------------
    // 1. Pass Rate doughnut chart
    // -----------------------------------------------------------------------

    /**
     * Render (or re-render) the pass rate doughnut chart.
     * @param {Object} data - { pass_rate, total_tests, counts: { passed, failed, skipped, error } }
     */
    function renderPassRateChart(data) {
        const canvas = document.getElementById("passRateChart");
        if (!canvas) return;

        // Destroy previous instance
        if (passRateChartInstance) {
            passRateChartInstance.destroy();
            passRateChartInstance = null;
        }

        const counts = data.counts || {};
        const labels = ["Passed", "Failed", "Skipped", "Error"];
        const values = [
            counts.passed  || 0,
            counts.failed  || 0,
            counts.skipped || 0,
            counts.error   || 0,
        ];
        const colors = [
            STATUS_COLORS.passed,
            STATUS_COLORS.failed,
            STATUS_COLORS.skipped,
            STATUS_COLORS.error,
        ];

        // If all zero, show a single grey slice so the chart is not empty
        const hasData = values.some(function (v) { return v > 0; });

        passRateChartInstance = new Chart(canvas, {
            type: "doughnut",
            data: {
                labels: labels,
                datasets: [{
                    data: hasData ? values : [1],
                    backgroundColor: hasData ? colors : ["#dee2e6"],
                    borderWidth: 2,
                    borderColor: "#fff",
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                cutout: "65%",
                plugins: {
                    legend: {
                        position: "bottom",
                        labels: {
                            padding: 12,
                            usePointStyle: true,
                            pointStyleWidth: 10,
                        },
                    },
                    tooltip: {
                        callbacks: {
                            label: function (context) {
                                if (!hasData) return "No data";
                                var total = context.dataset.data.reduce(function (a, b) { return a + b; }, 0);
                                var val = context.parsed;
                                var pct = total > 0 ? ((val / total) * 100).toFixed(1) : 0;
                                return context.label + ": " + val + " (" + pct + "%)";
                            },
                        },
                    },
                },
            },
        });

        // Update badge
        var badge = document.getElementById("passRateBadge");
        if (badge) {
            badge.textContent = data.pass_rate + "%";
            badge.className = "badge " + (data.pass_rate >= 80 ? "bg-success" : data.pass_rate >= 50 ? "bg-warning text-dark" : "bg-danger");
        }

        // Summary text
        var summary = document.getElementById("passRateSummary");
        if (summary) {
            summary.textContent =
                "Total: " + data.total_tests +
                " | Passed: " + (counts.passed || 0) +
                " | Failed: " + (counts.failed || 0) +
                " | Skipped: " + (counts.skipped || 0) +
                " | Error: " + (counts.error || 0);
        }
    }

    // -----------------------------------------------------------------------
    // 2. Trend line chart
    // -----------------------------------------------------------------------

    /**
     * Render (or re-render) the trend line chart.
     * @param {Object} data   - { labels: string[], pass_rates: number[] }
     * @param {string} granularity - "daily" | "weekly" | "monthly"
     */
    function renderTrendChart(data, granularity) {
        var canvas = document.getElementById("trendChart");
        if (!canvas) return;

        if (trendChartInstance) {
            trendChartInstance.destroy();
            trendChartInstance = null;
        }

        var labels = data.labels || [];
        var rates  = data.pass_rates || [];

        trendChartInstance = new Chart(canvas, {
            type: "line",
            data: {
                labels: labels,
                datasets: [{
                    label: "Pass Rate (%)",
                    data: rates,
                    borderColor: "#0d6efd",
                    backgroundColor: "rgba(13, 110, 253, .08)",
                    fill: true,
                    tension: 0.3,
                    pointRadius: labels.length > 30 ? 0 : 3,
                    pointHoverRadius: 5,
                    borderWidth: 2,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                interaction: {
                    mode: "index",
                    intersect: false,
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        max: 100,
                        ticks: {
                            callback: function (value) { return value + "%"; },
                        },
                        title: {
                            display: true,
                            text: "Pass Rate",
                        },
                    },
                    x: {
                        title: {
                            display: true,
                            text: granularity.charAt(0).toUpperCase() + granularity.slice(1),
                        },
                        ticks: {
                            maxRotation: 45,
                            autoSkip: true,
                            maxTicksLimit: 20,
                        },
                    },
                },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: function (context) {
                                return "Pass Rate: " + context.parsed.y + "%";
                            },
                        },
                    },
                },
            },
        });
    }

    // -----------------------------------------------------------------------
    // 3. Execution queue table
    // -----------------------------------------------------------------------

    /**
     * Fetch queue data from API and update the queue table.
     */
    async function refreshQueue() {
        var data = await fetchJSON("/dashboard/api/dashboard/queue");
        var tbody = document.getElementById("queueBody");
        var badge = document.getElementById("queueCountBadge");
        if (!data || !tbody) return;

        var queue = data.queue || [];
        if (badge) badge.textContent = queue.length;

        if (queue.length === 0) {
            tbody.innerHTML =
                '<tr><td colspan="6" class="text-center text-muted py-4">No active executions</td></tr>';
            return;
        }

        var html = "";
        for (var i = 0; i < queue.length; i++) {
            var item = queue[i];
            html += "<tr>";
            html += '<td><a href="' + (item.detail_url || "#") + '">' + (item.id || "--") + "</a></td>";
            html += "<td>" + escapeHtml(item.project_name || "--") + "</td>";
            html += "<td>" + escapeHtml(item.suite_name || "--") + "</td>";
            html += '<td><span class="badge badge-status ' + statusBadgeClass(item.status) + '">' +
                    escapeHtml(item.status || "--") + "</span></td>";
            html += "<td>" + escapeHtml(item.stage || "--") + "</td>";
            html += "<td>" + formatElapsed(item.elapsed_seconds) + "</td>";
            html += "</tr>";
        }
        tbody.innerHTML = html;
    }

    // -----------------------------------------------------------------------
    // 4. Recent failures table
    // -----------------------------------------------------------------------

    /**
     * Fetch failure data from API and update the failures table.
     */
    async function refreshFailures() {
        if (!currentProjectId) return;

        var url = "/dashboard/api/dashboard/failures?project_id=" + currentProjectId + "&limit=20";
        var data = await fetchJSON(url);
        var tbody = document.getElementById("failuresBody");
        var badge = document.getElementById("failureCountBadge");
        if (!data || !tbody) return;

        var failures = data.failures || [];
        if (badge) badge.textContent = failures.length;

        if (failures.length === 0) {
            tbody.innerHTML =
                '<tr><td colspan="4" class="text-center text-muted py-4">No recent failures</td></tr>';
            return;
        }

        var html = "";
        for (var i = 0; i < failures.length; i++) {
            var f = failures[i];
            html += "<tr>";

            // Test name with link to execution
            html += "<td>";
            if (f.execution_url) {
                html += '<a href="' + f.execution_url + '" title="' + escapeHtml(f.test_name || "") + '">' +
                        escapeHtml(f.test_name || "--") + "</a>";
            } else {
                html += escapeHtml(f.test_name || "--");
            }
            html += "</td>";

            // Suite / file path
            html += '<td class="small">' + escapeHtml(f.file_path || "--") + "</td>";

            // Error snippet (truncated)
            html += '<td class="error-snippet" title="' + escapeHtml(f.error_msg || "") + '">' +
                    escapeHtml(f.error_msg || "--") + "</td>";

            // Allure report link
            html += "<td>";
            if (f.allure_url) {
                html += '<a href="' + f.allure_url + '" target="_blank" rel="noopener" ' +
                        'class="btn btn-sm btn-outline-primary"><i class="bi bi-file-earmark-bar-graph"></i> Allure</a>';
            } else {
                html += '<span class="text-muted small">N/A</span>';
            }
            html += "</td>";

            html += "</tr>";
        }
        tbody.innerHTML = html;
    }

    // -----------------------------------------------------------------------
    // 5. Main orchestrator
    // -----------------------------------------------------------------------

    /**
     * Load all dashboard data for the given project.
     * @param {number|string} projectId
     */
    async function loadDashboard(projectId) {
        if (!projectId) return;
        currentProjectId = projectId;

        var grid    = document.getElementById("dashboardGrid");
        var noMsg   = document.getElementById("noProjectMsg");
        if (grid)  grid.style.display  = "";
        if (noMsg) noMsg.style.display = "none";

        setLoading(true);

        // Fire requests in parallel
        var passRateUrl = "/dashboard/api/dashboard/pass-rate?project_id=" + projectId + "&days=7";
        var trendUrl    = "/dashboard/api/dashboard/trends?project_id=" + projectId +
                          "&granularity=" + currentGranularity + "&days=30";

        var results = await Promise.all([
            fetchJSON(passRateUrl),
            fetchJSON(trendUrl),
            refreshQueue(),
            refreshFailures(),
        ]);

        var passRateData = results[0];
        var trendData    = results[1];

        if (passRateData && !passRateData.error) {
            renderPassRateChart(passRateData);
        }
        if (trendData && !trendData.error) {
            renderTrendChart(trendData, currentGranularity);
        }

        setLoading(false);
    }

    // -----------------------------------------------------------------------
    // HTML escaping (XSS safety)
    // -----------------------------------------------------------------------

    function escapeHtml(str) {
        if (!str) return "";
        var div = document.createElement("div");
        div.appendChild(document.createTextNode(str));
        return div.innerHTML;
    }

    // -----------------------------------------------------------------------
    // Event listeners & auto-refresh
    // -----------------------------------------------------------------------

    document.addEventListener("DOMContentLoaded", function () {

        // --- Project filter change ---
        var projectSelect = document.getElementById("projectFilter");
        if (projectSelect) {
            projectSelect.addEventListener("change", function () {
                var pid = this.value;
                if (!pid) {
                    // Hide grid, show placeholder
                    var grid  = document.getElementById("dashboardGrid");
                    var noMsg = document.getElementById("noProjectMsg");
                    if (grid)  grid.style.display  = "none";
                    if (noMsg) noMsg.style.display = "";
                    stopQueueRefresh();
                    return;
                }
                loadDashboard(pid);
                startQueueRefresh();
            });
        }

        // --- Granularity toggle ---
        var toggleBtns = document.querySelectorAll(".granularity-toggle .btn");
        toggleBtns.forEach(function (btn) {
            btn.addEventListener("click", function () {
                // Update active state
                toggleBtns.forEach(function (b) { b.classList.remove("active"); });
                this.classList.add("active");

                currentGranularity = this.getAttribute("data-granularity") || "daily";
                if (currentProjectId) {
                    loadDashboard(currentProjectId);
                }
            });
        });

        // --- Auto-select first project if only one exists ---
        if (projectSelect && projectSelect.options.length === 2) {
            projectSelect.selectedIndex = 1;
            projectSelect.dispatchEvent(new Event("change"));
        }
    });

    // -----------------------------------------------------------------------
    // Auto-refresh queue every 10 seconds
    // -----------------------------------------------------------------------

    function startQueueRefresh() {
        stopQueueRefresh();
        queueRefreshTimer = setInterval(refreshQueue, 10000);
    }

    function stopQueueRefresh() {
        if (queueRefreshTimer) {
            clearInterval(queueRefreshTimer);
            queueRefreshTimer = null;
        }
    }

})();
