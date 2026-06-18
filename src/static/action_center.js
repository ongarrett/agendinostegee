const ACTION_ITEMS_URL = "/api/action-center/items";
const ACTION_EXTRACT_SELECTED_URL = "/api/action-center/extract/selected";
const ACTION_EXTRACT_SUMMARIZED_URL = "/api/action-center/extract/summarized";
const ACTION_EXTRACT_TRANSCRIBED_URL = "/api/action-center/extract/transcribed";
const ACTION_EXTRACT_COLLECTION_URL = "/api/action-center/extract/collection";
const ACTION_EXTRACT_RECORDING_URL = "/api/action-center/extract/recording";
const DASHBOARD_RECORDINGS_URL = "/api/dashboard/recordings";

const acQuery = (selector) => document.querySelector(selector);
const show = (el) => el?.classList.remove("d-none");
const hide = (el) => el?.classList.add("d-none");

let actionItems = [];
let filterOptions = { owners: [], topics: [], recordings: [] };
let recordings = [];
let collections = [];

function escapeHtml(text) {
    return (text || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

function itemTypeLabel(type) {
    return {
        action_item: "Action Item",
        decision: "Decision",
        risk: "Risk / Blocker",
        open_question: "Open Question",
    }[type] || type;
}

function itemTypeClass(type) {
    return {
        action_item: "text-bg-primary",
        decision: "text-bg-success",
        risk: "text-bg-danger",
        open_question: "text-bg-warning",
    }[type] || "text-bg-secondary";
}

function statusLabel(status) {
    return {
        open: "Open",
        done: "Done",
        resolved: "Resolved",
        dismissed: "Dismissed",
    }[status] || status;
}

function alertMessage(className, message) {
    const alert = acQuery("#action-center-alert");
    if (!alert) return;
    alert.className = `alert ${className}`;
    alert.innerHTML = message;
    show(alert);
}

function selectedRecordingNames() {
    return Array.from(acQuery("#action-recording-select")?.selectedOptions || []).map(option => option.value);
}

function forceRefresh() {
    return !!acQuery("#action-force-refresh")?.checked;
}

function currentFilters() {
    const params = new URLSearchParams();
    const values = {
        item_type: acQuery("#filter-item-type")?.value || "",
        owner: acQuery("#filter-owner")?.value || "",
        topic: acQuery("#filter-topic")?.value || "",
        recording_name: acQuery("#filter-recording")?.value || "",
        date_filter: acQuery("#filter-date")?.value || "",
    };
    Object.entries(values).forEach(([key, value]) => {
        if (value) params.set(key, value);
    });
    if (acQuery("#filter-dismissed")?.checked) params.set("include_dismissed", "true");
    return params;
}

function renderSelectOptions(select, options, placeholder, getValue = item => item, getLabel = item => item) {
    if (!select) return;
    const current = select.value;
    select.innerHTML = `<option value="">${placeholder}</option>` + options.map(item => {
        const value = getValue(item);
        const label = getLabel(item);
        return `<option value="${escapeHtml(value)}">${escapeHtml(label)}</option>`;
    }).join("");
    select.value = current;
}

function populateFilters() {
    renderSelectOptions(acQuery("#filter-owner"), filterOptions.owners || [], "All people");
    renderSelectOptions(acQuery("#filter-topic"), filterOptions.topics || [], "All topics");
    renderSelectOptions(
        acQuery("#filter-recording"),
        filterOptions.recordings || [],
        "All recordings",
        item => item.name,
        item => item.title || item.name
    );
}

function populateExtractionSelectors() {
    const recordingSelect = acQuery("#action-recording-select");
    if (recordingSelect) {
        recordingSelect.innerHTML = recordings.map(rec => {
            const title = rec.db_title || rec.db_label || rec.name;
            return `<option value="${escapeHtml(rec.name)}">${escapeHtml(title)}</option>`;
        }).join("");
    }
    const collectionSelect = acQuery("#action-collection-select");
    if (collectionSelect) {
        collectionSelect.innerHTML = '<option value="">Choose collection...</option>' + collections.map(collection => (
            `<option value="${collection.id}">${escapeHtml(collection.name)} (${collection.count || 0})</option>`
        )).join("");
    }
}

function updateCounts(counts) {
    acQuery("#count-action-items").textContent = counts.action_item || 0;
    acQuery("#count-decisions").textContent = counts.decision || 0;
    acQuery("#count-risks").textContent = counts.risk || 0;
    acQuery("#count-questions").textContent = counts.open_question || 0;
}

function topicBadges(topics) {
    if (!topics || topics.length === 0) return "";
    return topics.map(topic => (
        `<span class="badge bg-secondary-subtle text-secondary-emphasis">${escapeHtml(topic)}</span>`
    )).join("");
}

function renderActionCard(item) {
    const isAction = item.item_type === "action_item";
    const isRisk = item.item_type === "risk";
    const canComplete = isAction && item.status !== "done" && item.status !== "dismissed";
    const canResolve = isRisk && item.status !== "resolved" && item.status !== "dismissed";
    const recordingTitle = item.recording_title || item.recording_name;
    return `<article class="action-item-card status-${escapeHtml(item.status)}" data-item-id="${item.id}">
        <div class="action-item-header">
            <div class="action-item-text">${escapeHtml(item.text)}</div>
            <span class="badge ${itemTypeClass(item.item_type)}">${itemTypeLabel(item.item_type)}</span>
        </div>
        <div class="action-item-meta">
            ${item.owner ? `<span class="badge bg-info-subtle text-info-emphasis"><i class="bi bi-person me-1"></i>${escapeHtml(item.owner)}</span>` : ""}
            ${item.due_date ? `<span class="badge bg-warning-subtle text-warning-emphasis"><i class="bi bi-calendar3 me-1"></i>${escapeHtml(item.due_date)}</span>` : ""}
            <span class="badge bg-light text-body border"><i class="bi bi-mic me-1"></i>${escapeHtml(recordingTitle)}</span>
            <span class="badge bg-light text-body border">${statusLabel(item.status)}</span>
            ${topicBadges(item.topics)}
        </div>
        ${item.source_excerpt ? `<div class="action-source-excerpt">${escapeHtml(item.source_excerpt)}</div>` : ""}
        <div class="action-item-actions">
            ${canComplete ? `<button class="btn btn-sm btn-outline-success btn-action-status" data-status="done" data-item-id="${item.id}"><i class="bi bi-check2 me-1"></i>Mark done</button>` : ""}
            ${canResolve ? `<button class="btn btn-sm btn-outline-success btn-action-status" data-status="resolved" data-item-id="${item.id}"><i class="bi bi-check2-circle me-1"></i>Resolve risk</button>` : ""}
            <button class="btn btn-sm btn-outline-secondary btn-action-dismiss" data-item-id="${item.id}"><i class="bi bi-eye-slash me-1"></i>Dismiss</button>
            <a class="btn btn-sm btn-outline-dark" href="/?recording=${encodeURIComponent(item.recording_name)}">
                <i class="bi bi-layout-text-sidebar-reverse me-1"></i>Open recording
            </a>
            <button class="btn btn-sm btn-outline-primary btn-action-regenerate" data-recording-name="${escapeHtml(item.recording_name)}">
                <i class="bi bi-arrow-repeat me-1"></i>Regenerate
            </button>
        </div>
    </article>`;
}

function renderGroup(selector, items, emptyText) {
    const list = document.querySelector(`${selector} .action-group-list`);
    if (!list) return;
    list.innerHTML = items.length
        ? items.map(renderActionCard).join("")
        : `<div class="action-group-empty">${emptyText}</div>`;
}

function renderItems() {
    hide(acQuery("#action-center-loading"));
    if (!actionItems.length) {
        hide(acQuery("#action-groups"));
        show(acQuery("#action-center-empty"));
        return;
    }
    hide(acQuery("#action-center-empty"));
    show(acQuery("#action-groups"));

    renderGroup(
        "#group-my-actions",
        actionItems.filter(item => item.item_type === "action_item" && item.owner),
        "No assigned action items."
    );
    renderGroup(
        "#group-team-actions",
        actionItems.filter(item => item.item_type === "action_item" && !item.owner),
        "No unassigned team action items."
    );
    renderGroup("#group-decisions", actionItems.filter(item => item.item_type === "decision"), "No decisions.");
    renderGroup("#group-risks", actionItems.filter(item => item.item_type === "risk"), "No risks or blockers.");
    renderGroup(
        "#group-questions",
        actionItems.filter(item => item.item_type === "open_question"),
        "No open questions."
    );
}

async function loadActionItems() {
    show(acQuery("#action-center-loading"));
    hide(acQuery("#action-center-empty"));
    const res = await fetch(`${ACTION_ITEMS_URL}?${currentFilters().toString()}`);
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "Failed to load Action Center");
    actionItems = data.items || [];
    filterOptions = data.filters || filterOptions;
    updateCounts(data.counts || {});
    populateFilters();
    renderItems();
}

async function loadRecordingOptions() {
    const res = await fetch(DASHBOARD_RECORDINGS_URL);
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "Failed to load recordings");
    recordings = data.recordings || [];
    collections = data.collections || [];
    populateExtractionSelectors();
}

async function runExtraction(url, payload, button) {
    const original = button?.innerHTML;
    if (button) {
        button.disabled = true;
        button.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Extracting...';
    }
    hide(acQuery("#action-center-alert"));
    try {
        const res = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!res.ok || !data.ok) throw new Error(data.error || "Extraction failed");
        const counts = data.counts || {};
        alertMessage(
            counts.failed ? "alert-warning" : "alert-success",
            `<i class="bi bi-check-circle me-1"></i>Processed ${counts.recordings || 0}; extracted ${counts.extracted || 0}; skipped ${counts.skipped || 0}; items ${counts.items || 0}; failed ${counts.failed || 0}.`
        );
        await loadActionItems();
    } catch (err) {
        alertMessage("alert-danger", `<i class="bi bi-exclamation-triangle me-1"></i>${escapeHtml(err.message)}`);
    } finally {
        if (button) {
            button.disabled = false;
            button.innerHTML = original;
        }
    }
}

async function updateStatus(itemId, status) {
    const res = await fetch(`/api/action-center/items/${encodeURIComponent(itemId)}/status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "Status update failed");
    await loadActionItems();
}

async function dismissItem(itemId) {
    const res = await fetch(`/api/action-center/items/${encodeURIComponent(itemId)}/dismiss`, { method: "POST" });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "Dismiss failed");
    await loadActionItems();
}

document.addEventListener("DOMContentLoaded", async () => {
    try {
        await Promise.all([loadActionItems(), loadRecordingOptions()]);
    } catch (err) {
        hide(acQuery("#action-center-loading"));
        alertMessage("alert-danger", `<i class="bi bi-exclamation-triangle me-1"></i>${escapeHtml(err.message)}`);
    }

    acQuery("#btn-action-center-refresh")?.addEventListener("click", (e) => {
        e.preventDefault();
        loadActionItems().catch(err => alertMessage("alert-danger", escapeHtml(err.message)));
    });
    document.querySelectorAll(".action-filter").forEach(el => {
        el.addEventListener("change", () => loadActionItems().catch(err => alertMessage("alert-danger", escapeHtml(err.message))));
    });
    acQuery("#btn-clear-action-filters")?.addEventListener("click", (e) => {
        e.preventDefault();
        ["#filter-item-type", "#filter-owner", "#filter-topic", "#filter-recording", "#filter-date"].forEach(selector => {
            const el = acQuery(selector);
            if (el) el.value = "";
        });
        const dismissed = acQuery("#filter-dismissed");
        if (dismissed) dismissed.checked = false;
        loadActionItems().catch(err => alertMessage("alert-danger", escapeHtml(err.message)));
    });
    acQuery("#btn-extract-selected")?.addEventListener("click", (e) => {
        e.preventDefault();
        const names = selectedRecordingNames();
        if (!names.length) {
            alertMessage("alert-warning", "Select one or more recordings first.");
            return;
        }
        runExtraction(ACTION_EXTRACT_SELECTED_URL, { names, force: forceRefresh() }, e.currentTarget);
    });
    acQuery("#btn-extract-summarized")?.addEventListener("click", (e) => {
        e.preventDefault();
        runExtraction(ACTION_EXTRACT_SUMMARIZED_URL, { force: forceRefresh() }, e.currentTarget);
    });
    acQuery("#btn-extract-transcribed")?.addEventListener("click", (e) => {
        e.preventDefault();
        runExtraction(ACTION_EXTRACT_TRANSCRIBED_URL, { force: forceRefresh() }, e.currentTarget);
    });
    acQuery("#btn-extract-collection")?.addEventListener("click", (e) => {
        e.preventDefault();
        const collectionId = Number(acQuery("#action-collection-select")?.value || 0);
        if (!collectionId) {
            alertMessage("alert-warning", "Choose a collection first.");
            return;
        }
        runExtraction(ACTION_EXTRACT_COLLECTION_URL, { collection_id: collectionId, force: true }, e.currentTarget);
    });
    document.addEventListener("click", async (e) => {
        const statusBtn = e.target.closest(".btn-action-status");
        const dismissBtn = e.target.closest(".btn-action-dismiss");
        const regenerateBtn = e.target.closest(".btn-action-regenerate");
        try {
            if (statusBtn) {
                e.preventDefault();
                await updateStatus(statusBtn.dataset.itemId, statusBtn.dataset.status);
            } else if (dismissBtn) {
                e.preventDefault();
                await dismissItem(dismissBtn.dataset.itemId);
            } else if (regenerateBtn) {
                e.preventDefault();
                await runExtraction(
                    `${ACTION_EXTRACT_RECORDING_URL}/${encodeURIComponent(regenerateBtn.dataset.recordingName)}`,
                    { force: true },
                    regenerateBtn
                );
            }
        } catch (err) {
            alertMessage("alert-danger", `<i class="bi bi-exclamation-triangle me-1"></i>${escapeHtml(err.message)}`);
        }
    });
});
