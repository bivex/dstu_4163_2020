// Портал підписання — фронтенд-логіка.
// Інтеграція з FastAPI бекендом (той самий origin) + клієнтський підпис КЕП
// через EUSign (euscpfactory.js із submodule external/EUSignES6, подається
// під /eusign/). Приватний ключ не покидає браузер — на сервер іде лише CMS.

const API = "";  // той самий origin, що й статика

// --- EUSign: динамічний імпорт фабрики (файловий режим) + iframe-віджет ІІТ (токен) ---
const WIDGET_URI = "https://eu.iit.com.ua/sign-widget/v20200922/";
let euSignFactory = null;
let euReady = false;
let euWidget = null;          // обʼєкт EndUser (міст до iframe-віджета ІІТ)
let widgetInited = false;

async function initEUSign() {
  const st = document.getElementById("euStatus");
  try {
    const mod = await import("/eusign/modules/euscpfactory.js");
    euSignFactory = mod.euSignFactory;
    euSignFactory.onChangeCAs = renderCAs;
    euSignFactory.onerror = (m) => toast("EUSign: " + m);
    // дочекатися завантаження переліку КНЕДП
    const wait = setInterval(() => {
      if (euSignFactory.isReady && euSignFactory.isReady()) {
        clearInterval(wait);
        euReady = true;
        renderCAs();
        st.textContent = "EUSign готовий. Оберіть спосіб ключа.";
        document.getElementById("signBtn").disabled = false;
      }
    }, 400);
    document.getElementById("keyFile").onchange = (e) => {
      const f = e.target.files;
      euSignFactory.setPrivateKeyFile(f.length ? f[0] : null);
    };
    document.getElementById("keySource").onchange = onKeySourceChange;
  } catch (err) {
    st.textContent = "Не вдалося завантажити EUSign: " + err
      + " — підпис недоступний, решта порталу працює.";
  }
}

// Перемикання файл/токен. Токен-режим піднімає офіційний iframe-віджет ІІТ
// (eu.iit.com.ua/sign-widget) — він вантажить крипто сам і бачить підключені
// носії через «ІІТ Користувач ЦСК». Файловий режим — WASM-збірка EUSign.
function onKeySourceChange() {
  const mode = document.getElementById("keySource").value;
  const tokenWrap = document.getElementById("tokenWrap");
  const fileWrap = document.getElementById("fileWrap");
  if (mode === "token") {
    fileWrap.style.display = "none";
    tokenWrap.style.display = "";
    initWidget();
  } else {
    tokenWrap.style.display = "none";
    fileWrap.style.display = "";
  }
}

// Підняти iframe-віджет ІІТ через офіційний helper EndUser (eusign.js).
function initWidget() {
  if (widgetInited) return;
  const hint = document.getElementById("tokenHint");
  if (typeof EndUser === "undefined") {
    hint.innerHTML = '<span style="color:var(--bad)">Не завантажено eusign.js (helper ' +
      'віджета ІІТ).</span>';
    return;
  }
  try {
    euWidget = new EndUser(
      "sign-widget-parent",   // батьківський елемент
      "sign-widget",          // id iframe
      WIDGET_URI,             // офіційний віджет ІІТ
      EndUser.FormType.SignFile
    );
    euWidget.AddEventListener(EndUser.EventType.ConfirmKSPOperation, () => {});
    widgetInited = true;
    hint.innerHTML = "Віджет ІІТ завантажено. Оберіть носій/файл усередині віджета, " +
      "зчитайте ключ, далі натисніть «Підписати поточним у черзі».";
  } catch (e) {
    hint.innerHTML = '<span style="color:var(--bad)">Помилка ініціалізації віджета: ' +
      e + '. Перевірте, що домен дозволено у віджеті ІІТ.</span>';
  }
}

function renderCAs() {
  if (!euSignFactory || !euSignFactory.CAsServers) return;
  const sel = document.getElementById("caSelect");
  sel.innerHTML = "";
  euSignFactory.CAsServers.forEach((s) => {
    const o = document.createElement("option");
    o.text = s.title;
    sel.add(o);
  });
}

// --- API helpers ---
async function api(path, method = "GET", body = null) {
  const opt = { method, headers: { "Content-Type": "application/json" } };
  if (body) opt.body = JSON.stringify(body);
  const r = await fetch(API + path, opt);
  const txt = await r.text();
  const data = txt ? JSON.parse(txt) : {};
  if (!r.ok) throw new Error(data.detail || r.status);
  return data;
}

function docId() { return document.getElementById("docId").value.trim(); }

function readEditor() {
  const signers = document.getElementById("signers").value
    .split("\n").map((l) => l.trim()).filter(Boolean)
    .map((l, i) => {
      const [name, pos] = l.split("|").map((s) => s.trim());
      return { order_index: i, full_name: name, position: pos || "" };
    });
  const eSig = signers.map((s) => ({
    signer: s.full_name, signer_position: s.position,
    certificate_serial: "—", issuer: "—",
    valid_from: "", valid_to: "", timestamp: "",
  }));
  return {
    doc_id: docId(),
    org_name: document.getElementById("orgName").value,
    doc_type: document.getElementById("docType").value,
    title: document.getElementById("title").value,
    reg_index: document.getElementById("regIndex").value,
    date_text: document.getElementById("dateText").value,
    fmt: document.getElementById("fmt").value,
    is_electronic: true,
    body: document.getElementById("body").value.split("\n").map((s) => s.trim()).filter(Boolean),
    signature_position: signers[0]?.position || "",
    signature_name: signers[0]?.full_name || "",
    e_signatures: eSig,
    signers,
    retention_years: 5,
  };
}

// --- дії ---
window.createDoc = async () => {
  try { await api("/documents", "POST", readEditor()); toast("Чернетку створено"); refresh(); }
  catch (e) { toast("Помилка: " + e.message); }
};

window.generateDoc = async () => {
  try {
    const r = await api(`/documents/${docId()}/generate`, "POST");
    renderReport(r.report); toast("Згенеровано та перевірено"); refresh();
  } catch (e) { toast("Помилка: " + e.message); }
};

window.downloadDoc = () => { window.open(`${API}/documents/${docId()}/download`, "_blank"); };

window.deleteDoc = async () => {
  if (!confirm(`Видалити документ ${docId()} разом із підписами та аудитом?`)) return;
  try {
    await api(`/documents/${docId()}`, "DELETE");
    toast("Документ видалено — можна створити заново");
    document.getElementById("signerList").innerHTML = '<span class="muted">Створіть документ.</span>';
    document.getElementById("docStatus").textContent = "";
    renderReport(null);
    document.getElementById("asiceBtn").disabled = true;
  } catch (e) { toast("Помилка: " + e.message); }
};

window.submitDoc = async () => {
  try { await api(`/documents/${docId()}/submit`, "POST"); toast("Подано у чергу"); refresh(); }
  catch (e) { toast("Помилка: " + e.message); }
};

window.refresh = async () => {
  try {
    const d = await api(`/documents/${docId()}`);
    renderSigners(d); renderReport(d.conformance);
    document.getElementById("docStatus").textContent = "статус: " + d.status;
    document.getElementById("asiceBtn").disabled = !d.has_asice;
  } catch (e) { document.getElementById("signerList").innerHTML =
      `<span class="muted">${e.message}</span>`; }
};

window.downloadAsice = () => {
  window.open(`${API}/documents/${docId()}/download/asice`, "_blank");
};

function renderSigners(d) {
  const el = document.getElementById("signerList");
  if (!d.signers.length) { el.innerHTML = '<span class="muted">Немає підписантів.</span>'; return; }
  el.innerHTML = d.signers.map((s) => `
    <div class="signer">
      <div><b>#${s.order_index} ${s.full_name}</b>
        <div class="status-line">${s.position || ""}${
          s.certificate_serial && s.certificate_serial !== "—"
            ? " · серт. " + s.certificate_serial : ""}</div></div>
      <span class="badge b-${s.status}">${s.status}</span>
    </div>`).join("");
}

function renderReport(rep) {
  const sum = document.getElementById("reportSummary");
  const box = document.getElementById("report");
  if (!rep) { sum.textContent = "Згенеруйте документ для перевірки."; box.innerHTML = ""; return; }
  sum.innerHTML = rep.conforms
    ? `<span class="f-ok">✔ ВІДПОВІДАЄ</span> · правил: ${rep.results.length}, знахідок: ${rep.findings_count}`
    : `<span class="f-bad">✘ НЕ ВІДПОВІДАЄ</span> · знахідок: ${rep.findings_count}`;
  box.innerHTML = rep.results.map((r) => {
    const ok = r.conforms;
    const f = r.findings.map((x) => `<div class="f-bad">— ${x.clause}: ${x.message}</div>`).join("");
    return `<div class="${ok ? "f-ok" : "f-bad"}">${ok ? "✔" : "✘"} ${r.rule_id} <span class="muted">(${r.clause})</span></div>${f}`;
  }).join("");
}

// --- КЕП-підпис поточного у черзі ---
window.signCurrent = async () => {
  if (!euReady) { toast("EUSign ще не готовий"); return; }
  let doc;
  try { doc = await api(`/documents/${docId()}`); }
  catch (e) { toast("Спершу створіть і подайте документ: " + e.message); return; }

  const next = doc.signers.find((s) => s.status === "invited");
  if (!next) { toast("Немає активного підписанта (подайте у чергу)"); return; }

  try {
    const mode = document.getElementById("keySource").value;

    // 2) отримати з сервера точні байти ASiCManifest поточного підписанта
    //    і підписати саме їх DETACHED-CAdES — так підпис покриває digest
    //    документа за ETSI EN 319 162-1 (інакше «помилка 33»).
    const mr = await fetch(`${API}/documents/${docId()}/manifest`);
    if (!mr.ok) { toast("Не вдалося отримати манІфест: " + (await mr.text())); return; }
    const manifest = await mr.text();

    let cmsB64;

    if (mode === "token") {
      // --- апаратний токен через офіційний iframe-віджет ІІТ ---
      if (!euWidget) { toast("Віджет ІІТ не ініціалізовано"); return; }
      // ключ зчитується всередині віджета (носій + пароль вводяться там)
      await euWidget.ReadPrivateKey();
      // SignData: external=true (detached), asBase64String=true,
      // signAlgo за замовч. (DSTU4145WithGOST34311), signType CAdES_X_Long
      cmsB64 = await euWidget.SignData(
        manifest, true, true,
        EndUser.SignAlgo.DSTU4145WithGOST34311,
        null,
        EndUser.SignType.CAdES_X_Long
      );
    } else {
      // --- файловий ключ через WASM-збірку EUSign ---
      const password = document.getElementById("keyPass").value;
      const caIdx = document.getElementById("caSelect").selectedIndex;
      euSignFactory.setCASettings(caIdx < 0 ? -1 : caIdx);
      euSignFactory.pkFilePassword = password;
      euSignFactory.pkFileItemIndex = -1;
      euSignFactory.readPrivateKeyButtonClick();
      if (!euSignFactory.pkReaded) { toast("Не вдалося прочитати ключ (пароль/файл)"); return; }
      cmsB64 = euSignFactory.signData(manifest, false, true, "def");
    }

    if (!cmsB64) { toast("Підпис не сформовано"); return; }

    // 3) відправити готову detached-КЕП на сервер (приватний ключ лишився у браузері)
    await api(`/documents/${docId()}/sign`, "POST", {
      signer_order_index: next.order_index,
      signature_b64: cmsB64,
      signer: next.full_name,
      signer_position: next.position,
    });
    toast(`Підписано: ${next.full_name}`);
    refresh();
  } catch (e) { toast("Помилка підпису: " + (e.message || e)); }
};

// --- toast ---
let toastT;
function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg; t.classList.add("show");
  clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove("show"), 3500);
}

// init
initEUSign();
