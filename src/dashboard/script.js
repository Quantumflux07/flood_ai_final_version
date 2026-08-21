/**
 * FLOWSHIELD V2 — Frontend Controller
 * Connects Stitch UI templates to the FlowShield V2 Decision & Replanning Backend.
 */

const API_BASE = "";
let operationalState = null;
let selectedResourceId = "crew-alpha";
let activeIncidentId = null;

// ── Tab Navigation ──────────────────────────────────────────────────────────

function switchTab(tabId) {
    const tabs = ["live", "incidents", "resources", "simulation", "history"];
    tabs.forEach(t => {
        const btn = document.getElementById(`nav-${t}`);
        const view = document.getElementById(`view-${t}`);
        if (btn) {
            if (t === tabId) {
                btn.classList.add("active");
            } else {
                btn.classList.remove("active");
            }
        }
        if (view) {
            if (t === tabId) {
                view.classList.remove("hidden");
            } else {
                view.classList.add("hidden");
            }
        }
    });
}

// ── State Fetching & UI Rendering ───────────────────────────────────────────

async function refreshState() {
    const refreshIcon = document.getElementById("refresh-icon");
    if (refreshIcon) refreshIcon.classList.add("animate-spin");

    try {
        const res = await fetch(`${API_BASE}/api/state`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        operationalState = data;

        renderLiveStatusMetrics(data);
        renderDecisionEnginePanel(data);
        renderIncidentsView(data);
        renderResourcesView(data);
        renderTimelineView(data);
        updateClocks();
    } catch (err) {
        console.error("Failed to load operational state:", err);
        showToast("Error connecting to FlowShield backend API", "error");
    } finally {
        if (refreshIcon) {
            setTimeout(() => refreshIcon.classList.remove("animate-spin"), 400);
        }
    }
}

function renderLiveStatusMetrics(state) {
    const activeIncs = state.incidents ? state.incidents.filter(i => i.status === "open") : [];
    const p1Incs = activeIncs.filter(i => i.severity === "critical" || (i.people_trapped && i.people_trapped > 0));
    
    let totalRisk = 0;
    activeIncs.forEach(i => {
        totalRisk += (i.people_at_risk || (i.people_trapped ? i.people_trapped * 3 : 100));
    });

    const resources = state.resources || [];
    const deployedCount = resources.filter(r => r.status === "assigned" || r.status === "deployed").length;

    const elActive = document.getElementById("stat-active-incidents");
    const elP1 = document.getElementById("stat-p1-critical");
    const elRisk = document.getElementById("stat-people-risk");
    const elDep = document.getElementById("stat-deployed-res");

    if (elActive) elActive.textContent = activeIncs.length;
    if (elP1) elP1.textContent = p1Incs.length;
    if (elRisk) elRisk.textContent = totalRisk.toLocaleString();
    if (elDep) elDep.textContent = `${deployedCount} / ${resources.length}`;

    // Simulation tab live metric
    const simLiveIncs = document.getElementById("sim-live-incs");
    if (simLiveIncs) simLiveIncs.textContent = activeIncs.length;
}

function renderDecisionEnginePanel(state) {
    const allocBox = document.getElementById("live-alloc-box");
    const planBox = document.getElementById("live-plan-box");
    const optRes = state.optimization_result;
    const plan = state.response_plan;

    if (allocBox) {
        if (optRes && optRes.assignments && optRes.assignments.length > 0) {
            allocBox.innerHTML = optRes.assignments.map(a => `
                <div class="p-1.5 bg-surface rounded border border-outline-variant/40 flex justify-between items-center">
                    <div>
                        <span class="text-primary font-bold">${a.resource_id}</span>
                        <span class="text-on-surface-variant text-[10px] block">-> ${a.incident_id.slice(0, 8)}...</span>
                    </div>
                    <div class="text-right">
                        <span class="text-tertiary">ETA ${a.estimated_travel_minutes}m</span>
                        <span class="text-[10px] text-on-surface-variant block">Score ${(a.fit_score * 100).toFixed(0)}%</span>
                    </div>
                </div>
            `).join("");
        } else {
            allocBox.innerHTML = `<p class="text-on-surface-variant text-xs">No active assignments.</p>`;
        }
    }

    if (planBox) {
        if (plan && plan.plan_actions && plan.plan_actions.length > 0) {
            planBox.innerHTML = plan.plan_actions.map(pa => `
                <div class="p-1.5 bg-surface rounded border border-outline-variant/40 flex items-start gap-2">
                    <span class="text-primary font-bold text-xs">#${pa.step}</span>
                    <div class="flex-1">
                        <span class="text-xs text-on-surface line-clamp-2">${pa.action_description}</span>
                        <span class="text-[10px] ${pa.approval_state === 'required' ? 'text-secondary' : 'text-[#10b981]'} font-bold uppercase">${pa.approval_state}</span>
                    </div>
                </div>
            `).join("");
        } else {
            planBox.innerHTML = `<p class="text-on-surface-variant text-xs">Response plan is pending.</p>`;
        }
    }
}

function renderIncidentsView(state) {
    const queueList = document.getElementById("incidents-queue-list");
    const openIncs = state.incidents ? state.incidents.filter(i => i.status === "open") : [];
    
    if (!openIncs.length) {
        if (queueList) queueList.innerHTML = `<p class="text-on-surface-variant text-xs p-3">No active incidents in queue.</p>`;
        return;
    }

    if (!activeIncidentId || !openIncs.some(i => i.id === activeIncidentId)) {
        activeIncidentId = openIncs[0].id;
    }

    // Render Queue on Right Sidebar
    if (queueList) {
        queueList.innerHTML = openIncs.map(inc => {
            const isSelected = inc.id === activeIncidentId;
            const isCrit = inc.severity === "critical" || (inc.people_trapped && inc.people_trapped > 0);
            return `
                <div onclick="selectIncident('${inc.id}')" class="p-2.5 bg-surface rounded ${isSelected ? 'border-2 border-primary' : 'border border-outline-variant'} ${isCrit ? 'border-l-4 border-l-error' : 'border-l-4 border-l-tertiary'} flex justify-between items-center cursor-pointer hover:bg-surface-container-highest transition-colors">
                    <div class="overflow-hidden pr-2">
                        <span class="font-data-mono text-data-mono text-on-surface text-[12px] block truncate font-bold">${inc.title || inc.id}</span>
                        <span class="text-[10px] text-on-surface-variant font-data-mono">${inc.zone_id || 'Zone W12'} • ${inc.people_trapped ? inc.people_trapped + ' Trapped' : (inc.people_at_risk || 0) + ' at risk'}</span>
                    </div>
                    <span class="font-data-mono text-[10px] font-bold ${isCrit ? 'text-error bg-error/10 border border-error/20' : 'text-tertiary bg-tertiary/10 border border-tertiary/20'} px-1.5 py-0.5 rounded uppercase">${inc.severity}</span>
                </div>
            `;
        }).join("");
    }

    // Render Selected Incident Details
    const activeInc = openIncs.find(i => i.id === activeIncidentId) || openIncs[0];
    if (activeInc) {
        const titleEl = document.getElementById("inc-decision-title");
        const descEl = document.getElementById("inc-decision-desc");
        const pLevelEl = document.getElementById("inc-decision-p-level");
        const locEl = document.getElementById("inc-loc-val");
        const entitiesEl = document.getElementById("inc-entities-val");
        const driversList = document.getElementById("inc-drivers-list");
        const resNameEl = document.getElementById("inc-res-name");
        const resEtaEl = document.getElementById("inc-res-eta");
        const resReasoningEl = document.getElementById("inc-res-reasoning");
        const actionsList = document.getElementById("inc-actions-list");

        if (titleEl) titleEl.textContent = activeInc.title || `Flood Incident — ${activeInc.zone_id}`;
        if (descEl) descEl.textContent = activeInc.description || `Active flood emergency in ${activeInc.zone_id}.`;
        if (pLevelEl) pLevelEl.textContent = `${activeInc.severity === 'critical' ? 'P1 — Life Safety' : 'P2 — Elevated Risk'}`;
        if (locEl) locEl.textContent = activeInc.location || activeInc.zone_id || "Ward 12";

        const entitiesStr = [
            activeInc.people_trapped ? `${activeInc.people_trapped} Trapped` : null,
            activeInc.people_at_risk ? `${activeInc.people_at_risk} at Risk` : null,
            activeInc.critical_facility ? `Facility: ${activeInc.critical_facility}` : null,
            activeInc.zone_id ? `Zone: ${activeInc.zone_id}` : null
        ].filter(Boolean).join(", ");
        if (entitiesEl) entitiesEl.textContent = entitiesStr || "Urban flood conditions detected.";

        // Find priority result drivers for this incident
        const pr = (state.priority_results || []).find(p => p.incident_id === activeInc.id);
        if (driversList) {
            if (pr && pr.reason_codes && pr.reason_codes.length > 0) {
                driversList.innerHTML = pr.reason_codes.map(rc => `
                    <li class="flex items-center gap-2">
                        <span class="w-1.5 h-1.5 bg-error rounded-full"></span>
                        <span>${rc.replace(/_/g, " ")} (Score Factor)</span>
                    </li>
                `).join("");
            } else {
                driversList.innerHTML = `
                    <li class="flex items-center gap-2"><span class="w-1.5 h-1.5 bg-error rounded-full"></span> Life-safety priority evaluation</li>
                    <li class="flex items-center gap-2"><span class="w-1.5 h-1.5 bg-error rounded-full"></span> Critical water level surge</li>
                `;
            }
        }

        // Find allocation for this incident
        const opt = state.optimization_result;
        const assignment = opt && opt.assignments ? opt.assignments.find(a => a.incident_id === activeInc.id) : null;
        if (assignment) {
            const resObj = (state.resources || []).find(r => r.id === assignment.resource_id);
            if (resNameEl) resNameEl.textContent = resObj ? resObj.name : assignment.resource_id;
            if (resEtaEl) resEtaEl.textContent = `Assigned — ETA ${assignment.estimated_travel_minutes} min (Fit: ${(assignment.fit_score * 100).toFixed(0)}%)`;
            if (resReasoningEl) resReasoningEl.textContent = `Assigned based on shortest transit distance and verified capabilities [${assignment.reason_codes.join(', ')}].`;
        } else {
            if (resNameEl) resNameEl.textContent = "Unassigned / Gap Escalation";
            if (resEtaEl) resEtaEl.textContent = "Requires Mutual Aid / Escalation";
            if (resReasoningEl) resReasoningEl.textContent = "No matching available resources currently within travel threshold. Escalated to municipal flood coordination.";
        }

        // Render response plan actions
        const plan = state.response_plan;
        if (actionsList) {
            if (plan && plan.plan_actions && plan.plan_actions.length > 0) {
                actionsList.innerHTML = plan.plan_actions.map(pa => `
                    <li class="flex items-start gap-3 p-2 bg-surface rounded border border-outline-variant">
                        <span class="flex items-center justify-center w-5 h-5 rounded-full bg-primary-container text-primary text-[10px] border border-primary shrink-0">${pa.step}</span>
                        <div class="flex-1">
                            <span class="block">${pa.action_description}</span>
                            <span class="text-[10px] ${pa.approval_state === 'required' ? 'text-secondary' : 'text-[#10b981]'} uppercase font-bold tracking-wider">${pa.approval_state === 'required' ? 'Human Approval Required' : 'Auto Dispatched'}</span>
                        </div>
                    </li>
                `).join("");
            } else {
                actionsList.innerHTML = `<li class="p-2 text-on-surface-variant text-xs">Awaiting workflow action generation.</li>`;
            }
        }
    }
}

function selectIncident(incId) {
    activeIncidentId = incId;
    if (operationalState) renderIncidentsView(operationalState);
}

function renderResourcesView(state) {
    const tbody = document.getElementById("resources-table-body");
    const resources = state.resources || [];

    // Summary counts
    const rescueAvail = resources.filter(r => r.type === "rescue_team" && (r.status === "available" || r.status === "standby")).length;
    const pumpAvail = resources.filter(r => r.type === "pump" && (r.status === "available" || r.status === "standby")).length;
    const elRescue = document.getElementById("fleet-rescue-avail");
    const elPump = document.getElementById("fleet-pump-avail");
    if (elRescue) elRescue.textContent = rescueAvail;
    if (elPump) elPump.textContent = pumpAvail;

    if (tbody) {
        tbody.innerHTML = resources.map(r => {
            const isSelected = r.id === selectedResourceId;
            const isAvail = r.status === "available" || r.status === "standby";
            const isUnavail = r.status === "unavailable";
            const isAssigned = r.status === "assigned" || r.status === "deployed";

            let statusBadge = `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-primary-container text-primary text-[10px] uppercase font-bold tracking-wider"><span class="w-1.5 h-1.5 rounded-full bg-primary"></span> Available</span>`;
            if (isUnavail) {
                statusBadge = `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-error-container/30 text-error text-[10px] uppercase font-bold tracking-wider"><span class="w-1.5 h-1.5 rounded-full bg-error"></span> Unavailable</span>`;
            } else if (isAssigned) {
                statusBadge = `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-tertiary-container/30 text-tertiary text-[10px] uppercase font-bold tracking-wider"><span class="w-1.5 h-1.5 rounded-full bg-tertiary"></span> Assigned</span>`;
            }

            return `
                <tr onclick="selectResource('${r.id}')" class="border-b border-outline-variant hover:bg-surface-container-high transition-colors cursor-pointer ${isSelected ? 'bg-primary-container/20 border-l-4 border-l-primary' : 'border-l-4 border-l-transparent'}">
                    <td class="p-3 font-data-mono text-data-mono text-primary font-bold">${r.id}</td>
                    <td class="p-3 font-bold">${r.name}</td>
                    <td class="p-3 text-on-surface-variant uppercase font-data-mono text-[11px]">${r.type.replace('_', ' ')}</td>
                    <td class="p-3">${statusBadge}</td>
                    <td class="p-3 font-data-mono text-on-surface-variant text-[11px]">${r.current_zone_id || r.home_zone_id || 'Depot'}</td>
                    <td class="p-3 text-right">
                        <button onclick="event.stopPropagation(); toggleResource('${r.id}')" class="px-2 py-1 text-[11px] font-label-caps uppercase rounded ${isAvail ? 'bg-error-container text-on-error-container hover:bg-error' : 'bg-primary text-on-primary hover:bg-primary-fixed'} transition-colors">
                            ${isAvail ? 'Mark Unavail' : 'Mark Avail'}
                        </button>
                    </td>
                </tr>
            `;
        }).join("");
    }

    renderSelectedResourceDetail(state);
}

function selectResource(resId) {
    selectedResourceId = resId;
    if (operationalState) renderResourcesView(operationalState);
}

function renderSelectedResourceDetail(state) {
    const resources = state.resources || [];
    const r = resources.find(item => item.id === selectedResourceId) || resources[0];
    if (!r) return;

    const idEl = document.getElementById("detail-res-id");
    const nameEl = document.getElementById("detail-res-name");
    const badgeEl = document.getElementById("detail-res-status-badge");
    const zoneEl = document.getElementById("detail-res-zone");
    const capsEl = document.getElementById("detail-res-caps");
    const btnToggle = document.getElementById("btn-toggle-resource");

    if (idEl) idEl.textContent = r.id.toUpperCase();
    if (nameEl) nameEl.textContent = `${r.name} • ${r.type.replace('_', ' ')}`;
    if (zoneEl) zoneEl.textContent = r.current_zone_id || r.home_zone_id || "Ward 12 Central";

    if (badgeEl) {
        badgeEl.textContent = r.status.toUpperCase();
        if (r.status === "unavailable") {
            badgeEl.className = "inline-flex items-center gap-1 px-2 py-1 rounded bg-error-container text-on-error-container text-xs uppercase font-bold tracking-wider";
        } else {
            badgeEl.className = "inline-flex items-center gap-1 px-2 py-1 rounded bg-primary-container text-primary text-xs uppercase font-bold tracking-wider";
        }
    }

    if (capsEl) {
        const caps = r.capabilities || ["Standard Flood Relief Equipment"];
        capsEl.innerHTML = caps.map(c => `
            <li class="flex items-center gap-2">
                <span class="material-symbols-outlined text-primary text-[14px]">check_circle</span>
                <span>${c}</span>
            </li>
        `).join("");
    }

    if (btnToggle) {
        const isAvail = r.status === "available" || r.status === "standby";
        btnToggle.textContent = isAvail ? "Mark Resource Unavailable (Trigger Replan)" : "Mark Resource Available (Trigger Replan)";
        btnToggle.className = isAvail 
            ? "w-full py-2.5 bg-secondary-container text-on-secondary-container font-label-caps text-label-caps uppercase rounded hover:bg-error-container transition-colors border border-on-secondary-container flex items-center justify-center gap-2"
            : "w-full py-2.5 bg-primary text-on-primary font-label-caps text-label-caps uppercase rounded hover:bg-primary-fixed transition-colors flex items-center justify-center gap-2";
    }
}

async function toggleSelectedResourceStatus() {
    if (!selectedResourceId) return;
    await toggleResource(selectedResourceId);
}

async function toggleResource(resId) {
    if (!operationalState) return;
    const r = (operationalState.resources || []).find(item => item.id === resId);
    if (!r) return;

    const newStatus = (r.status === "available" || r.status === "standby") ? "unavailable" : "available";
    try {
        const res = await fetch(`${API_BASE}/api/state/update`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ resource_id: resId, status: newStatus })
        });
        const data = await res.json();
        if (data.status === "success") {
            showToast(`Resource ${resId} marked ${newStatus.toUpperCase()}. Replan complete!`, "success");
            await refreshState();
        } else {
            showToast(data.message || "Failed to update resource", "error");
        }
    } catch (err) {
        showToast("Error updating resource status", "error");
    }
}

function renderTimelineView(state) {
    const rowsContainer = document.getElementById("timeline-rows");
    const timeline = state.timeline || [];
    const metricEvents = document.getElementById("metric-total-events");
    if (metricEvents) metricEvents.textContent = timeline.length;

    if (!rowsContainer) return;

    if (!timeline.length) {
        rowsContainer.innerHTML = `<p class="text-on-surface-variant text-xs p-4">No logged events recorded.</p>`;
        return;
    }

    rowsContainer.innerHTML = timeline.slice().reverse().map(ev => {
        const timeStr = ev.occurred_at ? new Date(ev.occurred_at).toLocaleTimeString() : "--:--";
        let typeBadge = `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-primary/10 border border-primary/20 text-primary font-label-caps text-[10px] uppercase">${ev.type || 'Event'}</span>`;
        if (ev.severity === "critical" || ev.type === "incident_reported") {
            typeBadge = `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-error/10 border border-error/20 text-error font-label-caps text-[10px] uppercase"><span class="w-1 h-1 rounded-full bg-error"></span> Incident</span>`;
        } else if (ev.type === "resource_update") {
            typeBadge = `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-tertiary/10 border border-tertiary/20 text-tertiary font-label-caps text-[10px] uppercase">Resource</span>`;
        }

        return `
            <div class="grid grid-cols-12 gap-unit px-container-padding py-3 hover:bg-surface-container-low items-center transition-colors">
                <div class="col-span-3 font-data-mono text-data-mono text-on-surface text-[12px]">${timeStr}</div>
                <div class="col-span-2">${typeBadge}</div>
                <div class="col-span-5 font-body-sm text-body-sm text-on-surface truncate">
                    <span class="font-bold block">${ev.title || 'Event Log'}</span>
                    <span class="text-on-surface-variant text-[11px]">${ev.details || ''}</span>
                </div>
                <div class="col-span-2 text-right font-data-mono text-[11px] uppercase ${ev.severity === 'critical' ? 'text-error font-bold' : 'text-on-surface-variant'}">${ev.severity || 'Normal'}</div>
            </div>
        `;
    }).join("");
}

function filterTimeline() {
    const q = (document.getElementById("history-search-input")?.value || "").toLowerCase();
    const typeFilter = document.getElementById("history-type-filter")?.value || "all";
    if (!operationalState || !operationalState.timeline) return;

    const filtered = operationalState.timeline.filter(ev => {
        const matchQ = !q || (ev.title && ev.title.toLowerCase().includes(q)) || (ev.details && ev.details.toLowerCase().includes(q));
        const matchT = typeFilter === "all" || (ev.type && ev.type.includes(typeFilter));
        return matchQ && matchT;
    });

    renderTimelineView({ ...operationalState, timeline: filtered });
}

// ── Command Submission & Natural Language Dispatch ─────────────────────────

async function handleCommandSubmit() {
    const inputEl = document.getElementById("live-command-input");
    const zoneEl = document.getElementById("live-zone-hint");
    const btnText = document.getElementById("btn-analyze-text");
    const btn = document.getElementById("btn-analyze");

    const text = inputEl ? inputEl.value.trim() : "";
    const zoneHint = zoneEl ? zoneEl.value : null;

    if (!text) {
        showToast("Please enter an incident, resource status, or query.", "error");
        return;
    }

    if (btnText) btnText.textContent = "PROCESSING...";
    if (btn) btn.disabled = true;

    try {
        const res = await fetch(`${API_BASE}/api/input/execute`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text, zone_id_hint: zoneHint || null })
        });
        const data = await res.json();

        // 1. Validation Gate: Rejected
        if (data.status === "rejected") {
            showToast(`Rejected: ${data.reason}`, "error");
            return;
        }

        // 2. Validation Gate: Clarify
        if (data.status === "clarify") {
            openClarificationModal(data);
            return;
        }

        // 3. Validation Gate: Error
        if (data.status === "error") {
            showToast(data.message || "Failed to process command", "error");
            return;
        }

        // 4. Success: Handled
        showToast(`Command executed successfully [Intent: ${data.intent || 'processed'} | Source: ${data.source || 'core'}]`, "success");

        // Update tag
        const tag = document.getElementById("input-source-tag");
        if (tag) tag.textContent = `Source: ${(data.source || 'Core').toUpperCase()}`;

        // Clear input
        if (inputEl) inputEl.value = "";

        // Refresh entire state
        await refreshState();

        // If query intent, show query answer
        if (data.intent === "query" && data.answer) {
            alert(`FLOWSHIELD QUERY ANSWER:\n\n${data.answer}`);
        } else if (data.intent === "incident") {
            // Focus on incidents tab
            switchTab("incidents");
        }
    } catch (err) {
        console.error("Submit error:", err);
        showToast("Server connection error during command execution", "error");
    } finally {
        if (btnText) btnText.textContent = "ANALYZE & DISPATCH";
        if (btn) btn.disabled = false;
    }
}

function setScenarioText(text, zoneHint = "") {
    const inputEl = document.getElementById("live-command-input");
    const zoneEl = document.getElementById("live-zone-hint");
    if (inputEl) {
        inputEl.value = text;
        inputEl.focus();
    }
    if (zoneEl && zoneHint) {
        zoneEl.value = zoneHint;
    }
}

// ── Simulation Engine ──────────────────────────────────────────────────────

async function executeSimulation() {
    const queryEl = document.getElementById("sim-query-input");
    const targetEl = document.getElementById("sim-resource-target");
    const rainEl = document.getElementById("slider-rain");
    const btn = document.getElementById("btn-run-sim");

    const text = queryEl ? queryEl.value.trim() : "Custom simulation";
    const resTarget = targetEl ? targetEl.value : null;
    const rainVal = rainEl ? parseFloat(rainEl.value) : 120.0;

    if (btn) btn.disabled = true;

    try {
        const res = await fetch(`${API_BASE}/api/simulation`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                text: text,
                resource_unavailable: resTarget,
                rainfall_increase: { zone_id: "W12-C", rainfall_mm_hr: rainVal }
            })
        });
        const data = await res.json();
        if (data.status === "success" && data.simulation) {
            const sim = data.simulation;
            const assignedEl = document.getElementById("sim-outcome-assigned");
            const gapsEl = document.getElementById("sim-outcome-gaps");
            const strategyList = document.getElementById("sim-strategy-list");

            if (assignedEl) assignedEl.innerHTML = `${sim.assigned_count} <span class="material-symbols-outlined text-[16px]">check</span>`;
            if (gapsEl) gapsEl.innerHTML = `${sim.gap_count} <span class="material-symbols-outlined text-[16px]">warning</span>`;

            if (strategyList) {
                const actions = sim.response_plan ? sim.response_plan.plan_actions : [];
                if (actions && actions.length > 0) {
                    strategyList.innerHTML = actions.map(pa => `
                        <div class="p-3 bg-surface-container-highest rounded border-l-2 ${pa.approval_state === 'required' ? 'border-error' : 'border-tertiary'}">
                            <div class="flex justify-between items-center mb-1">
                                <span class="font-label-caps text-label-caps text-on-surface">STEP ${pa.step}: ${pa.approval_state === 'required' ? 'ESCALATION / APPROVAL' : 'AUTO ROUTE'}</span>
                                <span class="font-data-mono text-[10px] text-simulation-accent">ETA: ${pa.estimated_travel_minutes || 0}m</span>
                            </div>
                            <p class="font-body-sm text-body-sm text-on-surface-variant">${pa.action_description}</p>
                        </div>
                    `).join("");
                } else {
                    strategyList.innerHTML = `<div class="p-3 bg-surface-container-highest rounded border-l-2 border-[#10b981]">All simulated incidents covered with existing capacity.</div>`;
                }
            }

            showToast("Simulation completed safely — LIVE state remains 100% unmodified.", "success");
        }
    } catch (err) {
        console.error("Simulation error:", err);
        showToast("Error running simulation", "error");
    } finally {
        if (btn) btn.disabled = false;
    }
}

// ── Clarification Modal ────────────────────────────────────────────────────

function openClarificationModal(data) {
    const modal = document.getElementById("modal-clarify");
    const list = document.getElementById("clarify-missing-list");
    const promptEl = document.getElementById("clarify-prompt-text");
    if (!modal) return;

    if (list) {
        const missing = data.missing_information || ["Location or zone detail", "Flood depth / severity"];
        list.innerHTML = missing.map(m => `<li>• Missing: ${m.replace(/_/g, ' ')}</li>`).join("");
    }
    if (promptEl) {
        promptEl.textContent = data.message || "Please provide location details and severity.";
    }

    modal.classList.remove("hidden");
}

async function submitClarification() {
    const extraInput = document.getElementById("clarify-input-extra");
    const origInput = document.getElementById("live-command-input");
    const textExtra = extraInput ? extraInput.value.trim() : "";
    const origText = origInput ? origInput.value.trim() : "";

    const combinedText = `${origText} ${textExtra}`.trim();
    document.getElementById("modal-clarify").classList.add("hidden");

    if (origInput) origInput.value = combinedText;
    await handleCommandSubmit();
}

// ── Emergency Dispatch Modal ───────────────────────────────────────────────

function openEmergencyModal() {
    const modal = document.getElementById("modal-emergency");
    if (modal) modal.classList.remove("hidden");
}

async function submitEmergencyDispatch() {
    const textEl = document.getElementById("emergency-text");
    const zoneEl = document.getElementById("emergency-zone");
    const text = textEl ? textEl.value.trim() : "";
    const zone = zoneEl ? zoneEl.value : "W12-C";

    if (!text) {
        showToast("Please enter critical emergency details", "error");
        return;
    }

    document.getElementById("modal-emergency").classList.add("hidden");
    const inputEl = document.getElementById("live-command-input");
    if (inputEl) inputEl.value = `[CRITICAL EMERGENCY] ${text} in ${zone}`;
    await handleCommandSubmit();
}

// ── Reset Scenario ─────────────────────────────────────────────────────────

async function resetScenario() {
    if (!confirm("Are you sure you want to reset the operational state to the baseline Ward 12 scenario?")) {
        return;
    }
    try {
        const res = await fetch(`${API_BASE}/api/reset`, { method: "POST" });
        const data = await res.json();
        if (data.status === "success") {
            showToast("Scenario reset to Ward 12 baseline state.", "success");
            await refreshState();
        }
    } catch (err) {
        showToast("Failed to reset scenario", "error");
    }
}

// ── Toasts & Clock Helpers ─────────────────────────────────────────────────

function showToast(msg, type = "info") {
    const container = document.getElementById("toast-container");
    if (!container) return;

    const toast = document.createElement("div");
    let bg = "bg-surface-container border-primary text-on-surface";
    let icon = "info";
    if (type === "error") {
        bg = "bg-secondary-container border-error text-on-secondary-container";
        icon = "error";
    } else if (type === "success") {
        bg = "bg-surface-container-high border-[#10b981] text-on-surface";
        icon = "check_circle";
    }

    toast.className = `p-3 rounded border shadow-xl flex items-center gap-2.5 font-body-sm text-body-sm transition-all transform duration-300 ${bg}`;
    toast.innerHTML = `
        <span class="material-symbols-outlined text-[18px]">${icon}</span>
        <span class="flex-1">${msg}</span>
    `;

    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = "0";
        setTimeout(() => toast.remove(), 300);
    }, 4500);
}

function updateClocks() {
    const now = new Date();
    const timeStr = now.toISOString().slice(11, 19) + "Z";
    const sidebarTime = document.getElementById("sidebar-time");
    const footerTime = document.getElementById("footer-time");
    if (sidebarTime) sidebarTime.textContent = timeStr.slice(0, 5) + " UTC";
    if (footerTime) footerTime.textContent = `SYS_TIME: ${timeStr}`;
}

// ── Initialization ─────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
    refreshState();
    setInterval(updateClocks, 1000);
    setInterval(refreshState, 15000); // Auto-refresh state every 15s
});
