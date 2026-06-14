var __require = /* @__PURE__ */ ((x) => typeof require !== "undefined" ? require : typeof Proxy !== "undefined" ? new Proxy(x, {
  get: (a, b) => (typeof require !== "undefined" ? require : a)[b]
}) : x)(function(x) {
  if (typeof require !== "undefined")
    return require.apply(this, arguments);
  throw Error('Dynamic require of "' + x + '" is not supported');
});

// src/app.ts
var API = "";
var WIDGET_URI = "https://eu.iit.com.ua/sign-widget/v20200922/";
var euSignFactory = null;
var euReady = false;
var euWidget = null;
var widgetInited = false;
function el(id) {
  const e = document.getElementById(id);
  if (!e)
    throw new Error(`element #${id} not found`);
  return e;
}
function val(id) {
  return el(id).value;
}
async function initEUSign() {
  const st = el("euStatus");
  try {
    const mod = await import("/eusign/modules/euscpfactory.js");
    const factory = mod.euSignFactory;
    euSignFactory = factory;
    factory.onChangeCAs = renderCAs;
    factory.onerror = (m) => toast("EUSign: " + m);
    const wait = setInterval(() => {
      if (euSignFactory && euSignFactory.isReady && euSignFactory.isReady()) {
        clearInterval(wait);
        euReady = true;
        renderCAs();
        st.textContent = "EUSign готовий. Оберіть спосіб ключа.";
        el("signBtn").disabled = false;
      }
    }, 400);
    el("keyFile").onchange = (e) => {
      const f = e.target.files;
      euSignFactory.setPrivateKeyFile(f && f.length ? f[0] : null);
    };
    el("keySource").onchange = onKeySourceChange;
  } catch (err) {
    st.textContent = "Не вдалося завантажити EUSign: " + err + " — підпис недоступний, решта порталу працює.";
  }
}
function onKeySourceChange() {
  const mode = val("keySource");
  const tokenWrap = el("tokenWrap");
  const fileWrap = el("fileWrap");
  if (mode === "token") {
    fileWrap.classList.add("hidden");
    tokenWrap.classList.remove("hidden");
    initWidget();
  } else {
    tokenWrap.classList.add("hidden");
    fileWrap.classList.remove("hidden");
  }
}
function initWidget() {
  if (widgetInited)
    return;
  const hint = el("tokenHint");
  if (typeof EndUser === "undefined") {
    hint.innerHTML = '<span style="color:var(--bad)">Не завантажено eusign.js ' + "(helper віджета ІІТ).</span>";
    return;
  }
  try {
    euWidget = new EndUser("sign-widget-parent", "sign-widget", WIDGET_URI, EndUser.FormType.ReadPKey);
    const ifr = document.querySelector("#sign-widget-parent iframe");
    const addListener = () => {
      try {
        euWidget?.AddEventListener(EndUser.EventType.ConfirmKSPOperation, () => {});
      } catch {}
    };
    if (ifr)
      ifr.addEventListener("load", addListener, { once: true });
    widgetInited = true;
    hint.innerHTML = "Віджет ІІТ завантажено. Оберіть носій усередині віджета, " + "зчитайте ключ, далі натисніть «Підписати поточним у черзі».";
  } catch (e) {
    hint.innerHTML = '<span style="color:var(--bad)">Помилка ініціалізації віджета: ' + e + ". Перевірте, що домен дозволено у віджеті ІІТ.</span>";
  }
}
function renderCAs() {
  if (!euSignFactory || !euSignFactory.CAsServers)
    return;
  const sel = el("caSelect");
  sel.innerHTML = "";
  euSignFactory.CAsServers.forEach((s) => {
    const o = document.createElement("option");
    o.text = s.title;
    sel.add(o);
  });
}
async function api(path, method = "GET", body = null) {
  const opt = { method, headers: { "Content-Type": "application/json" } };
  if (body)
    opt.body = JSON.stringify(body);
  const r = await fetch(API + path, opt);
  const txt = await r.text();
  const data = txt ? JSON.parse(txt) : {};
  if (!r.ok)
    throw new Error(data.detail || String(r.status));
  return data;
}
function docId() {
  return val("docId").trim();
}
function readEditor() {
  const signers = val("signers").split(`
`).map((l) => l.trim()).filter(Boolean).map((l, i) => {
    const [name, pos] = l.split("|").map((s) => s.trim());
    return { order_index: i, full_name: name, position: pos || "" };
  });
  const eSig = signers.map((s) => ({
    signer: s.full_name,
    signer_position: s.position,
    certificate_serial: "—",
    issuer: "—",
    valid_from: "",
    valid_to: "",
    timestamp: ""
  }));
  return {
    doc_id: docId(),
    org_name: val("orgName"),
    doc_type: val("docType"),
    title: val("title"),
    reg_index: val("regIndex"),
    date_text: val("dateText"),
    fmt: val("fmt"),
    is_electronic: true,
    body: val("body").split(`
`).map((s) => s.trim()).filter(Boolean),
    signature_position: signers[0]?.position || "",
    signature_name: signers[0]?.full_name || "",
    e_signatures: eSig,
    signers,
    retention_years: 5
  };
}
async function createDoc() {
  try {
    await api("/documents", "POST", readEditor());
    selectedDoc = docId();
    toast("Картку збережено");
    reloadDocs();
    refresh();
  } catch (e) {
    try {
      await api(`/documents/${docId()}`, "PUT", readEditor());
      toast("Картку оновлено");
      reloadDocs();
      refresh();
    } catch (e2) {
      toast("Помилка: " + errMsg(e2));
    }
  }
}
async function generateDoc() {
  try {
    const r = await api(`/documents/${docId()}/generate`, "POST");
    renderReport(r.report);
    toast("Згенеровано та перевірено");
    refresh();
  } catch (e) {
    toast("Помилка: " + errMsg(e));
  }
}
function downloadDoc() {
  window.open(`${API}/documents/${docId()}/download`, "_blank");
}
async function deleteDoc() {
  if (!confirm(`Видалити документ ${docId()} разом із підписами та аудитом?`))
    return;
  try {
    await api(`/documents/${docId()}`, "DELETE");
    toast("Документ видалено");
    selectedDoc = null;
    el("detailBody").classList.add("hidden");
    el("detailEmpty").classList.remove("hidden");
    reloadDocs();
  } catch (e) {
    toast("Помилка: " + errMsg(e));
  }
}
async function submitDoc() {
  try {
    await api(`/documents/${docId()}/submit`, "POST");
    toast("Подано у чергу");
    refresh();
    reloadDocs();
  } catch (e) {
    toast("Помилка: " + errMsg(e));
  }
}
async function refresh() {
  try {
    const d = await api(`/documents/${docId()}`);
    renderSigners(d);
    renderReport(d.conformance ?? null);
    el("docStatus").textContent = "статус: " + d.status;
    el("asiceBtn").disabled = !d.has_asice;
    el("submitBtn").disabled = d.status !== "draft";
  } catch (e) {
    el("signerList").innerHTML = `<span class="muted">${errMsg(e)}</span>`;
  }
}
function downloadAsice() {
  window.open(`${API}/documents/${docId()}/download/asice`, "_blank");
}
function renderSigners(d) {
  const box = el("signerList");
  if (!d.signers.length) {
    box.innerHTML = '<span class="muted">Немає підписантів.</span>';
    return;
  }
  const stColor = {
    waiting: "grey",
    invited: "yellow",
    signed: "green",
    rejected: "red"
  };
  const stLabel = {
    waiting: "очікує",
    invited: "у черзі",
    signed: "підписано",
    rejected: "відмова"
  };
  box.innerHTML = '<div class="ui relaxed divided list">' + d.signers.map((s) => `
    <div class="item">
      <div class="right floated content">
        <span class="ui ${stColor[s.status] || "grey"} mini label">${stLabel[s.status] || s.status}</span>
      </div>
      <i class="user circle icon"></i>
      <div class="content">
        <div class="header">#${s.order_index + 1} ${s.full_name}</div>
        <div class="description muted">${s.position || ""}${s.certificate_serial && s.certificate_serial !== "—" ? " · серт. " + s.certificate_serial : ""}</div>
      </div>
    </div>`).join("") + "</div>";
}
function renderReport(rep) {
  const sum = el("reportSummary");
  const box = el("report");
  if (!rep) {
    sum.textContent = "Згенеруйте документ для перевірки.";
    box.innerHTML = "";
    return;
  }
  sum.innerHTML = rep.conforms ? `<div class="ui green label"><i class="check icon"></i>ВІДПОВІДАЄ</div> правил: ${rep.results.length}, знахідок: ${rep.findings_count}` : `<div class="ui red label"><i class="times icon"></i>НЕ ВІДПОВІДАЄ</div> знахідок: ${rep.findings_count}`;
  box.innerHTML = rep.results.map((r) => {
    const ok = r.conforms;
    const f = r.findings.map((x) => `<div class="f-bad">— ${x.clause}: ${x.message}</div>`).join("");
    return `<div class="item"><i class="${ok ? "check green" : "times red"} icon"></i><div class="content"><span class="${ok ? "f-ok" : "f-bad"}">${r.rule_id}</span> <span class="muted">(${r.clause})</span>${f}</div></div>`;
  }).join("");
}
function signOverlayStart(steps, title) {
  const ov = el("signOverlay");
  el("signTitle").textContent = title;
  const seal = el("signSeal");
  seal.className = "sign-seal spin";
  const ul = el("signSteps");
  ul.innerHTML = steps.map((s) => `<li data-k="${s.key}"><span class="ico"></span><span>${s.label}</span></li>`).join("");
  ov.classList.add("show");
}
function signStepActive(key) {
  const ul = el("signSteps");
  ul.querySelectorAll("li").forEach((li) => {
    const k = li.getAttribute("data-k");
    if (k === key)
      li.classList.add("active");
  });
}
function signStepDone(key) {
  const li = el("signSteps").querySelector(`li[data-k="${key}"]`);
  if (li) {
    li.classList.remove("active");
    li.classList.add("done");
  }
}
function signOverlayFinish(ok, failKey) {
  const seal = el("signSeal");
  seal.className = "sign-seal " + (ok ? "done" : "fail");
  if (!ok && failKey) {
    const li = el("signSteps").querySelector(`li[data-k="${failKey}"]`);
    if (li) {
      li.classList.remove("active");
      li.classList.add("err");
    }
  }
  const delay = ok ? 1100 : 1800;
  setTimeout(() => el("signOverlay").classList.remove("show"), delay);
}
var sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function signCurrent() {
  if (!euReady) {
    toast("EUSign ще не готовий");
    return;
  }
  let doc;
  try {
    doc = await api(`/documents/${docId()}`);
  } catch (e) {
    toast("Спершу створіть і подайте документ: " + errMsg(e));
    return;
  }
  const next = doc.signers.find((s) => s.status === "invited");
  if (!next) {
    toast("Немає активного підписанта (подайте у чергу)");
    return;
  }
  const mode = val("keySource");
  const STEPS = [
    { key: "manifest", label: "Формування даних для підпису (манІфест)" },
    { key: "key", label: mode === "token" ? "Зчитування ключа з апаратного носія" : "Зчитування особистого ключа" },
    { key: "sign", label: "Накладання КЕП (ДСТУ 4145)" },
    { key: "send", label: "Передавання підпису на сервер" },
    { key: "done", label: "Підпис зафіксовано у черзі" }
  ];
  signOverlayStart(STEPS, `Підписання: ${next.full_name}`);
  let stepKey = "manifest";
  try {
    signStepActive("manifest");
    const mr = await fetch(`${API}/documents/${docId()}/manifest`);
    if (!mr.ok)
      throw new Error("манІфест: " + await mr.text());
    const manifest = await mr.text();
    signStepDone("manifest");
    let cmsB64;
    if (mode === "token") {
      if (!euWidget)
        throw new Error("віджет ІІТ не ініціалізовано");
      stepKey = "key";
      signStepActive("key");
      await euWidget.ReadPrivateKey();
      signStepDone("key");
      stepKey = "sign";
      signStepActive("sign");
      cmsB64 = await euWidget.SignData(manifest, true, true, EndUser.SignAlgo.DSTU4145WithGOST34311, null, EndUser.SignType.CAdES_X_Long);
    } else {
      if (!euSignFactory)
        throw new Error("EUSign не готовий");
      stepKey = "key";
      signStepActive("key");
      const password = val("keyPass");
      const caIdx = el("caSelect").selectedIndex;
      euSignFactory.setCASettings(caIdx < 0 ? -1 : caIdx);
      euSignFactory.pkFilePassword = password;
      euSignFactory.pkFileItemIndex = -1;
      euSignFactory.readPrivateKeyButtonClick();
      if (!euSignFactory.pkReaded)
        throw new Error("не вдалося прочитати ключ (пароль/файл)");
      signStepDone("key");
      stepKey = "sign";
      signStepActive("sign");
      const manifestBytes = new TextEncoder().encode(manifest);
      cmsB64 = euSignFactory.signData(manifestBytes, false, true, "def");
    }
    if (!cmsB64)
      throw new Error("підпис не сформовано");
    signStepDone("sign");
    stepKey = "send";
    signStepActive("send");
    await api(`/documents/${docId()}/sign`, "POST", {
      signer_order_index: next.order_index,
      signature_b64: cmsB64,
      signer: next.full_name,
      signer_position: next.position
    });
    signStepDone("send");
    signStepActive("done");
    await sleep(300);
    signStepDone("done");
    signOverlayFinish(true);
    toast(`Підписано: ${next.full_name}`);
    refresh();
    reloadDocs();
  } catch (e) {
    signOverlayFinish(false, stepKey);
    toast("Помилка підпису: " + errMsg(e));
  }
}
var CATEGORIES = [
  { key: "all", title: "Всі документи", match: () => true },
  { key: "signing", title: "Підписання", match: (d) => d.status === "pending_signatures" },
  { key: "drafts", title: "Чернетки", match: (d) => d.status === "draft" },
  { key: "processed", title: "Опрацьовані", match: (d) => d.status === "signed" || d.status === "published" }
];
var SECTION_KEYS = new Set(["favorites", "archive", "trash"]);
var allDocs = [];
var activeCat = "all";
var selectedDoc = null;
var searchTerm = "";
async function reloadDocs() {
  try {
    const r = await api("/documents");
    allDocs = r.documents || [];
  } catch (e) {
    allDocs = [];
    toast("Не вдалося завантажити список: " + errMsg(e));
  }
  renderCats();
  renderList();
}
function renderCats() {
  const box = el("cats");
  box.innerHTML = "";
  for (const c of CATEGORIES) {
    const n = allDocs.filter(c.match).length;
    const a = document.createElement("a");
    a.className = "item" + (c.key === activeCat ? " active" : "");
    a.innerHTML = `${c.title}<div class="ui label">${n}</div>`;
    a.onclick = () => {
      activeCat = c.key;
      renderCats();
      renderList();
    };
    box.appendChild(a);
  }
  document.querySelectorAll("[data-c]").forEach((e) => {
    e.textContent = "0";
  });
  document.querySelectorAll(".side .item[data-cat]").forEach((e) => {
    e.onclick = () => {
      const k = e.getAttribute("data-cat");
      if (SECTION_KEYS.has(k)) {
        activeCat = k;
        renderCats();
        renderList();
      }
    };
    e.classList.toggle("active", e.getAttribute("data-cat") === activeCat);
  });
}
function currentList() {
  let docs = allDocs;
  const cat = CATEGORIES.find((c) => c.key === activeCat);
  if (cat)
    docs = docs.filter(cat.match);
  else if (SECTION_KEYS.has(activeCat))
    docs = [];
  if (searchTerm) {
    const q = searchTerm.toLowerCase();
    docs = docs.filter((d) => d.title.toLowerCase().includes(q) || d.doc_id.toLowerCase().includes(q));
  }
  return docs;
}
function statusLabel(s) {
  return {
    draft: "чернетка",
    pending_signatures: "підписання",
    signed: "підписано",
    published: "оприлюднено"
  }[s] || s;
}
function statusColor(s) {
  return {
    draft: "grey",
    pending_signatures: "yellow",
    signed: "green",
    published: "blue"
  }[s] || "grey";
}
function renderList() {
  const titleEl = el("listTitle");
  const cat = CATEGORIES.find((c) => c.key === activeCat);
  titleEl.textContent = cat ? cat.title : { favorites: "Обрані", archive: "Архів", trash: "Кошик" }[activeCat] || "Документи";
  const docs = currentList();
  el("listCount").textContent = String(docs.length);
  const box = el("docList");
  if (!docs.length) {
    box.innerHTML = '<div class="empty">Немає документів у цій категорії.</div>';
    return;
  }
  box.innerHTML = docs.map((d) => {
    const signed = d.signers.filter((s) => s.status === "signed").length;
    const total = d.signers.length;
    return `<div class="item doc${d.doc_id === selectedDoc ? " sel" : ""}" data-id="${d.doc_id}">
      <i class="file alternate outline icon"></i>
      <div class="content">
        <div class="header">${d.title || d.doc_id}</div>
        <div class="description">
          <span class="muted">${d.doc_id}</span>
          <span class="ui ${statusColor(d.status)} mini label">${statusLabel(d.status)}</span>
          ${total ? `<span class="muted">підписів: ${signed}/${total}</span>` : ""}
        </div>
      </div></div>`;
  }).join("");
  box.querySelectorAll(".doc").forEach((e) => {
    e.onclick = () => openDoc(e.getAttribute("data-id"));
  });
}
async function openDoc(id) {
  selectedDoc = id;
  el("docId").value = id;
  el("detailEmpty").classList.add("hidden");
  el("detailBody").classList.remove("hidden");
  renderList();
  await refresh();
  try {
    const d = await api(`/documents/${id}`);
    if (d.title)
      el("title").value = d.title;
  } catch {}
}
function newDocument() {
  selectedDoc = null;
  el("detailEmpty").classList.add("hidden");
  el("detailBody").classList.remove("hidden");
  const stamp = new Date().toISOString().slice(0, 19).replace(/[-:T]/g, "");
  el("docId").value = "DOC-" + stamp;
  el("signerList").innerHTML = '<span class="muted">Збережіть картку.</span>';
  el("docStatus").textContent = "";
  renderReport(null);
  el("asiceBtn").disabled = true;
}
var toastT;
function toast(msg) {
  const t = el("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toastT);
  toastT = setTimeout(() => t.classList.remove("show"), 3500);
}
function errMsg(e) {
  return e instanceof Error ? e.message : String(e);
}
Object.assign(window, {
  createDoc,
  generateDoc,
  downloadDoc,
  deleteDoc,
  submitDoc,
  refresh,
  downloadAsice,
  signCurrent,
  reloadDocs,
  newDocument
});
var searchEl = document.getElementById("search");
if (searchEl) {
  searchEl.oninput = () => {
    searchTerm = searchEl.value.trim();
    renderList();
  };
}
initEUSign();
reloadDocs();
