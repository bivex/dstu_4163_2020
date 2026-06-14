// Декларації типів для зовнішніх EUSign API та доменних DTO порталу.
// Крипто-бібліотека постачається ІІТ (euscpfactory.js WASM + eusign.js helper);
// тут лише типи інтерфейсів, які реально використовує фронт.

// --- iframe sign-widget helper (eusign.js, глобальний EndUser) ---

export interface CertInfo {
  [key: string]: unknown;
}

export interface EndUserInstance {
  AddEventListener(eventType: number, listener: (ev: unknown) => void): void;
  ReadPrivateKey(): Promise<CertInfo[]>;
  SignData(
    data: string | Uint8Array,
    external: boolean,
    asBase64String: boolean,
    signAlgo?: number,
    previousSign?: string | Uint8Array | null,
    signType?: number,
  ): Promise<string>;
  ResetPrivateKey(): Promise<void>;
}

export interface EndUserConstructor {
  new (
    parentId: string,
    iframeId: string,
    uri: string,
    formType: number,
  ): EndUserInstance;
  FormType: { ReadPKey: number; MakeNewCertificate: number; SignFile: number;
    ViewPKeyCertificates: number; MakeDeviceCertificate: number };
  EventType: { ConfirmKSPOperation: number };
  SignAlgo: { DSTU4145WithGOST34311: number; RSAWithSHA: number };
  SignType: { CAdES_BES: number; CAdES_T: number; CAdES_X_Long: number };
}

// --- WASM-фабрика для файлового ключа (euscpfactory.js) ---

export interface CAServer { title: string; [k: string]: unknown }

export interface EUSignFactory {
  onChangeCAs: (() => void) | null;
  onerror: ((m: string) => void) | null;
  CAsServers?: CAServer[];
  pkFilePassword: string;
  pkFileItemIndex: number;
  pkReaded: boolean;
  isReady(): boolean;
  setPrivateKeyFile(f: File | null): void;
  setCASettings(idx: number): void;
  readPrivateKeyButtonClick(): void;
  signData(
    data: string | Uint8Array,
    isInternalSign: boolean,
    isAddCert: boolean,
    signAlg: string,
  ): string;
}

// --- бекенд DTO ---

export interface Signer {
  order_index: number;
  full_name: string;
  position: string;
  status: "waiting" | "invited" | "signed" | "rejected";
  certificate_serial?: string;
}

export interface Finding { clause: string; message: string }
export interface RuleResult {
  rule_id: string; clause: string; conforms: boolean; findings: Finding[];
}
export interface ConformanceReport {
  conforms: boolean; findings_count: number; results: RuleResult[];
}
export interface DocumentDTO {
  doc_id: string;
  status: string;
  signers: Signer[];
  conformance?: ConformanceReport | null;
  has_asice?: boolean;
}

declare global {
  // eslint-disable-next-line no-var
  var EndUser: EndUserConstructor;
}

