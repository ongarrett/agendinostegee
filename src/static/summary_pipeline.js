const SUMMARY_PIPELINE_STATUS_URL = "/api/processing-queue/summary-pipeline";
const SUMMARY_PIPELINE_ENQUEUE_URL = "/api/processing-queue/summary-pipeline/enqueue";
const SUMMARY_PIPELINE_PAUSE_URL = "/api/processing-queue/summary-pipeline/pause";
const SUMMARY_PIPELINE_RESUME_URL = "/api/processing-queue/summary-pipeline/resume";
const SUMMARY_PIPELINE_RETRY_FAILED_URL = "/api/processing-queue/summary-pipeline/retry-failed";
const SUMMARY_PIPELINE_CLEAR_COMPLETED_URL = "/api/processing-queue/summary-pipeline/clear-completed";
const SUMMARY_PIPELINE_JOBS_URL = "/api/processing-queue/jobs?job_type=summarize";
const SUMMARY_PIPELINE_PROMPTS_URL = "/api/dashboard/prompts";

const sp = (selector) => document.querySelector(selector);
const spShow = (el) => el?.classList.remove("d-none");
const spHide = (el) => el?.classList.add("d-none");

function spEscapeHtml(text) {
    return String(text || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

function showSummaryPipelineAlert(className, message) {
    const alert = sp("#summary-pipeline-alert");
    if (!alert) return;
    alert.className = `alert ${className}`;
    alert.innerHTML = message;
    spShow(alert);
}

function statusBadge(status) {
    const classes = {
        pending: "bg-secondary-subtle text-secondary-emphasis",
        running: "bg-primary-subtle text-primary-emphasis",
        completed: "bg-success-subtle text-success-emphasis",
        failed: "bg-danger-subtle text-danger-emphasis",
        skipped: "bg-warning-subtle text-warning-emphasis",
    };
    return `<span class="badge ${classes[status] || "bg-light text-dark"}">${spEscapeHtml(status)}</span>`;
}

function providerConfig() {
    const provider = sp("#summary-pipeline-provider")?.value || "local";
    const model = sp("#summary-pipeline-model")?.value || "qwen3:8b";
    return {
        summary_provider: provider,
        summary_model: provider === "local" ? model : null,
    };
}

function providerLabel(config = providerConfig()) {
    if (config.summary_provider === "local") {
        return `Local AI / Ollama / ${config.summary_model || "qwen3:8b"}`;
    }
    return "Gemini";
}

function formatEta(seconds) {
    if (!seconds) return "Unknown";
    const minutes = Math.ceil(seconds / 60);
    if (minutes < 60) return `${minutes} min`;
    const hours = Math.floor(minutes / 60);
    const remainder = minutes % 60;
    return remainder ? `${hours}h ${remainder}m` : `${hours}h`;
}

function renderPipelineStatus(status) {
    const counts = status.counts || {};
    sp("#summary-pipeline-missing").textContent = status.total_missing || 0;
    sp("#summary-pipeline-ready").textContent = status.ready || 0;
    sp("#summary-pipeline-queued").textContent = counts.queued || counts.pending || 0;
    sp("#summary-pipeline-running").textContent = counts.running || 0;
    sp("#summary-pipeline-completed").textContent = counts.completed || 0;
    sp("#summary-pipeline-failed").textContent = counts.failed || 0;
    sp("#summary-pipeline-provider-label").textContent = providerLabel({
        summary_provider: status.provider || "local",
        summary_model: status.model || "qwen3:8b",
    });
    const state = sp("#summary-pipeline-state");
    state.textContent = status.paused ? "Paused" : "Active";
    state.className = status.paused
        ? "badge bg-warning-subtle text-warning-emphasis"
        : "badge bg-success-subtle text-success-emphasis";
    const current = status.current_job;
    sp("#summary-pipeline-current").textContent = current
        ? (current.recording_title || current.recording_name)
        : "None running";
    sp("#summary-pipeline-eta").textContent = formatEta(status.estimated_seconds_remaining);
    sp("#summary-pipeline-updated").textContent = status.last_updated || "Never";
}

function renderJobs(jobs) {
    const table = sp("#summary-pipeline-table");
    const body = sp("#summary-pipeline-table-body");
    const empty = sp("#summary-pipeline-empty");
    if (!jobs.length) {
        body.innerHTML = "";
        spHide(table);
        spShow(empty);
        return;
    }
    body.innerHTML = jobs.map(job => {
        const provider = job.summary_provider === "local"
            ? `Local AI / Ollama / ${job.summary_model || "qwen3:8b"}`
            : "Gemini";
        const prompt = job.prompt_id ? `<div class="small text-muted">${spEscapeHtml(job.prompt_id)}</div>` : "";
        const error = job.error ? `<span class="text-danger queue-error">${spEscapeHtml(job.error)}</span>` : "";
        return `
            <tr>
                <td>${statusBadge(job.status)}</td>
                <td>
                    <a href="/?recording=${encodeURIComponent(job.recording_name)}">${spEscapeHtml(job.recording_title || job.recording_name)}</a>
                    <div class="small text-muted">${spEscapeHtml(job.recording_name)}</div>
                </td>
                <td>${spEscapeHtml(provider)}${prompt}</td>
                <td>${job.attempts || 0}</td>
                <td class="small text-muted">${spEscapeHtml(job.updated_at || "")}</td>
                <td>${error}</td>
            </tr>`;
    }).join("");
    spHide(empty);
    spShow(table);
}

async function loadPrompts() {
    const select = sp("#summary-pipeline-prompt");
    if (!select) return;
    const res = await fetch(SUMMARY_PIPELINE_PROMPTS_URL);
    const data = await res.json();
    if (!res.ok || !data.ok) {
        throw new Error(data.detail || data.error || "Failed to load prompts");
    }
    const prompts = data.prompts || [];
    select.innerHTML = prompts.map(prompt => (
        `<option value="${spEscapeHtml(prompt.id)}">${spEscapeHtml(prompt.language)} / ${spEscapeHtml(prompt.category)} / ${spEscapeHtml(prompt.name)}</option>`
    )).join("");
}

async function loadSummaryPipeline() {
    const loading = sp("#summary-pipeline-loading");
    spShow(loading);
    try {
        const [statusRes, jobsRes] = await Promise.all([
            fetch(SUMMARY_PIPELINE_STATUS_URL),
            fetch(SUMMARY_PIPELINE_JOBS_URL),
        ]);
        const statusData = await statusRes.json();
        const jobsData = await jobsRes.json();
        if (!statusRes.ok || !statusData.ok) {
            throw new Error(statusData.detail || statusData.error || "Failed to load summary pipeline");
        }
        if (!jobsRes.ok || !jobsData.ok) {
            throw new Error(jobsData.detail || jobsData.error || "Failed to load summary jobs");
        }
        renderPipelineStatus(statusData);
        renderJobs(jobsData.jobs || []);
    } catch (err) {
        showSummaryPipelineAlert("alert-danger", `<i class="bi bi-exclamation-triangle me-1"></i>${spEscapeHtml(err.message)}`);
    } finally {
        spHide(loading);
    }
}

async function postJson(url, payload = {}, button = null) {
    const original = button?.innerHTML;
    if (button) {
        button.disabled = true;
        button.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Working';
    }
    try {
        const res = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!res.ok || !data.ok) {
            throw new Error(data.detail || data.error || "Request failed");
        }
        return data;
    } finally {
        if (button) {
            button.disabled = false;
            button.innerHTML = original;
        }
    }
}

async function enqueueSummaries(limit, button) {
    const promptId = sp("#summary-pipeline-prompt")?.value;
    if (!promptId) {
        showSummaryPipelineAlert("alert-warning", '<i class="bi bi-info-circle me-1"></i>Select a prompt first.');
        return;
    }
    const payload = {
        prompt_id: promptId,
        limit: limit || null,
        ...providerConfig(),
    };
    try {
        const data = await postJson(SUMMARY_PIPELINE_ENQUEUE_URL, payload, button);
        const counts = data.counts || {};
        showSummaryPipelineAlert(
            "alert-success",
            `<i class="bi bi-check-circle me-1"></i>${spEscapeHtml(data.message || `Queued ${counts.enqueued || 0} summary job(s).`)}`
        );
        await loadSummaryPipeline();
    } catch (err) {
        showSummaryPipelineAlert("alert-danger", `<i class="bi bi-exclamation-triangle me-1"></i>${spEscapeHtml(err.message)}`);
    }
}

document.addEventListener("DOMContentLoaded", async () => {
    try {
        await loadPrompts();
    } catch (err) {
        showSummaryPipelineAlert("alert-danger", `<i class="bi bi-exclamation-triangle me-1"></i>${spEscapeHtml(err.message)}`);
    }
    await loadSummaryPipeline();

    sp("#summary-pipeline-refresh")?.addEventListener("click", (e) => {
        e.preventDefault();
        loadSummaryPipeline();
    });
    sp("#summary-pipeline-provider")?.addEventListener("change", (e) => {
        const isLocal = e.currentTarget.value === "local";
        sp("#summary-pipeline-model-wrap")?.classList.toggle("d-none", !isLocal);
        sp("#summary-pipeline-provider-label").textContent = providerLabel();
    });
    sp("#summary-pipeline-model")?.addEventListener("change", () => {
        sp("#summary-pipeline-provider-label").textContent = providerLabel();
    });
    document.querySelectorAll("[data-summary-enqueue-limit]").forEach(button => {
        button.addEventListener("click", (e) => {
            e.preventDefault();
            const raw = e.currentTarget.dataset.summaryEnqueueLimit;
            enqueueSummaries(raw ? Number(raw) : null, e.currentTarget);
        });
    });
    sp("#summary-pipeline-pause")?.addEventListener("click", async (e) => {
        e.preventDefault();
        try {
            await postJson(SUMMARY_PIPELINE_PAUSE_URL, {}, e.currentTarget);
            showSummaryPipelineAlert("alert-warning", '<i class="bi bi-pause-fill me-1"></i>Summary pipeline paused.');
            await loadSummaryPipeline();
        } catch (err) {
            showSummaryPipelineAlert("alert-danger", `<i class="bi bi-exclamation-triangle me-1"></i>${spEscapeHtml(err.message)}`);
        }
    });
    sp("#summary-pipeline-resume")?.addEventListener("click", async (e) => {
        e.preventDefault();
        try {
            const data = await postJson(SUMMARY_PIPELINE_RESUME_URL, { max_jobs: 5, max_retries: 1, reset_running: true }, e.currentTarget);
            const counts = data.counts || {};
            showSummaryPipelineAlert(
                counts.failed ? "alert-warning" : "alert-success",
                `<i class="bi bi-play-fill me-1"></i>Processed ${counts.processed || 0}; completed ${counts.completed || 0}; skipped ${counts.skipped || 0}; failed ${counts.failed || 0}.`
            );
            await loadSummaryPipeline();
        } catch (err) {
            showSummaryPipelineAlert("alert-danger", `<i class="bi bi-exclamation-triangle me-1"></i>${spEscapeHtml(err.message)}`);
        }
    });
    sp("#summary-pipeline-retry-failed")?.addEventListener("click", async (e) => {
        e.preventDefault();
        try {
            const data = await postJson(SUMMARY_PIPELINE_RETRY_FAILED_URL, {}, e.currentTarget);
            showSummaryPipelineAlert("alert-success", `<i class="bi bi-arrow-repeat me-1"></i>${spEscapeHtml(data.message || "Failed summary jobs queued for retry.")}`);
            await loadSummaryPipeline();
        } catch (err) {
            showSummaryPipelineAlert("alert-danger", `<i class="bi bi-exclamation-triangle me-1"></i>${spEscapeHtml(err.message)}`);
        }
    });
    sp("#summary-pipeline-clear-completed")?.addEventListener("click", async (e) => {
        e.preventDefault();
        try {
            const data = await postJson(SUMMARY_PIPELINE_CLEAR_COMPLETED_URL, {}, e.currentTarget);
            showSummaryPipelineAlert("alert-success", `<i class="bi bi-trash3 me-1"></i>${spEscapeHtml(data.message || "Completed summary jobs cleared.")}`);
            await loadSummaryPipeline();
        } catch (err) {
            showSummaryPipelineAlert("alert-danger", `<i class="bi bi-exclamation-triangle me-1"></i>${spEscapeHtml(err.message)}`);
        }
    });
});
