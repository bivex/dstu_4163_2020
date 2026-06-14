// Портал підписання — фронтенд-логіка.
// Інтеграція з FastAPI бекендом (той самий origin) + клієнтський підпис КЕП
// через EUSign (euscpfactory.js із submodule external/EUSignES6, подається
// під /eusign/). Приватний ключ не покидає браузер — на сервер іде лише CMS.

const API = "";  // той самий origin, що й статика

// --- EUSign: динамічний імпорт фабрики ---
let euSignFactory = null;
let euReady = false;

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
        st.textContent = "EUSign готовий. Оберіть КНЕДП, ключ і пароль.";
        document.getElementById("signBtn").disabled = false;
      }
    }, 400);
    document.getElementById("keyFile").onchange = (e) => {
      const f = e.target.files;
      euSignFactory.setPrivateKeyFile(f.length ? f[0] : null);
    };
  } catch (err) {
    st.textContent = "Не вдалося завантажити EUSign: " + err
      + " — підпис недоступний, решта порталу працює.";
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

window.submitDoc = async () => {
  try { await api(`/documents/${docId()}/submit`, "POST"); toast("Подано у чергу"); refresh(); }
  catch (e) { toast("Помилка: " + e.message); }
};

window.refresh = async () => {
  try {
    const d = await api(`/documents/${docId()}`);
    renderSigners(d); renderReport(d.conformance);
    document.getElementById("docStatus").textContent = "статус: " + d.status;
  } catch (e) { document.getElementById("signerList").innerHTML =
      `<span class="muted">${e.message}</span>`; }
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
    // 1) налаштувати ключ та КНЕДП
    const caIdx = document.getElementById("caSelect").selectedIndex;
    euSignFactory.setCASettings(caIdx < 0 ? -1 : caIdx);
    euSignFactory.pkFilePassword = document.getElementById("keyPass").value;
    euSignFactory.pkFileItemIndex = -1;
    euSignFactory.readPrivateKeyButtonClick();
    if (!euSignFactory.pkReaded) { toast("Не вдалося прочитати ключ (пароль/файл)"); return; }

    // 2) підписати дані документа (CMS, внутрішній підпис, з сертифікатом)
    const dataToSign = `${doc.doc_id}|${doc.title}|signer#${next.order_index}`;
    const cms = euSignFactory.signData(dataToSign, true, true, "def");
    if (!cms) { toast("Підпис не сформовано"); return; }

    // 3) відправити готову КЕП на сервер (приватний ключ лишився у браузері)
    await api(`/documents/${docId()}/sign`, "POST", {
      signer_order_index: next.order_index,
      signature_b64: cms,
      signer: next.full_name,
      signer_position: next.position,
    });
    toast(`Підписано: ${next.full_name}`);
    refresh();
  } catch (e) { toast("Помилка підпису: " + e.message); }
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
