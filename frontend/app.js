// -*- coding: utf-8 -*-
// Lado cliente (frontend) do Editais Watcher.
//
// Faz chamadas ao backend FastAPI e renderiza a UI
// de coleta/gestão de editais e a aba Perplexity.

const state = {
  config: null,
  defaults: null,
  availableGroups: [],
  regexByGroup: {},
  statusChoices: [],
  statusBg: {},
  statusColors: {},
  minDays: 21,
  minDaysPreset: "10 dias",
  usdBrl: 5.2,
  linkTokens: 0, // tokens estimados do conteúdo do link do edital
};

// ---------- Helpers One-Click (presets salvos em localStorage) ----------

const ONECLICK_KEY = "pplx_oneclick_presets_v1";

function loadOneClickPresets() {
  try {
    const raw = localStorage.getItem(ONECLICK_KEY);
    if (!raw) {
      // presets default
      const d = state.minDays || 21;
      const defaults = [
        {
          id: "amazonia",
          label: `Editais internacionais para aceleradoras na Amazônia (≥ ${d} dias)`,
          prompt: `Editais internacionais para aceleradoras na Amazônia com prazo mínimo de ${d} dias. Liste oportunidades relevantes, com links oficiais.`,
        },
        {
          id: "phil",
          label: `Filantropia global para clima & biodiversidade (≥ ${d} dias)`,
          prompt: `Filantropia global para clima & biodiversidade com prazo mínimo de ${d} dias. Liste oportunidades relevantes, com links oficiais.`,
        },
        {
          id: "gov",
          label: `Chamadas governamentais Brasil/LatAm focadas em inovação (≥ ${d} dias)`,
          prompt: `Chamadas governamentais Brasil/LatAm focadas em inovação com prazo mínimo de ${d} dias. Liste oportunidades relevantes, com links oficiais.`,
        },
      ];
      localStorage.setItem(ONECLICK_KEY, JSON.stringify(defaults));
      return defaults;
    }
    const arr = JSON.parse(raw);
    if (Array.isArray(arr)) return arr;
  } catch (e) {
    console.warn("erro ao carregar presets one-click", e);
  }
  return [];
}

function saveOneClickPresets(presets) {
  try {
    localStorage.setItem(ONECLICK_KEY, JSON.stringify(presets || []));
  } catch (e) {
    console.warn("erro ao salvar presets one-click", e);
  }
}

// flags de controle de long running tasks
let collectCancelRequested = false;
let diagAbortController = null;
let diagWindow = null;

// Helper simples para GET/POST no backend
async function apiGet(path, options = {}) {
  const resp = await fetch(path, {
    signal: options.signal,
  });
  if (!resp.ok) {
    throw new Error(`GET ${path} -> ${resp.status}`);
  }
  return await resp.json();
}

async function apiPost(path, body, options = {}) {
  const resp = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body || {}),
    signal: options.signal,
  });
  if (!resp.ok) {
    throw new Error(`POST ${path} -> ${resp.status}`);
  }
  return await resp.json();
}

// Desabilita/habilita interações na aba de gestão inteira
function setManageInteractivity(disabled) {
  const tab = document.getElementById("tab-manage");
  if (!tab) return;
  const els = tab.querySelectorAll("button, input, select, textarea");
  els.forEach((el) => {
    if (el.dataset.keepEnabled === "true") return;
    el.disabled = disabled;
  });
}

// Atualiza seção de erros genéricos
function renderErrors(errors, containerId = "errors-section") {
  const section = document.getElementById(containerId);
  const list = document.getElementById(
    containerId === "errors-section" ? "errors-list" : "pplx-errors-list"
  );
  if (!section || !list) return;
  list.innerHTML = "";
  if (!errors || errors.length === 0) {
    section.classList.add("hidden");
    return;
  }
  section.classList.remove("hidden");
  for (const [i, err] of errors.entries()) {
    const div = document.createElement("div");
    div.className = "error-item";
    div.innerHTML = `<strong>${i + 1}. [${err.ts}] ${err.where}</strong><br>${
      err.msg
    }<br><details><summary>Stacktrace</summary><pre>${err.stack}</pre></details>`;
    list.appendChild(div);
  }
}

// ---------- Inicialização de config ----------

async function loadConfig() {
  const data = await apiGet("/api/config");
  const cfg = data.config;
  state.config = cfg.config || {};
  state.defaults = cfg.defaults || {};
  state.availableGroups = cfg.available_groups || [];
  state.regexByGroup = cfg.regex_by_group || {};
  state.statusChoices = cfg.status_choices || [];
  state.statusBg = cfg.status_bg || {};
  state.statusColors = cfg.status_colors || {};

  // MIN_DAYS e PRESET
  const minDaysStr = state.config["MIN_DAYS"] || "21";
  state.minDays = parseInt(minDaysStr, 10) || 21;
  state.minDaysPreset = state.config["MIN_DAYS_PRESET"] || "10 dias";
  state.usdBrl = parseFloat(state.config["USD_BRL"] || "5.2");

  // Atualiza campo de dias na aba Perplexity, se existir
  const diasInput = document.getElementById("pplx-dias");
  if (diasInput) {
    diasInput.value = state.minDays.toString();
  }

  renderConfigUI();
  renderGroupsCheckboxes();
  renderGroups();
  renderErrors(data.errors);

  // Atualiza prompt/modelo Perplexity com o novo minDays/cotação
  try {
    recomputeTemplatePrompt();
  } catch (e) {
    // ignora se elementos ainda não estiverem no DOM
  }
}

// Renderiza campos de config (prazo mínimo e cotação)
function renderConfigUI() {
  const presetSelect = document.getElementById("preset-min-days");
  const customInput = document.getElementById("custom-min-days");
  const usdInput = document.getElementById("usd-brl");

  if (!presetSelect || !customInput || !usdInput) return;

  // Ajusta cotação USD->BRL (Perplexity)
  usdInput.value = state.usdBrl.toString();

  // Descobre qual preset bate com o valor atual
  let presetLabel = state.minDaysPreset;
  const mapPreset = { 7: "7 dias", 10: "10 dias", 15: "15 dias" };
  const reverseMap = {
    "7 dias": "7",
    "10 dias": "10",
    "15 dias": "15",
    Personalizado: "custom",
  };

  if (!["7 dias", "10 dias", "15 dias"].includes(presetLabel)) {
    const candidate = parseInt(presetLabel, 10);
    if (mapPreset[candidate]) {
      presetLabel = mapPreset[candidate];
    } else {
      presetLabel = "10 dias";
    }
  }

  const presetValue = reverseMap[presetLabel] || "10";
  presetSelect.value = presetValue;
  if (presetValue === "custom") {
    customInput.classList.remove("hidden");
    customInput.value = state.minDays.toString();
  } else {
    customInput.classList.add("hidden");
    customInput.value = state.minDays.toString();
  }
}

// Renderiza lista de checkboxes de grupos
function renderGroupsCheckboxes() {
  const container = document.getElementById("groups-checkboxes");
  if (!container) return;
  container.innerHTML = "";
  for (const g of state.availableGroups) {
    const id = `grp-${g.replace(/[^a-z0-9]/gi, "_")}`;
    const wrapper = document.createElement("div");
    wrapper.innerHTML = `
      <label>
        <input type="checkbox" id="${id}" data-group="${g}" checked />
        ${g}
      </label>
    `;
    container.appendChild(wrapper);
  }
}

// ---------- Renderização de grupos / itens ----------

async function renderGroups() {
  const container = document.getElementById("groups-container");
  if (!container) return;
  container.innerHTML = "";

  for (const g of state.availableGroups) {
    const groupDiv = document.createElement("div");
    groupDiv.className = "group-card";
    const regexVal = state.regexByGroup[g] || "";
    const statusOptions = state.statusChoices || [];
    const statusSelectId = `status-filter-${g.replace(/[^a-z0-9]/gi, "_")}`;
    const regexInputId = `regex-${g.replace(/[^a-z0-9]/gi, "_")}`;

    groupDiv.innerHTML = `
      <div class="group-header">
        <div class="group-header-main">
          <button class="group-toggle" data-group="${g}" aria-expanded="true">▾</button>
          <h3>${g}</h3>
        </div>
        <div class="group-toolbar">
          <button class="primary" data-action="save" data-group="${g}">💾 Salvar alterações</button>
          <button class="danger" data-action="delete" data-group="${g}">🗑️ Apagar selecionados</button>
          <label>Regex
            <input type="text" id="${regexInputId}" data-group="${g}" value="${regexVal}" />
          </label>
          <button data-action="save-regex" data-group="${g}">Salvar regex</button>
          <label>Filtro
            <select id="${statusSelectId}" data-group="${g}">
              <option value="Todos">Todos</option>
              ${statusOptions
                .map((s) => `<option value="${s}">${s}</option>`)
                .join("")}
            </select>
          </label>
        </div>
      </div>
      <div class="group-body" data-group-body="${g}">
        <em>Carregando itens...</em>
      </div>
    `;
    container.appendChild(groupDiv);

    // Carrega itens para esse grupo
    const statusSelect = groupDiv.querySelector(`#${statusSelectId}`);
    await loadGroupItems(g, statusSelect.value);

    // Liga eventos dos botões / selects
    const saveBtn = groupDiv.querySelector('button[data-action="save"]');
    const delBtn = groupDiv.querySelector('button[data-action="delete"]');
    const saveRegexBtn = groupDiv.querySelector(
      'button[data-action="save-regex"]'
    );
    const toggleBtn = groupDiv.querySelector(".group-toggle");
    const groupBody = groupDiv.querySelector(".group-body");

    if (saveBtn) {
      saveBtn.addEventListener("click", () => saveGroupChanges(g));
    }
    if (delBtn) {
      delBtn.addEventListener("click", () => deleteSelectedInGroup(g));
    }
    if (statusSelect) {
      statusSelect.addEventListener("change", () =>
        loadGroupItems(g, statusSelect.value)
      );
    }
    if (saveRegexBtn) {
      saveRegexBtn.addEventListener("click", () => {
        const inp = groupDiv.querySelector(`#${regexInputId}`);
        if (!inp) return;
        updateGroupRegex(g, inp.value);
      });
    }
    if (toggleBtn && groupBody) {
      toggleBtn.addEventListener("click", () => {
        const isHidden = groupBody.classList.toggle("hidden");
        const expanded = !isHidden;
        toggleBtn.setAttribute("aria-expanded", expanded ? "true" : "false");
        toggleBtn.textContent = expanded ? "▾" : "▸";
      });
    }
  }
}

// Carrega itens de um grupo e desenha cards
async function loadGroupItems(group, statusFilter) {
  const bodyDiv = document.querySelector(
    `[data-group-body="${CSS.escape(group)}"]`
  );
  if (!bodyDiv) return;
  bodyDiv.innerHTML = "<em>Carregando itens...</em>";

  const params = new URLSearchParams({ group });
  if (statusFilter && statusFilter !== "Todos") {
    params.set("status", statusFilter);
  }

  try {
    const data = await apiGet(`/api/items?${params.toString()}`);
    const itemsData = data.items;
    renderErrors(data.errors);
    const sources = itemsData.sources || [];
    const total = itemsData.items_count || 0;

    if (total === 0) {
      bodyDiv.innerHTML = "<em>Sem itens para este grupo.</em>";
      return;
    }

    bodyDiv.innerHTML = "";
    for (const src of sources) {
      const sDiv = document.createElement("div");
      sDiv.className = "source-card";
      const count = (src.items || []).length;
      sDiv.innerHTML = `
        <div class="source-header">
          <strong>${src.source}</strong> — ${count} itens
        </div>
        <div class="source-body"></div>
      `;
      const sb = sDiv.querySelector(".source-body");
      for (const it of src.items) {
        const card = document.createElement("div");
        card.className = "item-card";
        card.dataset.uid = it.uid;

        const bg = state.statusBg[it.status] || "#111111";
        card.style.backgroundColor = bg;

        const seenChecked =
          String(it.seen || "").trim().toLowerCase() in {
            "1": 1,
            true: 1,
            sim: 1,
            yes: 1,
            "✅": 1,
          };

        const dnsChecked = !!it.do_not_show;

        card.innerHTML = `
          <div class="item-row">
            <div>
              <div class="item-title">
                ${it.title || "(sem título)"}
              </div>
              <div class="item-caption">
                <a href="${it.link}" target="_blank">${it.link}</a><br/>
                ${it.agency || ""} • ${it.region || ""}
              </div>
            </div>
            <div class="item-field">
              <label>Prazo</label>
              <div>${(it.deadline_iso || "").slice(0, 10) || "—"}</div>
            </div>
            <div class="item-field">
              <label>Status</label>
              <select class="field-status">
                ${state.statusChoices
                  .map(
                    (s) =>
                      `<option value="${s}" ${
                        s === it.status ? "selected" : ""
                      }>${s}</option>`
                  )
                  .join("")}
              </select>
            </div>
            <div class="item-field">
              <label>Observações</label>
              <textarea class="field-notes">${it.notes || ""}</textarea>
            </div>
            <div class="item-field">
              <label>Flags</label>
              <div>
                <label>
                  <input type="checkbox" class="field-delete" />
                  Apagar
                </label><br/>
                <label>
                  <input type="checkbox" class="field-dns" ${
                    dnsChecked ? "checked" : ""
                  } />
                  Não mostrar novamente
                </label><br/>
                <label>
                  <input type="checkbox" class="field-seen" ${
                    seenChecked ? "checked" : ""
                  } />
                  Visto
                </label>
              </div>
            </div>
          </div>
        `;
        sb.appendChild(card);

        // Atualiza cor e salva na planilha ao mudar o status
        const statusSelect = card.querySelector(".field-status");
        if (statusSelect) {
          statusSelect.addEventListener("change", async () => {
            const newStatus = statusSelect.value;
            const newBg = state.statusBg[newStatus] || "#111111";
            card.style.backgroundColor = newBg;

            const notesEl = card.querySelector(".field-notes");
            const dnsChk = card.querySelector(".field-dns");
            const seenChk = card.querySelector(".field-seen");

            try {
              const data = await apiPost("/api/items/update", {
                updates: [
                  {
                    uid: card.dataset.uid,
                    status: newStatus,
                    notes: notesEl ? notesEl.value : "",
                    do_not_show: dnsChk ? dnsChk.checked : false,
                    seen: seenChk ? seenChk.checked : false,
                  },
                ],
              });
              renderErrors(data.errors);
            } catch (err) {
              alert("Erro ao atualizar status: " + err);
            }
          });
        }
      }
      bodyDiv.appendChild(sDiv);
    }
  } catch (e) {
    bodyDiv.innerHTML = `<span style="color:#f88">Erro ao carregar itens: ${e}</span>`;
  }
}

// Salva alterações de todos os itens de um grupo
async function saveGroupChanges(group) {
  const bodyDiv = document.querySelector(
    `[data-group-body="${CSS.escape(group)}"]`
  );
  if (!bodyDiv) return;

  const cards = bodyDiv.querySelectorAll(".item-card");
  const updates = [];
  cards.forEach((card) => {
    const uid = card.dataset.uid;
    if (!uid) return;
    const statusSel = card.querySelector(".field-status");
    const notesEl = card.querySelector(".field-notes");
    const dnsChk = card.querySelector(".field-dns");
    const seenChk = card.querySelector(".field-seen");
    updates.push({
      uid,
      status: statusSel ? statusSel.value : "pendente",
      notes: notesEl ? notesEl.value : "",
      do_not_show: dnsChk ? dnsChk.checked : false,
      seen: seenChk ? seenChk.checked : false,
    });
  });

  if (updates.length === 0) return;

  const btns = document.querySelectorAll(
    `.group-card button[data-action="save"][data-group="${CSS.escape(group)}"]`
  );
  btns.forEach((b) => (b.disabled = true));
  try {
    const data = await apiPost("/api/items/update", { updates });
    renderErrors(data.errors);
    alert("Alterações salvas.");
    // Recarrega itens para refletir cores/status
    const statusSelect = document.querySelector(
      `#status-filter-${group.replace(/[^a-z0-9]/gi, "_")}`
    );
    const status = statusSelect ? statusSelect.value : "Todos";
    await loadGroupItems(group, status);
  } catch (e) {
    alert("Falha ao salvar: " + e);
  } finally {
    btns.forEach((b) => (b.disabled = false));
  }
}

// Apaga itens selecionados para um grupo
async function deleteSelectedInGroup(group) {
  const bodyDiv = document.querySelector(
    `[data-group-body="${CSS.escape(group)}"]`
  );
  if (!bodyDiv) return;

  const cards = bodyDiv.querySelectorAll(".item-card");
  const uids = [];
  cards.forEach((card) => {
    const uid = card.dataset.uid;
    const delChk = card.querySelector(".field-delete");
    if (uid && delChk && delChk.checked) {
      uids.push(uid);
    }
  });

  if (uids.length === 0) {
    alert("Nenhum item selecionado para apagar.");
    return;
  }

  if (!confirm(`Remover ${uids.length} item(ns)?`)) {
    return;
  }

  try {
    const data = await apiPost("/api/items/delete", { uids });
    renderErrors(data.errors);
    alert(`Removidos ${data.result.deleted} item(ns).`);
    const statusSelect = document.querySelector(
      `#status-filter-${group.replace(/[^a-z0-9]/gi, "_")}`
    );
    const status = statusSelect ? statusSelect.value : "Todos";
    await loadGroupItems(group, status);
  } catch (e) {
    alert("Erro ao apagar: " + e);
  }
}

// Atualiza regex de um grupo
async function updateGroupRegex(group, regex) {
  try {
    const data = await apiPost("/api/group/regex", { group, regex });
    state.config = data.config.config;
    state.regexByGroup = data.config.regex_by_group;
    renderErrors(data.errors);
    alert("Regex atualizado.");
  } catch (e) {
    alert("Erro ao atualizar regex: " + e);
  }
}

// ---------- Botões principais de coleta / config ----------

async function handleSaveMinDays() {
  const presetSelect = document.getElementById("preset-min-days");
  const customInput = document.getElementById("custom-min-days");
  const usdInput = document.getElementById("usd-brl");

  let minDays;
  let presetLabel;
  if (presetSelect.value === "custom") {
    minDays = parseInt(customInput.value || "21", 10);
    presetLabel = "Personalizado";
  } else {
    minDays = parseInt(presetSelect.value, 10);
    presetLabel = `${minDays} dias`;
  }

  const updates = [
    { key: "MIN_DAYS", value: String(minDays) },
    { key: "MIN_DAYS_PRESET", value: presetLabel },
  ];

  const usdVal = parseFloat(usdInput.value || "5.2");
  if (!isNaN(usdVal)) {
    updates.push({ key: "USD_BRL", value: String(usdVal) });
  }

  try {
    const data = await apiPost("/api/config", { updates });
    state.config = data.config.config;
    state.regexByGroup = data.config.regex_by_group;
    state.minDays = minDays;
    state.minDaysPreset = presetLabel;
    state.usdBrl = usdVal;
    renderErrors(data.errors);
    alert("Configuração de prazo/US$ atualizada.");
  } catch (e) {
    alert("Erro ao salvar configuração: " + e);
  }
}

// Coleta: botão principal (agora com progresso, cancelamento e execução por grupo)
async function handleRunCollect() {
  const btn = document.getElementById("btn-run-collect");
  const resultDiv = document.getElementById("collect-result");
  const progressOverlay = document.getElementById("collect-progress");
  const progressBar = document.getElementById("collect-progress-bar");
  const progressLabel = document.getElementById("collect-progress-label");
  if (!btn || !resultDiv) return;

  const selectedGroups = [];
  document
    .querySelectorAll("#groups-checkboxes input[type=checkbox]")
    .forEach((chk) => {
      if (chk.checked) {
        selectedGroups.push(chk.dataset.group);
      }
    });

  let groupsToRun =
    selectedGroups.length > 0
      ? selectedGroups.slice()
      : (state.availableGroups || []).slice();

  if (!groupsToRun.length) {
    resultDiv.innerHTML = "<em>Nenhum grupo disponível para coleta.</em>";
    return;
  }

  collectCancelRequested = false;
  resultDiv.innerHTML = "";
  btn.disabled = true;

  setManageInteractivity(true);
  if (progressOverlay && progressBar && progressLabel) {
    progressOverlay.classList.remove("hidden");
    progressBar.max = groupsToRun.length;
    progressBar.value = 0;
    progressLabel.textContent = "Iniciando coleta…";
  }

  let totalFixed = 0;
  let totalNew = 0;
  const perGroupSummary = [];

  try {
    for (let i = 0; i < groupsToRun.length; i++) {
      const g = groupsToRun[i];

      if (progressLabel) {
        progressLabel.textContent = `Coletando grupo ${g} (${
          i + 1
        } de ${groupsToRun.length})…`;
      }

      try {
        const data = await apiPost("/api/collect", {
          groups: [g],
          min_days: state.minDays,
        });
        const res = data.result || {};
        renderErrors(data.errors);
        const fixed = res.fixed_links || 0;
        const ne = res.new_items || 0;
        totalFixed += fixed;
        totalNew += ne;
        perGroupSummary.push(
          `${g}: links corrigidos ${fixed}, novos itens ${ne}`
        );
      } catch (e) {
        perGroupSummary.push(`${g}: erro na coleta (${e})`);
      }

      if (progressBar) {
        progressBar.value = i + 1;
      }

      if (collectCancelRequested && i < groupsToRun.length - 1) {
        if (progressLabel) {
          progressLabel.textContent =
            "Cancelado pelo usuário. Interrompendo após o grupo atual…";
        }
        break;
      }
    }

    const cancelouAntesDoFim =
      collectCancelRequested && perGroupSummary.length < groupsToRun.length;

    const headerLine = cancelouAntesDoFim
      ? "⚠️ Coleta cancelada antes de completar todos os grupos.<br/>"
      : "✔️ Coleta concluída.<br/>";

    resultDiv.innerHTML =
      `${headerLine}` +
      `Links corrigidos: ${totalFixed}<br/>` +
      `Novos itens gravados (sem duplicar): ${totalNew}<br/><br/>` +
      perGroupSummary.map((s) => `• ${s}`).join("<br/>");

    await renderGroups();
  } finally {
    btn.disabled = false;
    setManageInteractivity(false);
    if (progressOverlay) {
      progressOverlay.classList.add("hidden");
    }
  }
}

// Recarregar apenas da planilha
async function handleRefreshItems() {
  await renderGroups();
}

// Limpar todos os itens
async function handleClearAll() {
  if (!confirm("Tem certeza que deseja limpar TODOS os itens?")) {
    return;
  }
  try {
    const data = await apiPost("/api/items/clear", {});
    renderErrors(data.errors);
    await renderGroups();
    alert("Planilha 'items' limpa (somente cabeçalho mantido).");
  } catch (e) {
    alert("Erro ao limpar itens: " + e);
  }
}

// Diagnóstico: abre em nova janela, com barra de progresso e cancelamento
async function handleRunDiag() {
  const reGovInp = document.getElementById("diag-re-gov");
  const rePhilInp = document.getElementById("diag-re-phil");
  const reLatamInp = document.getElementById("diag-re-latam");
  const container = document.getElementById("diag-results");
  const progressOverlay = document.getElementById("diag-progress");
  const progressBar = document.getElementById("diag-progress-bar");
  const progressLabel = document.getElementById("diag-progress-label");
  if (!container) return;

  const reGov = reGovInp ? reGovInp.value || "" : "";
  const rePhil = rePhilInp ? rePhilInp.value || "" : "";
  const reLatam = reLatamInp ? reLatamInp.value || "" : "";

  container.innerHTML = "";
  setManageInteractivity(true);
  if (progressOverlay && progressLabel) {
    progressOverlay.classList.remove("hidden");
    if (progressBar) {
      progressBar.removeAttribute("value"); // modo indeterminado
    }
    progressLabel.textContent = "Rodando diagnóstico dos providers…";
  }

  diagAbortController = new AbortController();

  try {
    const data = await apiPost(
      "/api/diag/providers",
      {
        re_gov: reGov,
        re_phil: rePhil,
        re_latam: reLatam,
      },
      { signal: diagAbortController.signal }
    );
    const diag = data.diag;
    renderErrors(data.errors);

    container.innerHTML =
      "<em>Diagnóstico concluído. O resultado foi aberto em uma nova janela.</em>";

    // Abre (ou reaproveita) uma nova janela para exibir os resultados
    if (!diagWindow || diagWindow.closed) {
      diagWindow = window.open("", "_blank");
    }
    if (!diagWindow) {
      // popup bloqueado
      return;
    }

    diagWindow.document.open();
    diagWindow.document.write(`
      <!DOCTYPE html>
      <html lang="pt-BR">
        <head>
          <meta charset="UTF-8" />
          <title>Diagnóstico dos providers</title>
          <link rel="stylesheet" href="/static/styles.css" />
        </head>
        <body class="app-main">
          <h1>🔬 Diagnóstico dos providers</h1>
          <section id="diag-window-content"></section>
        </body>
      </html>
    `);
    diagWindow.document.close();

    const contentDiv =
      diagWindow.document.getElementById("diag-window-content");
    if (!contentDiv) {
      return;
    }

    const rows = diag.rows || [];
    const logs = diag.logs || [];

    let html = "<h3>Providers</h3>";
    if (!rows.length) {
      html += "<p><em>Nenhum provider retornado.</em></p>";
    } else {
      html += `<table class="diag-table">
        <thead>
          <tr>
            <th>Grupo</th><th>Fonte</th><th>Itens</th><th>Tempo (s)</th><th>Erro</th><th>Hint</th>
          </tr>
        </thead>
        <tbody>
          ${rows
            .map(
              (r) => `
            <tr>
              <td>${r.Grupo}</td>
              <td>${r.Fonte}</td>
              <td>${r.Itens}</td>
              <td>${r["Tempo (s)"]}</td>
              <td>${r.Erro || ""}</td>
              <td>${r.Hint || ""}</td>
            </tr>
          `
            )
            .join("")}
        </tbody>
      </table>`;
    }

    if (logs.length) {
      html += "<h3>Logs (últimas linhas)</h3><pre>";
      for (const row of logs.slice(1)) {
        html += row.join(" | ") + "\n";
      }
      html += "</pre>";
    }

    contentDiv.innerHTML = html;
  } catch (e) {
    if (e.name === "AbortError") {
      container.innerHTML =
        "<em>Diagnóstico cancelado pelo usuário.</em>";
    } else {
      container.innerHTML = `<span style="color:#f88">Erro no diagnóstico: ${e}</span>`;
    }
  } finally {
    setManageInteractivity(false);
    if (progressOverlay) {
      progressOverlay.classList.add("hidden");
    }
    diagAbortController = null;
  }
}

// ---------- Perplexity UI ----------

function approxTokens(text) {
  if (!text) return 0;
  return Math.max(1, Math.floor(text.length / 4));
}

function getPricingForModel(modelId) {
  const row = document.querySelector(
    `.pplx-cost-table tr[data-model="${CSS.escape(modelId)}"]`
  );
  if (!row) {
    return { pin: 1, pout: 1 };
  }
  const inInput = row.querySelector("input[id^='cost-in']");
  const outInput = row.querySelector("input[id^='cost-out']");
  const pin = parseFloat((inInput && inInput.value) || "1");
  const pout = parseFloat((outInput && outInput.value) || "1");
  return { pin, pout };
}

function updatePplxMetrics(promptText, extraTokensFromLink = 0) {
  const modelSelect = document.getElementById("pplx-model");
  const maxOutInput = document.getElementById("pplx-max");
  const usdInput = document.getElementById("usd-brl");

  if (!modelSelect || !maxOutInput || !usdInput) return;

  const modelId = modelSelect.value;
  const { pin, pout } = getPricingForModel(modelId);

  const maxOut = parseInt(maxOutInput.value || "900", 10);
  const usdBrl = parseFloat(usdInput.value || "5.2");

  const tinPrompt = approxTokens(promptText);
  const tin = tinPrompt + (extraTokensFromLink || 0);

  const custoUsd =
    (tin / 1_000_000.0) * pin + (maxOut / 1_000_000.0) * pout;
  const custoBrl = custoUsd * usdBrl;

  const elIn = document.getElementById("metric-tokens-in");
  const elUsd = document.getElementById("metric-cost-usd");
  const elBrl = document.getElementById("metric-cost-brl");
  if (elIn) elIn.innerText = tin.toString();
  if (elUsd) elUsd.innerText = custoUsd.toFixed(4);
  if (elBrl) elBrl.innerText = custoBrl.toFixed(4);
}

// Gera o prompt final com base na opção Modelo + tema + região + prazo + link
function recomputeTemplatePrompt() {
  const tpl = document.getElementById("pplx-tpl");
  const temaInput = document.getElementById("pplx-tema");
  const regInput = document.getElementById("pplx-reg");
  const diasInput = document.getElementById("pplx-dias");
  const linkInput = document.getElementById("pplx-edital-link");
  const outTa = document.getElementById("pplx-tpl-output");

  if (!outTa || !tpl) return;

  const tema = (temaInput && temaInput.value) || "";
  const reg = (regInput && regInput.value) || "";
  const dias = (diasInput && diasInput.value) || state.minDays;
  const link = (linkInput && linkInput.value) || "";

  let txt = "";
  if (tpl.value === "listar") {
    txt =
      `Liste oportunidades de financiamento (editais) relevantes para ${tema}, ` +
      `com foco em ${reg}, prazo mínimo de ${dias} dias. ` +
      `Considere também o contexto do edital (se aplicável) no seguinte link: ${link || "[nenhum link fornecido]"}. ` +
      `Traga links oficiais e resuma os requisitos principais.`;
  } else if (tpl.value === "resumo") {
    txt =
      `Resuma o edital disponível no seguinte link: ${link || "[cole aqui o link do edital]"}. ` +
      `Explique em português claro: elegibilidade, prazos, valores, critérios de seleção e documentos necessários. ` +
      `Organize a resposta em bullet points e inclua o link novamente no final.`;
  } else {
    txt =
      `Compare o edital do seguinte link principal: ${link || "[cole aqui o link do edital]"} ` +
      `com outras chamadas semelhantes que você encontrar para ${tema} em ${reg}. ` +
      `Destaque diferenças em foco, elegibilidade, prazos e montantes. ` +
      `Produza uma tabela comparativa e bullets com as principais conclusões.`;
  }

  outTa.value = txt;
  updatePplxMetrics(txt, state.linkTokens);
}

function getPplxPromptAndModeLabel() {
  const tpl = document.getElementById("pplx-tpl");
  const outTa = document.getElementById("pplx-tpl-output");
  const tplVal = tpl ? tpl.value : "listar";
  let label;
  if (tplVal === "listar") {
    label = "Modelos: listar oportunidades";
  } else if (tplVal === "resumo") {
    label = "Modelos: resumo de edital";
  } else {
    label = "Modelos: comparar chamadas";
  }
  return {
    prompt: outTa ? outTa.value : "",
    modeLabel: label,
  };
}

// Botão que conta tokens do conteúdo do link (PDF/HTML/etc) via backend
async function handleCountTokensFromLink() {
  const linkInput = document.getElementById("pplx-edital-link");
  const display = document.getElementById("pplx-link-tokens");
  if (!linkInput || !display) return;

  const url = (linkInput.value || "").trim();
  if (!url) {
    alert("Insira o link do edital primeiro.");
    return;
  }

  display.textContent = "Calculando…";

  try {
    const data = await apiPost("/api/perplexity/count_tokens", { url });
    renderErrors(data.errors, "pplx-errors");

    if (!data.ok) {
      display.textContent = "Não foi possível calcular";
      alert("Erro ao calcular tokens: " + (data.error || "desconhecido"));
      return;
    }

    const tokens = data.tokens || 0;
    state.linkTokens = tokens;
    display.textContent = `${tokens} tokens (aprox.)`;

    const { prompt } = getPplxPromptAndModeLabel();
    updatePplxMetrics(prompt, state.linkTokens);
  } catch (e) {
    display.textContent = "Erro";
    alert("Erro ao calcular tokens: " + e);
  }
}

async function handleRunPerplexity() {
  const btn = document.getElementById("btn-pplx-run");
  if (!btn) return;

  const { prompt, modeLabel } = getPplxPromptAndModeLabel();
  if (!prompt.trim()) {
    alert("Preencha o modelo de prompt / link antes de rodar a pesquisa.");
    return;
  }

  const modelSelect = document.getElementById("pplx-model");
  const tempInput = document.getElementById("pplx-temp");
  const maxOutInput = document.getElementById("pplx-max");
  const saveChk = document.getElementById("pplx-save");
  const usdInput = document.getElementById("usd-brl");
  const editalLinkInput = document.getElementById("pplx-edital-link");

  const modeloApi = modelSelect.value;
  const { pin, pout } = getPricingForModel(modeloApi);

  const temp = parseFloat(tempInput.value || "0.2");
  const maxOut = parseInt(maxOutInput.value || "900", 10);
  const usdBrl = parseFloat(usdInput.value || "5.2");
  const save = !!saveChk.checked;
  const editalLink = editalLinkInput ? editalLinkInput.value || null : null;

  // Atualiza métricas antes de enviar (incluindo tokens do link, se já calculados)
  updatePplxMetrics(prompt, state.linkTokens);

  btn.disabled = true;
  const summaryDiv = document.getElementById("pplx-summary");
  const linksUl = document.getElementById("pplx-links");
  summaryDiv.innerHTML = "Consultando Perplexity…";
  linksUl.innerHTML = "";

  try {
    const data = await apiPost("/api/perplexity/search", {
      prompt,
      modelo_api: modeloApi,
      modo_label: modeLabel,
      temperature: temp,
      max_tokens: maxOut,
      pricing_in: pin,
      pricing_out: pout,
      usd_brl: usdBrl,
      save,
      link_tokens: state.linkTokens || 0,
      edital_link: editalLink,
    });
    const res = data.result;
    renderErrors(data.errors, "pplx-errors");

    if (res.error) {
      summaryDiv.innerHTML = `<span style="color:#f88">${res.error}</span>`;
      return;
    }

    summaryDiv.innerText = res.summary || "—";

    linksUl.innerHTML = "";
    (res.links || []).forEach((u) => {
      const li = document.createElement("li");
      li.innerHTML = `<a href="${u}" target="_blank">${u}</a>`;
      linksUl.appendChild(li);
    });

    // Se o backend retornar tokens/custos reais, sobrepõe as métricas
    if (typeof res.tokens_in === "number") {
      const elIn = document.getElementById("metric-tokens-in");
      if (elIn) elIn.innerText = res.tokens_in.toString();
    }
    if (typeof res.estimated_cost_usd === "number") {
      const elUsd = document.getElementById("metric-cost-usd");
      if (elUsd) elUsd.innerText = res.estimated_cost_usd.toFixed(4);
    }
    if (typeof res.estimated_cost_brl === "number") {
      const elBrl = document.getElementById("metric-cost-brl");
      if (elBrl) elBrl.innerText = res.estimated_cost_brl.toFixed(4);
    }
  } catch (e) {
    summaryDiv.innerHTML = `<span style="color:#f88">Erro: ${e}</span>`;
  } finally {
    btn.disabled = false;
  }
}

// ---------- Tabs ----------

function setupTabs() {
  const buttons = document.querySelectorAll(".tab-btn");
  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const tab = btn.dataset.tab;
      document
        .querySelectorAll(".tab-btn")
        .forEach((b) => b.classList.remove("active"));
      document
        .querySelectorAll(".tab-panel")
        .forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById(`tab-${tab}`).classList.add("active");
    });
  });
}

// ---------- Eventos iniciais ----------

window.addEventListener("DOMContentLoaded", async () => {
  setupTabs();

  // Eventos de config
  const presetSelect = document.getElementById("preset-min-days");
  const customInput = document.getElementById("custom-min-days");
  const btnSaveMinDays = document.getElementById("btn-save-min-days");
  const btnRunCollect = document.getElementById("btn-run-collect");
  const btnRefreshItems = document.getElementById("btn-refresh-items");
  const btnClearAll = document.getElementById("btn-clear-all");
  const btnDiag = document.getElementById("btn-diag");
  const btnRunDiag = document.getElementById("btn-run-diag");
  const btnCancelCollect = document.getElementById("btn-cancel-collect");
  const btnCancelDiag = document.getElementById("btn-cancel-diag");
  const pplxTemp = document.getElementById("pplx-temp");
  const pplxTempValue = document.getElementById("pplx-temp-value");
  const pplxRunBtn = document.getElementById("btn-pplx-run");

  const pplxTpl = document.getElementById("pplx-tpl");
  const pplxTema = document.getElementById("pplx-tema");
  const pplxReg = document.getElementById("pplx-reg");
  const pplxDias = document.getElementById("pplx-dias");
  const pplxLink = document.getElementById("pplx-edital-link");
  const pplxCountTokensBtn = document.getElementById("pplx-count-tokens");
  const pplxModelSelect = document.getElementById("pplx-model");

  const pplxHtmlCheckbox = document.getElementById("pplx-html-checkbox");
  const pplxHtmlHelp = document.getElementById("pplx-html-help");
  const pplxPages = document.getElementById("pplx-edital-pages");


  if (pplxHtmlCheckbox && pplxHtmlHelp) {
    pplxHtmlCheckbox.addEventListener("change", () => {
      if (pplxHtmlCheckbox.checked) {
        pplxHtmlHelp.classList.remove("hidden");
      } else {
        pplxHtmlHelp.classList.add("hidden");
      }
    });
  }

  if (pplxPages) {
    pplxPages.addEventListener("input", () => {
      const { prompt } = getPplxPromptAndModeLabel();
      updatePplxMetrics(prompt);
    });
  }

  if (presetSelect && customInput) {
    presetSelect.addEventListener("change", () => {
      if (presetSelect.value === "custom") {
        customInput.classList.remove("hidden");
      } else {
        customInput.classList.add("hidden");
      }
    });
  }

  if (btnSaveMinDays) {
    btnSaveMinDays.addEventListener("click", handleSaveMinDays);
  }
  if (btnRunCollect) {
    btnRunCollect.addEventListener("click", handleRunCollect);
  }
  if (btnRefreshItems) {
    btnRefreshItems.addEventListener("click", handleRefreshItems);
  }
  if (btnClearAll) {
    btnClearAll.addEventListener("click", handleClearAll);
  }
  if (btnDiag) {
    btnDiag.addEventListener("click", toggleDiagSection);
  }
  if (btnRunDiag) {
    btnRunDiag.addEventListener("click", handleRunDiag);
  }
  if (btnCancelCollect) {
    btnCancelCollect.addEventListener("click", () => {
      collectCancelRequested = true;
      const label = document.getElementById("collect-progress-label");
      if (label) {
        label.textContent =
          "Cancelando… aguardando finalizar o grupo atual.";
      }
    });
  }
  if (btnCancelDiag) {
    btnCancelDiag.addEventListener("click", () => {
      if (diagAbortController) {
        diagAbortController.abort();
      }
      const label = document.getElementById("diag-progress-label");
      if (label) {
        label.textContent = "Cancelando diagnóstico…";
      }
    });
  }

  if (pplxTemp && pplxTempValue) {
    pplxTemp.addEventListener("input", () => {
      pplxTempValue.innerText = pplxTemp.value;
    });
  }


  if (pplxRunBtn) {
    pplxRunBtn.addEventListener("click", handleRunPerplexity);
  }

  [pplxTpl, pplxTema, pplxReg, pplxDias, pplxLink].forEach((el) => {
    if (el) {
      el.addEventListener("input", () => {
        recomputeTemplatePrompt();
      });
    }
  });

  if (pplxCountTokensBtn) {
    pplxCountTokensBtn.addEventListener("click", handleCountTokensFromLink);
  }

  if (pplxModelSelect) {
    pplxModelSelect.addEventListener("change", () => {
      const { prompt } = getPplxPromptAndModeLabel();
      updatePplxMetrics(prompt, state.linkTokens);
    });
  }

  document
    .querySelectorAll(".pplx-cost-table input[type='number']")
    .forEach((inp) => {
      inp.addEventListener("input", () => {
        const { prompt } = getPplxPromptAndModeLabel();
        updatePplxMetrics(prompt, state.linkTokens);
      });
    });

  const usdInput = document.getElementById("usd-brl");
  if (usdInput) {
    usdInput.addEventListener("input", () => {
      const { prompt } = getPplxPromptAndModeLabel();
      updatePplxMetrics(prompt, state.linkTokens);
    });
  }

  // Inicializa o prompt/modelo Perplexity
  recomputeTemplatePrompt();

  // Carrega config inicial do backend
  try {
    await loadConfig();
  } catch (e) {
    alert("Erro ao carregar configuração inicial: " + e);
  }
});

// Toggle simples da seção de diagnóstico
async function toggleDiagSection() {
  const sec = document.getElementById("diag-section");
  if (!sec) return;
  sec.classList.toggle("hidden");
}
