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
    fileWrap.style.display = "none";
    tokenWrap.style.display = "";
    initWidget();
  } else {
    tokenWrap.style.display = "none";
    fileWrap.style.display = "";
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
    euWidget.AddEventListener(EndUser.EventType.ConfirmKSPOperation, () => {});
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
    toast("Чернетку створено");
    refresh();
  } catch (e) {
    toast("Помилка: " + errMsg(e));
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
    toast("Документ видалено — можна створити заново");
    el("signerList").innerHTML = '<span class="muted">Створіть документ.</span>';
    el("docStatus").textContent = "";
    renderReport(null);
    el("asiceBtn").disabled = true;
  } catch (e) {
    toast("Помилка: " + errMsg(e));
  }
}
async function submitDoc() {
  try {
    await api(`/documents/${docId()}/submit`, "POST");
    toast("Подано у чергу");
    refresh();
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
  box.innerHTML = d.signers.map((s) => `
    <div class="signer">
      <div><b>#${s.order_index} ${s.full_name}</b>
        <div class="status-line">${s.position || ""}${s.certificate_serial && s.certificate_serial !== "—" ? " · серт. " + s.certificate_serial : ""}</div></div>
      <span class="badge b-${s.status}">${s.status}</span>
    </div>`).join("");
}
function renderReport(rep) {
  const sum = el("reportSummary");
  const box = el("report");
  if (!rep) {
    sum.textContent = "Згенеруйте документ для перевірки.";
    box.innerHTML = "";
    return;
  }
  sum.innerHTML = rep.conforms ? `<span class="f-ok">✔ ВІДПОВІДАЄ</span> · правил: ${rep.results.length}, знахідок: ${rep.findings_count}` : `<span class="f-bad">✘ НЕ ВІДПОВІДАЄ</span> · знахідок: ${rep.findings_count}`;
  box.innerHTML = rep.results.map((r) => {
    const ok = r.conforms;
    const f = r.findings.map((x) => `<div class="f-bad">— ${x.clause}: ${x.message}</div>`).join("");
    return `<div class="${ok ? "f-ok" : "f-bad"}">${ok ? "✔" : "✘"} ${r.rule_id} <span class="muted">(${r.clause})</span></div>${f}`;
  }).join("");
}
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
  try {
    const mode = val("keySource");
    const mr = await fetch(`${API}/documents/${docId()}/manifest`);
    if (!mr.ok) {
      toast("Не вдалося отримати манІфест: " + await mr.text());
      return;
    }
    const manifest = await mr.text();
    let cmsB64;
    if (mode === "token") {
      if (!euWidget) {
        toast("Віджет ІІТ не ініціалізовано");
        return;
      }
      await euWidget.ReadPrivateKey();
      cmsB64 = await euWidget.SignData(manifest, true, true, EndUser.SignAlgo.DSTU4145WithGOST34311, null, EndUser.SignType.CAdES_X_Long);
    } else {
      if (!euSignFactory) {
        toast("EUSign не готовий");
        return;
      }
      const password = val("keyPass");
      const caIdx = el("caSelect").selectedIndex;
      euSignFactory.setCASettings(caIdx < 0 ? -1 : caIdx);
      euSignFactory.pkFilePassword = password;
      euSignFactory.pkFileItemIndex = -1;
      euSignFactory.readPrivateKeyButtonClick();
      if (!euSignFactory.pkReaded) {
        toast("Не вдалося прочитати ключ (пароль/файл)");
        return;
      }
      const manifestBytes = new TextEncoder().encode(manifest);
      cmsB64 = euSignFactory.signData(manifestBytes, false, true, "def");
    }
    if (!cmsB64) {
      toast("Підпис не сформовано");
      return;
    }
    await api(`/documents/${docId()}/sign`, "POST", {
      signer_order_index: next.order_index,
      signature_b64: cmsB64,
      signer: next.full_name,
      signer_position: next.position
    });
    toast(`Підписано: ${next.full_name}`);
    refresh();
  } catch (e) {
    toast("Помилка підпису: " + errMsg(e));
  }
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
  signCurrent
});
initEUSign();
