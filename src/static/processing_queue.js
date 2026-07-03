const QUEUE_JOBS_URL = "/api/processing-queue/jobs";
const QUEUE_PROCESS_NEXT_URL = "/api/processing-queue/process-next";
const QUEUE_RESUME_URL = "/api/processing-queue/resume";
const QUEUE_RETRY_SUMMARY_FAILED_URL = "/api/processing-queue/summary-pipeline/retry-failed";
const QUEUE_CLEAR_SUMMARY_COMPLETED_URL = "/api/processing-queue/summary-pipeline/clear-completed";
const QUEUE_CLEAR_TRANSCRIPTION_COMPLETED_URL = "/api/processing-queue/clear-completed/transcribe";
const QUEUE_CLEAR_ALL_COMPLETED_URL = "/api/processing-queue/clear-completed/all";
const QUEUE_CLEAR_FAILED_URL = "/api/processing-queue/clear-failed";
const QUEUE_HISTORY_ONLY_NOTE = "This only clears queue history. It does not delete recordings, transcripts, or summaries.";

const qs = (selector) => document.querySelector(selector);
const showEl = (el) => el?.classList.remove("d-none");
const hideEl = (el) => el?.classList.add("d-none");

function queueEscapeHtml(text) {
    return (text || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

function statusBadge(status) {
    const classes = {
        pending: "bg-secondary-subtle text-secondary-emphasis",
        running: "bg-primary-subtle text-primary-emphasis",
        completed: "bg-success-subtle text-success-emphasis",
        failed: "bg-danger-subtle text-danger-emphasis",
        skipped: "bg-warning-subtle text-warning-emphasis",
    };
    return `<span class="badge ${classes[status] || "bg-light text-dark"}">${queueEscapeHtml(status)}</span>`;
}

function showQueueAlert(className, message) {
    const alert = qs("#queue-alert");
    if (!alert) return;
    alert.className = `alert ${className}`;
    alert.innerHTML = message;
    showEl(alert);
}

function jobProviderLabel(job) {
    if (job.job_type === "transcribe") {
        return job.engine || "whisper";
    }
    if (job.summary_provider === "local") {
        return `Local AI / Ollama${job.summary_model ? ` / ${job.summary_model}` : ""}`;
    }
    return "Gemini";
}

function renderCounts(counts) {
    qs("#queue-count-pending").textContent = counts.pending || 0;
    qs("#queue-count-running").textContent = counts.running || 0;
    qs("#queue-count-completed").textContent = counts.completed || 0;
    qs("#queue-count-failed").textContent = counts.failed || 0;
}

function renderJobs(jobs) {
    const table = qs("#queue-table");
    const body = qs("#queue-table-body");
    const empty = qs("#queue-empty");
    if (!jobs.length) {
        body.innerHTML = "";
        hideEl(table);
        showEl(empty);
        return;
    }
    body.innerHTML = jobs.map(job => {
        const provider = jobProviderLabel(job);
        const error = job.error ? `<span class="text-danger queue-error">${queueEscapeHtml(job.error)}</span>` : "";
        return `
            <tr>
                <td>${statusBadge(job.status)}</td>
                <td>${queueEscapeHtml(job.job_type)}</td>
                <td>
                    <a href="/?recording=${encodeURIComponent(job.recording_name)}">${queueEscapeHtml(job.recording_title || job.recording_name)}</a>
                    <div class="small text-muted">${queueEscapeHtml(job.recording_name)}</div>
                </td>
                <td>${queueEscapeHtml(provider)}</td>
                <td>${job.attempts || 0}</td>
                <td class="small text-muted">${queueEscapeHtml(job.updated_at || "")}</td>
                <td>${error}</td>
            </tr>`;
    }).join("");
    hideEl(empty);
    showEl(table);
}

async function loadQueue() {
    const loading = qs("#queue-loading");
    const status = qs("#queue-status-filter")?.value || "";
    showEl(loading);
    try {
        const res = await fetch(`${QUEUE_JOBS_URL}?status=${encodeURIComponent(status)}`);
        const data = await res.json();
        if (!res.ok || !data.ok) {
            throw new Error(data.detail || data.error || "Failed to load processing queue");
        }
        renderCounts(data.counts || {});
        renderJobs(data.jobs || []);
    } catch (err) {
        showQueueAlert("alert-danger", `<i class="bi bi-exclamation-triangle me-1"></i>${queueEscapeHtml(err.message)}`);
    } finally {
        hideEl(loading);
    }
}

async function processQueue(url, maxJobs, button) {
    const original = button?.innerHTML;
    if (button) {
        button.disabled = true;
        button.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Working';
    }
    try {
        const res = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ max_jobs: maxJobs, max_retries: 1, reset_running: url === QUEUE_RESUME_URL }),
        });
        const data = await res.json();
        if (!res.ok || !data.ok) {
            const failed = data.counts ? data.counts.failed : 0;
            if (!failed) throw new Error(data.detail || data.error || "Queue processing failed");
        }
        const counts = data.counts || {};
        showQueueAlert(
            counts.failed ? "alert-warning" : "alert-success",
            `<i class="bi bi-check-circle me-1"></i>` +
                `Processed ${counts.processed || 0}; completed ${counts.completed || 0}; failed ${counts.failed || 0}; ` +
                `local ${counts.local || 0}; Gemini ${counts.gemini || 0}; retries ${counts.retries || 0}.`
        );
        await loadQueue();
    } catch (err) {
        showQueueAlert("alert-danger", `<i class="bi bi-exclamation-triangle me-1"></i>${queueEscapeHtml(err.message)}`);
    } finally {
        if (button) {
            button.disabled = false;
            button.innerHTML = original;
        }
    }
}

async function postQueueAction(url, button, successPrefix, confirmationMessage = "") {
    if (confirmationMessage && !window.confirm(`${confirmationMessage}\n\n${QUEUE_HISTORY_ONLY_NOTE}`)) {
        return;
    }
    const original = button?.innerHTML;
    if (button) {
        button.disabled = true;
        button.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Working';
    }
    try {
        const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
        const data = await res.json();
        if (!res.ok || !data.ok) {
            throw new Error(data.detail || data.error || "Queue action failed");
        }
        const cleared = data.cleared || data.retried || 0;
        const alertClass = cleared ? "alert-success" : "alert-info";
        const iconClass = cleared ? "bi-check-circle" : "bi-info-circle";
        showQueueAlert(
            alertClass,
            `<i class="bi ${iconClass} me-1"></i>${queueEscapeHtml(data.message || successPrefix)}`
        );
        await loadQueue();
    } catch (err) {
        showQueueAlert("alert-danger", `<i class="bi bi-exclamation-triangle me-1"></i>${queueEscapeHtml(err.message)}`);
    } finally {
        if (button) {
            button.disabled = false;
            button.innerHTML = original;
        }
    }
}

document.addEventListener("DOMContentLoaded", () => {
    qs("#queue-refresh-btn")?.addEventListener("click", (e) => {
        e.preventDefault();
        loadQueue();
    });
    qs("#queue-process-next-btn")?.addEventListener("click", (e) => {
        e.preventDefault();
        processQueue(QUEUE_PROCESS_NEXT_URL, 1, e.currentTarget);
    });
    qs("#queue-resume-btn")?.addEventListener("click", (e) => {
        e.preventDefault();
        processQueue(QUEUE_RESUME_URL, 5, e.currentTarget);
    });
    qs("#queue-retry-summary-failed-btn")?.addEventListener("click", (e) => {
        e.preventDefault();
        postQueueAction(QUEUE_RETRY_SUMMARY_FAILED_URL, e.currentTarget, "Failed summary jobs queued for retry.");
    });
    qs("#queue-clear-summary-completed-btn")?.addEventListener("click", (e) => {
        e.preventDefault();
        postQueueAction(
            QUEUE_CLEAR_SUMMARY_COMPLETED_URL,
            e.currentTarget,
            "Completed summary jobs cleared.",
            "Clear completed summary jobs?"
        );
    });
    qs("#queue-clear-transcription-completed-btn")?.addEventListener("click", (e) => {
        e.preventDefault();
        postQueueAction(
            QUEUE_CLEAR_TRANSCRIPTION_COMPLETED_URL,
            e.currentTarget,
            "Completed transcription jobs cleared.",
            "Clear completed transcription jobs?"
        );
    });
    qs("#queue-clear-all-completed-btn")?.addEventListener("click", (e) => {
        e.preventDefault();
        postQueueAction(
            QUEUE_CLEAR_ALL_COMPLETED_URL,
            e.currentTarget,
            "All completed jobs cleared.",
            "Clear all completed jobs?"
        );
    });
    qs("#queue-clear-failed-btn")?.addEventListener("click", (e) => {
        e.preventDefault();
        postQueueAction(
            QUEUE_CLEAR_FAILED_URL,
            e.currentTarget,
            "Failed jobs cleared.",
            "Clear failed jobs? This removes failed queue history that may be useful for debugging."
        );
    });
    qs("#queue-status-filter")?.addEventListener("change", loadQueue);
    loadQueue();
});
