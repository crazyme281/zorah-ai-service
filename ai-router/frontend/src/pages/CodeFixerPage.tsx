import { useCallback, useEffect, useRef, useState } from "react";
import { IonPage, IonContent, IonIcon, IonSpinner } from "@ionic/react";
import {
  codeSlashOutline,
  cloudUploadOutline,
  documentOutline,
  checkmarkCircleOutline,
  closeCircleOutline,
  alertCircleOutline,
  downloadOutline,
} from "ionicons/icons";
import { TopBar } from "../components/TopBar";
import {
  uploadProject,
  getJob,
  getDownloadUrl,
  STAGE_LABELS,
  type CodeFixerJob,
} from "../lib/codeFixer";

const POLL_MS = 2000;
const TERMINAL: CodeFixerJob["status"][] = ["complete", "failed"];

function formatSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function CodeFixerPage() {
  const [file, setFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [job, setJob] = useState<CodeFixerJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  function pickFile(f: File | undefined) {
    if (!f) return;
    if (!f.name.toLowerCase().endsWith(".zip")) {
      setError("Only .zip files are accepted.");
      return;
    }
    setError(null);
    setFile(f);
    setJob(null);
  }

  const startPolling = useCallback((jobId: string) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const updated = await getJob(jobId);
        setJob(updated);
        if (TERMINAL.includes(updated.status) && pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
      } catch {
        // Transient network hiccup — the next tick tries again rather
        // than giving up on the whole job over one failed poll.
      }
    }, POLL_MS);
  }, []);

  async function handleStart() {
    if (!file || uploading) return;
    setUploading(true);
    setError(null);
    try {
      const created = await uploadProject(file);
      setJob(created);
      startPolling(created.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't start the fix.");
    } finally {
      setUploading(false);
    }
  }

  async function handleDownload() {
    if (!job) return;
    setDownloading(true);
    setError(null);
    try {
      const url = await getDownloadUrl(job.id);
      window.open(url, "_blank");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't get the download link.");
    } finally {
      setDownloading(false);
    }
  }

  function reset() {
    setFile(null);
    setJob(null);
    setError(null);
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  const running = job !== null && !TERMINAL.includes(job.status);
  const showReport = job !== null && job.status === "complete";
  const showFailure = job !== null && job.status === "failed";

  return (
    <IonPage>
      <TopBar />
      <IonContent className="panel-page">
        <div className="codefix">
          {!job && (
            <>
              <div className="codefix__intro">
                <IonIcon icon={codeSlashOutline} />
                <h2>Code Fixer</h2>
                <p>Upload a project as a .zip — Zorah will inspect it, fix what it can, and validate the result.</p>
              </div>

              <div
                className={`codefix__drop ${dragOver ? "codefix__drop--active" : ""}`}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragOver(true);
                }}
                onDragLeave={() => setDragOver(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setDragOver(false);
                  pickFile(e.dataTransfer.files?.[0]);
                }}
                onClick={() => fileRef.current?.click()}
              >
                <IonIcon icon={cloudUploadOutline} />
                {file ? (
                  <>
                    <p className="codefix__filename">
                      <IonIcon icon={documentOutline} /> {file.name}
                    </p>
                    <small>{formatSize(file.size)} — tap to choose a different file</small>
                  </>
                ) : (
                  <>
                    <p>Drag a .zip here, or tap to browse</p>
                    <small>Project archives only</small>
                  </>
                )}
              </div>

              {error && <p className="codefix__error">{error}</p>}

              <button
                type="button"
                className="codefix__start"
                disabled={!file || uploading}
                onClick={handleStart}
              >
                {uploading ? <IonSpinner name="crescent" /> : "Fix My Code"}
              </button>
            </>
          )}

          {running && (
            <div className="codefix__progress">
              <IonSpinner name="crescent" />
              <h3>{STAGE_LABELS[job.status]}</h3>
              {job.project_type && <p>Detected: {job.project_type}</p>}
              {job.attempts > 1 && <p>Repair attempt {job.attempts}</p>}
            </div>
          )}

          {showFailure && (
            <div className="codefix__report">
              <div className="codefix__final codefix__final--failed">
                <IonIcon icon={closeCircleOutline} />
                Couldn&rsquo;t fix this project
              </div>
              <p className="codefix__error">{job!.error}</p>
              <button type="button" className="codefix__start" onClick={reset}>
                Try again
              </button>
            </div>
          )}

          {showReport && (
            <div className="codefix__report">
              <div
                className={`codefix__final ${
                  job!.final_status === "success" ? "codefix__final--success" : "codefix__final--partial"
                }`}
              >
                <IonIcon icon={job!.final_status === "success" ? checkmarkCircleOutline : alertCircleOutline} />
                {job!.final_status === "success"
                  ? "Project successfully fixed and validated"
                  : "Project partially fixed — some issues remain"}
              </div>

              <section>
                <h4>Problems Found</h4>
                {job!.problems_found.length === 0 ? (
                  <p className="codefix__muted">None</p>
                ) : (
                  <ul>
                    {job!.problems_found.map((p, i) => (
                      <li key={i}>{p}</li>
                    ))}
                  </ul>
                )}
              </section>

              <section>
                <h4>Files Changed</h4>
                {job!.files_changed.length === 0 ? (
                  <p className="codefix__muted">None</p>
                ) : (
                  <ul className="codefix__files">
                    {job!.files_changed.map((f, i) => (
                      <li key={i}>
                        <code>{f.path}</code>
                        <span>{f.reason}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              {!!job!.dependencies_changed?.added?.length && (
                <section>
                  <h4>Dependencies</h4>
                  <p>Added: {job!.dependencies_changed.added.join(", ")}</p>
                </section>
              )}

              {Object.keys(job!.validation).length > 0 && (
                <section>
                  <h4>Validation</h4>
                  <ul className="codefix__validation">
                    {Object.entries(job!.validation).map(([label, v]) => (
                      <li key={label} className={v.passed ? "pass" : "fail"}>
                        <IonIcon icon={v.passed ? checkmarkCircleOutline : closeCircleOutline} />
                        {label.replace("_", " ")}: {v.passed ? "Passed" : v.timed_out ? "Timed out" : "Failed"}
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              <section>
                <h4>Unresolved Issues</h4>
                {job!.unresolved_issues.length === 0 ? (
                  <p className="codefix__muted">None</p>
                ) : (
                  <ul>
                    {job!.unresolved_issues.map((u, i) => (
                      <li key={i}>{u}</li>
                    ))}
                  </ul>
                )}
              </section>

              {error && <p className="codefix__error">{error}</p>}

              <div className="codefix__actions">
                <button type="button" className="codefix__start" onClick={handleDownload} disabled={downloading}>
                  <IonIcon icon={downloadOutline} />
                  {downloading ? "Preparing…" : "Download Fixed Project ZIP"}
                </button>
                <button type="button" className="codefix__ghost" onClick={reset}>
                  Fix another project
                </button>
              </div>
            </div>
          )}
        </div>

        <input
          ref={fileRef}
          type="file"
          accept=".zip"
          hidden
          onChange={(e) => {
            pickFile(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
      </IonContent>
    </IonPage>
  );
}