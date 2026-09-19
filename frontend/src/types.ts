export type Route = "answer" | "clarify" | "refuse" | "chat" | "error";
export type ChartKind = "bar" | "line" | "pie" | "scatter" | "none";

export interface ColumnInfo {
  name: string;
  dtype: string;
  null_count: number;
  distinct_count: number;
  samples: string[];
  values: string[];
  null_pct: number;
  case_variant_count: number | null;
  case_variant_examples: string[];
}

export interface TableInfo {
  name: string;
  row_count: number;
  columns: ColumnInfo[];
  sheet_name: string | null;
  display_name: string;
  grain_column: string | null;
  grain_entities: number | null;
  rows_per_entity: number | null;
  is_history_table: boolean;
  history_date_column: string | null;
}

export interface Plan {
  route: Route;
  sql: string | null;
  clarify_question: string | null;
  clarify_options: string[] | null;
  clarify_term: string | null;
  refuse_reason: string | null;
  reply: string | null;
  chart: ChartKind;
  chart_x: string | null;
  chart_y: string[] | null;
}

export interface ChartAdvice {
  kind: ChartKind;
  x: string | null;
  y: string | null;
  reason: string;
  alternatives: ChartKind[];
  unsupported: string | null;
  rendered: string | null;
}

export type Cell = string | number | boolean | null;

export interface AskResponse {
  route: Route;
  sql: string | null;
  columns: string[] | null;
  rows: Cell[][] | null;
  narration: string | null;
  chart: Record<string, unknown> | null;
  clarify_question: string | null;
  clarify_options: string[] | null;
  clarify_term: string | null;
  refuse_reason: string | null;
  reply: string | null;
  error_code: string | null;
  error_message: string | null;
  tables_sent: string[] | null;
  chart_advice: ChartAdvice | null;
  follow_ups: string[];
  definitions_applied: Record<string, string>;
  elapsed_ms: number;
  provider: string;
  model: string;
  endpoint_host: string | null;
}

export interface AuditEntry {
  ts: string;
  session_id: string;
  question: string;
  route: Route;
  sql: string | null;
  row_count: number;
  elapsed_ms: number;
  model: string;
  provider: string;
  host: string | null;
  guard_errors: string[];
  error_code: string | null;
  tables_sent: string[] | null;
  definitions_applied: Record<string, string>;
  narration_verified: boolean;
  chart_kind: string | null;
  chart_rendered: boolean;
}

export interface UploadResult {
  session_id: string;
  tables: TableInfo[];
  suggestions: string[];
}

export interface SuggestionsResult {
  suggestions: string[];
}

export interface SessionResult {
  session_id: string;
}

export interface SettleResult {
  definitions: Record<string, string>;
}

export interface ModelOption {
  id: string;
  label: string;
}

export interface ProviderOption {
  id: string;
  label: string;
  models: ModelOption[];
  kind?: string;
}

export interface ModelCatalog {
  provider: string;
  model: string;
  host: string | null;
  providers: ProviderOption[];
  presets: ProviderOption[];
}

export class ApiRequestError extends Error {
  readonly code: string;
  constructor(code: string, message: string) {
    super(message);
    this.name = "ApiRequestError";
    this.code = code;
  }
}
