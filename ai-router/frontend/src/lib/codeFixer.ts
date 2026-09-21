/**
 * Calls for the Code Fixer pipeline (see backend/access/codefix_pipeline.py).
 * Every call needs the caller's own bearer token — job ownership is
 * enforced server-side, not by anything client-side.
 */
import { supabase } from "./supabase";

const BASE = import.meta.env.VITE_AI_BACKEND_URL;

export type CodeFixerStatus =
  | "queued" | "extracting" | "inspecting" | "analyzing"
  | "applying_fixes" | "validating" | "packaging" | "complete" | "failed";

export interface FileChange {
  path: string;
  reason: string;
  action: "modified" | "created";
}

export interface ValidationEntry {
  command: string;
  passed: boolean;
  exit_code: number | null;
  timed_out: boolean;
  output: string;
}

export interface CodeFixerJob {
  id: string;
  status: CodeFixerStatus;
  project_type: string | null;
  original_file_name: string;
  attempts: number;
  problems_found: string[];
  files_changed: FileChange[];
  dependencies_changed: { added?: string[]; note?: string | null };
  validation: Record<string, ValidationEntry>;
  unresolved_issues: string[];
  final_status: "success" | "partial" | "failed" | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

async function authHeader(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function uploadProject(file: File): Promise<CodeFixerJob> {
  const form = new FormData();
  form.append("file", file);
  const resp = await fetch(`${BASE}/code-fixer/jobs`, {
    method: "POST",
    headers: await authHeader(),
    body: form,
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => null);
    throw new Error(body?.detail || "Upload failed.");
  }
  return resp.json();
}

export async function getJob(jobId: string): Promise<CodeFixerJob> {
  const resp = await fetch(`${BASE}/code-fixer/jobs/${jobId}`, { headers: await authHeader() });
  if (!resp.ok) throw new Error("Couldn't check job status.");
  return resp.json();
}

export async function listJobs(): Promise<CodeFixerJob[]> {
  const resp = await fetch(`${BASE}/code-fixer/jobs`, { headers: await authHeader() });
  if (!resp.ok) return [];
  return resp.json();
}

export async function getDownloadUrl(jobId: string): Promise<string> {
  const resp = await fetch(`${BASE}/code-fixer/jobs/${jobId}/download`, { headers: await authHeader() });
  if (!resp.ok) throw new Error("The fixed project isn't ready to download yet.");
  const data = await resp.json();
  return data.url;
}

export const STAGE_LABELS: Record<CodeFixerStatus, string> = {
  queued: "Uploading project…",
  extracting: "Extracting project…",
  inspecting: "Detecting project type…",
  analyzing: "Analyzing code…",
  applying_fixes: "Applying fixes…",
  validating: "Running validation…",
  packaging: "Creating corrected ZIP…",
  complete: "Complete",
  failed: "Failed",
};