// Портал підписання — фронтенд-логіка (TypeScript).
// Інтеграція з FastAPI бекендом (той самий origin) + клієнтський підпис КЕП:
//  • файловий ключ — WASM-збірка EUSign (euscpfactory.js, під /eusign/);
//  • апаратний токен — офіційний iframe-віджет ІІТ (eusign.js helper, EndUser).
// Приватний ключ не покидає браузер — на сервер іде лише готовий CMS.

import type {
  EUSignFactory,
  EndUserInstance,
  DocumentDTO,
  ConformanceReport,
  Signer,
} from "../types/eusign";

const API = ""; // той самий origin, що й статика
const WIDGET_URI = "https://eu.iit.com.ua/sign-widget/v20200922/";

let euSignFactory: EUSignFactory | null = null;
let euReady = false;
let euWidget: EndUserInstance | null = null;
let widgetInited = false;

// --- типобезпечні DOM-хелпери ---
function el<T extends HTMLElement = HTMLElement>(id: string): T {
  const e = document.getElementById(id);
  if (!e) throw new Error(`element #${id} not found`);
  return e as T;
}
function val(id: string): string {
  return (el<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>(id)).value;
}

async function initEUSign(): Promise<void> {
  const st = el("euStatus");
  try {
    const mod = await import(
      // @ts-expect-error — абсолютний URL статики /eusign/, TS не резолвить рантайм-шлях
      "/eusign/modules/euscpfactory.js"
    );
    const factory = (mod as { euSignFactory: EUSignFactory }).euSignFactory;
    euSignFactory = factory;
    factory.onChangeCAs = renderCAs;
    factory.onerror = (m: string) => toast("EUSign: " + m);
    const wait = setInterval(() => {
      if (euSignFactory && euSignFactory.isReady && euSignFactory.isReady()) {
        clearInterval(wait);
        euReady = true;
        renderCAs();
        st.textContent = "EUSign готовий. Оберіть спосіб ключа.";
        (el<HTMLButtonElement>("signBtn")).disabled = false;
      }
    }, 400);
    (el<HTMLInputElement>("keyFile")).onchange = (e: Event) => {
      const f = (e.target as HTMLInputElement).files;
      euSignFactory!.setPrivateKeyFile(f && f.length ? f[0] : null);
    };
    (el<HTMLSelectElement>("keySource")).onchange = onKeySourceChange;
  } catch (err) {
    st.textContent = "Не вдалося завантажити EUSign: " + err +
      " — підпис недоступний, решта порталу працює.";
  }
}

// Перемикання файл/токен. Токен-режим піднімає офіційний iframe-віджет ІІТ.
function onKeySourceChange(): void {
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

// Підняти iframe-віджет ІІТ через офіційний helper EndUser (eusign.js).
function initWidget(): void {
  if (widgetInited) return;
  const hint = el("tokenHint");
  if (typeof EndUser === "undefined") {
    hint.innerHTML = '<span style="color:var(--bad)">Не завантажено eusign.js ' +
      '(helper віджета ІІТ).</span>';
    return;
  }
  try {
    euWidget = new EndUser(
      "sign-widget-parent",
      "sign-widget",
      WIDGET_URI,
      // ReadPKey — форма ЛИШЕ зчитування ос. ключа; самі дані (манІфест)
      // підписуємо програмно через SignData().
      EndUser.FormType.ReadPKey,
    );
    euWidget.AddEventListener(EndUser.EventType.ConfirmKSPOperation, () => {});
    widgetInited = true;
    hint.innerHTML = "Віджет ІІТ завантажено. Оберіть носій усередині віджета, " +
      "зчитайте ключ, далі натисніть «Підписати поточним у черзі».";
  } catch (e) {
    hint.innerHTML = '<span style="color:var(--bad)">Помилка ініціалізації віджета: ' +
      e + ". Перевірте, що домен дозволено у віджеті ІІТ.</span>";
  }
}

function renderCAs(): void {
  if (!euSignFactory || !euSignFactory.CAsServers) return;
  const sel = el<HTMLSelectElement>("caSelect");
  sel.innerHTML = "";
  euSignFactory.CAsServers.forEach((s) => {
    const o = document.createElement("option");
    o.text = s.title;
    sel.add(o);
  });
}

// --- API helpers ---
async function api<T = unknown>(
  path: string, method = "GET", body: unknown = null,
): Promise<T> {
  const opt: RequestInit = { method, headers: { "Content-Type": "application/json" } };
  if (body) opt.body = JSON.stringify(body);
  const r = await fetch(API + path, opt);
  const txt = await r.text();
  const data = txt ? JSON.parse(txt) : {};
  if (!r.ok) throw new Error(data.detail || String(r.status));
  return data as T;
}

function docId(): string { return val("docId").trim(); }

interface EditorSigner { order_index: number; full_name: string; position: string }

function readEditor(): Record<string, unknown> {
  const signers: EditorSigner[] = val("signers")
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
    org_name: val("orgName"),
    doc_type: val("docType"),
    title: val("title"),
    reg_index: val("regIndex"),
    date_text: val("dateText"),
    fmt: val("fmt"),
    is_electronic: true,
    body: val("body").split("\n").map((s) => s.trim()).filter(Boolean),
    signature_position: signers[0]?.position || "",
    signature_name: signers[0]?.full_name || "",
    e_signatures: eSig,
    signers,
    retention_years: 5,
  };
}

// --- дії (експонуються на window для inline onclick) ---
async function createDoc(): Promise<void> {
  try { await api("/documents", "POST", readEditor()); toast("Чернетку створено"); refresh(); }
  catch (e) { toast("Помилка: " + errMsg(e)); }
}

async function generateDoc(): Promise<void> {
  try {
    const r = await api<{ report: ConformanceReport }>(
      `/documents/${docId()}/generate`, "POST");
    renderReport(r.report); toast("Згенеровано та перевірено"); refresh();
  } catch (e) { toast("Помилка: " + errMsg(e)); }
}

function downloadDoc(): void {
  window.open(`${API}/documents/${docId()}/download`, "_blank");
}

async function deleteDoc(): Promise<void> {
  if (!confirm(`Видалити документ ${docId()} разом із підписами та аудитом?`)) return;
  try {
    await api(`/documents/${docId()}`, "DELETE");
    toast("Документ видалено — можна створити заново");
    el("signerList").innerHTML = '<span class="muted">Створіть документ.</span>';
    el("docStatus").textContent = "";
    renderReport(null);
    (el<HTMLButtonElement>("asiceBtn")).disabled = true;
  } catch (e) { toast("Помилка: " + errMsg(e)); }
}

async function submitDoc(): Promise<void> {
  try { await api(`/documents/${docId()}/submit`, "POST"); toast("Подано у чергу"); refresh(); }
  catch (e) { toast("Помилка: " + errMsg(e)); }
}

async function refresh(): Promise<void> {
  try {
    const d = await api<DocumentDTO>(`/documents/${docId()}`);
    renderSigners(d); renderReport(d.conformance ?? null);
    el("docStatus").textContent = "статус: " + d.status;
    (el<HTMLButtonElement>("asiceBtn")).disabled = !d.has_asice;
  } catch (e) {
    el("signerList").innerHTML = `<span class="muted">${errMsg(e)}</span>`;
  }
}

function downloadAsice(): void {
  window.open(`${API}/documents/${docId()}/download/asice`, "_blank");
}

function renderSigners(d: DocumentDTO): void {
  const box = el("signerList");
  if (!d.signers.length) {
    box.innerHTML = '<span class="muted">Немає підписантів.</span>'; return;
  }
  box.innerHTML = d.signers.map((s: Signer) => `
    <div class="signer">
      <div><b>#${s.order_index} ${s.full_name}</b>
        <div class="status-line">${s.position || ""}${
          s.certificate_serial && s.certificate_serial !== "—"
            ? " · серт. " + s.certificate_serial : ""}</div></div>
      <span class="badge b-${s.status}">${s.status}</span>
    </div>`).join("");
}

function renderReport(rep: ConformanceReport | null): void {
  const sum = el("reportSummary");
  const box = el("report");
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
async function signCurrent(): Promise<void> {
  if (!euReady) { toast("EUSign ще не готовий"); return; }
  let doc: DocumentDTO;
  try { doc = await api<DocumentDTO>(`/documents/${docId()}`); }
  catch (e) { toast("Спершу створіть і подайте документ: " + errMsg(e)); return; }

  const next = doc.signers.find((s) => s.status === "invited");
  if (!next) { toast("Немає активного підписанта (подайте у чергу)"); return; }

  try {
    const mode = val("keySource");

    // отримати з сервера точні байти ASiCManifest поточного підписанта і
    // підписати саме їх DETACHED-CAdES — так підпис покриває digest документа
    // за ETSI EN 319 162-1 (інакше «помилка 33»).
    const mr = await fetch(`${API}/documents/${docId()}/manifest`);
    if (!mr.ok) { toast("Не вдалося отримати манІфест: " + (await mr.text())); return; }
    const manifest = await mr.text();

    let cmsB64: string;

    if (mode === "token") {
      // --- апаратний токен через офіційний iframe-віджет ІІТ ---
      if (!euWidget) { toast("Віджет ІІТ не ініціалізовано"); return; }
      await euWidget.ReadPrivateKey();
      cmsB64 = await euWidget.SignData(
        manifest, true, true,
        EndUser.SignAlgo.DSTU4145WithGOST34311,
        null,
        EndUser.SignType.CAdES_X_Long,
      );
    } else {
      // --- файловий ключ через WASM-збірку EUSign ---
      if (!euSignFactory) { toast("EUSign не готовий"); return; }
      const password = val("keyPass");
      const caIdx = (el<HTMLSelectElement>("caSelect")).selectedIndex;
      euSignFactory.setCASettings(caIdx < 0 ? -1 : caIdx);
      euSignFactory.pkFilePassword = password;
      euSignFactory.pkFileItemIndex = -1;
      euSignFactory.readPrivateKeyButtonClick();
      if (!euSignFactory.pkReaded) { toast("Не вдалося прочитати ключ (пароль/файл)"); return; }
      // ВАЖЛИВО: фабрика ініціалізована з SetCharset("UTF-16LE"); рядок дав би
      // підпис над UTF-16LE, а сервер пакує манІфест як UTF-8 → «помилка 35».
      // Передаємо UTF-8 Uint8Array — підпис покриває саме байти контейнера.
      const manifestBytes = new TextEncoder().encode(manifest);
      cmsB64 = euSignFactory.signData(manifestBytes, false, true, "def");
    }

    if (!cmsB64) { toast("Підпис не сформовано"); return; }

    // відправити готову detached-КЕП на сервер (приватний ключ лишився у браузері)
    await api(`/documents/${docId()}/sign`, "POST", {
      signer_order_index: next.order_index,
      signature_b64: cmsB64,
      signer: next.full_name,
      signer_position: next.position,
    });
    toast(`Підписано: ${next.full_name}`);
    refresh();
  } catch (e) { toast("Помилка підпису: " + errMsg(e)); }
}

// --- toast ---
let toastT: ReturnType<typeof setTimeout> | undefined;
function toast(msg: string): void {
  const t = el("toast");
  t.textContent = msg; t.classList.add("show");
  clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove("show"), 3500);
}

function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

// --- експонувати дії для inline onclick у index.html ---
Object.assign(window as unknown as Record<string, unknown>, {
  createDoc, generateDoc, downloadDoc, deleteDoc, submitDoc,
  refresh, downloadAsice, signCurrent,
});

// init
initEUSign();
