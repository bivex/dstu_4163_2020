// Портал підписання — фронтенд-логіка.
// Інтеграція з FastAPI бекендом (той самий origin) + клієнтський підпис КЕП
// через EUSign (euscpfactory.js із submodule external/EUSignES6, подається
// під /eusign/). Приватний ключ не покидає браузер — на сервер іде лише CMS.

const API = "";  // той самий origin, що й статика

// --- EUSign: динамічний імпорт фабрики ---
let euSignFactory = null;
let euSignClass = null;      // клас EUSignCP (для feature-detection методів носія)
let euReady = false;
let tokenSupported = false;  // чи вміє завантажена бібліотека читати апаратні носії

async function initEUSign() {
  const st = document.getElementById("euStatus");
  try {
    const mod = await import("/eusign/modules/euscpfactory.js");
    euSignFactory = mod.euSignFactory;
    // Інстанс euSign приватний у фабриці; для feature-detection токенів
    // перевіряємо прототип класу EUSignCP (експортується з euscpm.js) на
    // наявність методів роботи з носіями.
    try {
      const m = await import("/eusign/modules/euscpm.js");
      euSignClass = m.EUSignCP || null;
    } catch (_) { euSignClass = null; }
    euSignFactory.onChangeCAs = renderCAs;
    euSignFactory.onerror = (m) => toast("EUSign: " + m);
    // дочекатися завантаження переліку КНЕДП
    const wait = setInterval(() => {
      if (euSignFactory.isReady && euSignFactory.isReady()) {
        clearInterval(wait);
        euReady = true;
        renderCAs();
        detectTokenSupport();
        st.textContent = "EUSign готовий. Оберіть спосіб ключа, КНЕДП і пароль.";
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

// Feature-detection: чи має завантажений EUSign методи роботи з носіями.
// WASM-збірка у репо їх НЕ має (лише файловий ключ) — тоді режим токена
// чесно позначаємо недоступним і пояснюємо, що потрібне «ІІТ Користувач ЦСК».
function detectTokenSupport() {
  // токен-здатна збірка експонує на прототипі EUSignCP методи роботи з носіями
  // (перелік пристроїв + читання ключа з носія, не лише *Binary з файлу).
  const proto = euSignClass && euSignClass.prototype;
  tokenSupported = !!(proto && (
    typeof proto.EnumKeyMediaDevices === "function" ||
    typeof proto.GetKeyMediaDevices === "function" ||
    typeof proto.ReadPrivateKey === "function"  // не Binary — саме читання з носія
  ));
}

function onKeySourceChange() {
  const mode = document.getElementById("keySource").value;
  const tokenWrap = document.getElementById("tokenWrap");
  const fileWrap = document.getElementById("fileWrap");
  if (mode === "token") {
    fileWrap.style.display = "none";
    tokenWrap.style.display = "";
    const hint = document.getElementById("tokenHint");
    if (!tokenSupported) {
      hint.innerHTML = '<span style="color:var(--bad)">Апаратні токени недоступні у цій ' +
        'збірці бібліотеки. Встановіть «ІІТ Користувач ЦСК» (euscpnmh) — тоді портал ' +
        'бачитиме підключені носії. Поки що скористайтеся файловим ключем.</span>';
      document.getElementById("tokenSelect").innerHTML = "";
    } else {
      enumerateTokens();
    }
  } else {
    tokenWrap.style.display = "none";
    fileWrap.style.display = "";
  }
}

function enumerateTokens() {
  const sel = document.getElementById("tokenSelect");
  const hint = document.getElementById("tokenHint");
  sel.innerHTML = "";
  // інстанс EUSignCP, що вміє носії, надає токен-здатна збірка (через native
  // host «ІІТ Користувач ЦСК»). Беремо його з фабрики, якщо доступний.
  const eu = euSignFactory && (euSignFactory.euSign || euSignFactory.getEUSign &&
             euSignFactory.getEUSign());
  if (!eu) {
    hint.textContent = "Носії недоступні: токен-здатний модуль EUSign не активний.";
    return;
  }
  try {
    const list = (eu.EnumKeyMediaDevices && eu.EnumKeyMediaDevices()) ||
                 (eu.GetKeyMediaDevices && eu.GetKeyMediaDevices()) || [];
    if (!list.length) {
      hint.textContent = "Підключених носіїв не знайдено. Вставте токен і оновіть сторінку.";
      return;
    }
    list.forEach((dev, i) => {
      const o = document.createElement("option");
      o.value = i;
      o.text = typeof dev === "string" ? dev : (dev.name || `Носій #${i}`);
      sel.add(o);
    });
    hint.textContent = `Знайдено носіїв: ${list.length}.`;
  } catch (e) {
    hint.textContent = "Помилка переліку носіїв: " + e;
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
    const password = document.getElementById("keyPass").value;

    // 1) прочитати ключ — з файлу або з апаратного носія
    if (mode === "token") {
      if (!tokenSupported) {
        toast("Апаратні токени недоступні: встановіть «ІІТ Користувач ЦСК»");
        return;
      }
      const eu = euSignFactory && (euSignFactory.euSign || euSignFactory.getEUSign &&
                 euSignFactory.getEUSign());
      if (!eu) { toast("Токен-здатний модуль EUSign не активний"); return; }
      const devIdx = parseInt(document.getElementById("tokenSelect").value, 10);
      if (isNaN(devIdx)) { toast("Оберіть носій (токен)"); return; }
      // читання приватного ключа з носія: typeIndex авто (-1), devIndex обраний
      eu.ReadPrivateKey(eu.MakeKeyMedia
        ? eu.MakeKeyMedia(-1, devIdx, password)
        : { typeIndex: -1, devIndex, password });
      if (!eu.IsPrivateKeyReaded()) {
        toast("Не вдалося прочитати ключ з токена (пароль/носій)"); return;
      }
    } else {
      const caIdx = document.getElementById("caSelect").selectedIndex;
      euSignFactory.setCASettings(caIdx < 0 ? -1 : caIdx);
      euSignFactory.pkFilePassword = password;
      euSignFactory.pkFileItemIndex = -1;
      euSignFactory.readPrivateKeyButtonClick();
      if (!euSignFactory.pkReaded) { toast("Не вдалося прочитати ключ (пароль/файл)"); return; }
    }

    // 2) отримати з сервера точні байти ASiCManifest поточного підписанта
    //    і підписати саме їх DETACHED-CAdES (isInternalSign=false) — так підпис
    //    покриває digest документа за ETSI EN 319 162-1 (інакше «помилка 33»).
    const mr = await fetch(`${API}/documents/${docId()}/manifest`);
    if (!mr.ok) { toast("Не вдалося отримати манІфест: " + (await mr.text())); return; }
    const manifest = await mr.text();
    const cms = euSignFactory.signData(manifest, false, true, "def");
    if (!cms) { toast("Підпис не сформовано"); return; }

    // 3) відправити готову detached-КЕП на сервер (приватний ключ лишився у браузері)
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
