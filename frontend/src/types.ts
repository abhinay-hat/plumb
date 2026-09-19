export type Route = "answer" | "clarify" | "refuse" | "chat" | "error";
export type ChartKind = "bar" | "line" | "pie" | "scatter" | "none";

export interface ColumnInfo {
  name: string;
  dtype: string;
  null_count: number;
  distinct_count: number;
  samples: string[];
}

export interface TableInfo {
  name: string;
  row_count: number;
  columns: ColumnInfo[];
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
  definitions_applied: Record<string, string>;
  elapsed_ms: number;
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
  guard_errors: string[];
  error_code: string | null;
  definitions_applied: Record<string, string>;
  narration_verified: boolean;
}

export interface UploadResult {
  session_id: string;
  tables: TableInfo[];
}

export interface SettleResult {
  definitions: Record<string, string>;
}

export class ApiRequestError extends Error {
  readonly code: string;
  constructor(code: string, message: string) {
    super(message);
    this.name = "ApiRequestError";
    this.code = code;
  }
}
