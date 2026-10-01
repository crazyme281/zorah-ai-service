import { useEffect, useRef, useState } from "react";
import { IonIcon, IonSpinner } from "@ionic/react";
import { playOutline, refreshOutline, bulbOutline, checkmarkCircle, closeCircle, ellipseOutline } from "ionicons/icons";
import { runCode, executableTests, warmUpPython, type RunResult, type RunLanguage } from "../../lib/sandbox";
import { copyText } from "./CodeBlock";
import type { TaskContent } from "../../lib/training";

type Tab = "output" | "errors" | "tests";

const KEYS = ["⇥", "{", "}", "(", ")", "[", "]", '"', "'", ";", ":", "=", "<", ">", "+", "-", "*", "/", "_", "#"];

/**
 * Code editor + output / errors / tests console.
 *  - Runnable languages (JavaScript, Python) execute in the sandbox.
 *  - Anything else is write-and-review only (no Run button).
 */
export function CodeConsole({
  task,
  code,
  onCode,
  disabled,
  onResult,
  result,
}: {
  task: TaskContent;
  code: string;
  onCode: (v: string) => void;
  disabled?: boolean;
  onResult: (r: RunResult) => void;
  result: RunResult | null;
}) {
  const runnable = task.execution !== "none";
  const [tab, setTab] = useState<Tab>("output");
  const [running, setRunning] = useState(false);
  const [status, setStatus] = useState("");
  const [copied, setCopied] = useState(false);
  const ta = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (task.execution === "python") warmUpPython();
  }, [task.execution]);

  function insert(text: string) {
    const el = ta.current;
    if (!el) return onCode(code + text);
    const { selectionStart: s, selectionEnd: e } = el;
    const next = code.slice(0, s) + text + code.slice(e);
    onCode(next);
    requestAnimationFrame(() => {
      el.focus();
      el.selectionStart = el.selectionEnd = s + text.length;
    });
  }

  async function run() {
    if (!runnable || running) return;
    setRunning(true);
    setStatus("Running…");
    const r = await runCode(task.execution as RunLanguage, code, task.tests, setStatus);
    setRunning(false);
    setStatus("");
    onResult(r);
    setTab(r.error ? "errors" : executableTests(task.tests).length ? "tests" : "output");
  }

  const tests = result?.tests ?? [];
  const passed = tests.filter((t) => t.passed).length;
  const behavior = task.tests.filter((t) => t.type === "behavior");

  return (
    <div className="tr-console">
      <div className="tr-editor">
        <div className="tr-editor__bar">
          <span>{task.language ?? "Code"}</span>
          <button
            type="button"
            onClick={async () => {
              if (await copyText(code)) {
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              }
            }}
          >
            {copied ? "Copied" : "Copy code"}
          </button>
        </div>
        <textarea
          ref={ta}
          className="tr-editor__area"
          value={code}
          disabled={disabled}
          spellCheck={false}
          autoCapitalize="off"
          autoCorrect="off"
          autoComplete="off"
          wrap="off"
          rows={Math.min(18, Math.max(8, code.split("\n").length + 1))}
          onChange={(e) => onCode(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Tab") {
              e.preventDefault();
              insert("  ");
            }
          }}
          aria-label="Code editor"
        />
        <div className="tr-keys" role="toolbar" aria-label="Symbols">
          {KEYS.map((k) => (
            <button key={k} type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => insert(k === "⇥" ? "  " : k)} disabled={disabled}>
              {k}
            </button>
          ))}
        </div>
      </div>

      <div className="tr-actions">
        {runnable ? (
          <button type="button" className="tr-btn tr-btn--gold" onClick={run} disabled={running || disabled}>
            {running ? <IonSpinner name="dots" /> : <IonIcon icon={playOutline} />}
            {running ? status || "Running…" : "Run & test"}
          </button>
        ) : (
          <p className="tr-note">
            {task.language ?? "This language"} can't run inside the app yet — write your solution, then submit it for tutor review.
          </p>
        )}
        <button type="button" className="tr-btn" onClick={() => onCode(task.starter_code)} disabled={disabled || running}>
          <IonIcon icon={refreshOutline} /> Reset
        </button>
      </div>

      {runnable && (
        <div className="tr-panel">
          <div className="tr-tabs" role="tablist">
            {(["output", "errors", "tests"] as Tab[]).map((t) => (
              <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "is-on" : ""} onClick={() => setTab(t)}>
                {t === "output" ? "Output" : t === "errors" ? "Errors" : "Tests"}
                {t === "errors" && result?.error ? <i className="tr-dot tr-dot--bad" /> : null}
                {t === "tests" && tests.length ? <em>{passed}/{tests.length}</em> : null}
              </button>
            ))}
          </div>
          <div className="tr-panel__body">
            {!result && <p className="tr-muted">Run your code to see its output, errors and test results here.</p>}
            {result && tab === "output" && (
              <pre className="tr-pre">{result.stdout || "(no output)"}</pre>
            )}
            {result && tab === "errors" && (
              <pre className="tr-pre tr-pre--bad">{result.error ?? "No errors 🎉"}</pre>
            )}
            {result && tab === "tests" && (
              <ul className="tr-tests">
                {tests.map((t, i) => (
                  <li key={i} className={t.passed ? "ok" : "bad"}>
                    <IonIcon icon={t.passed ? checkmarkCircle : closeCircle} />
                    <div>
                      <strong>{t.name}</strong>
                      {!t.passed && t.message ? <small>{t.message}</small> : null}
                    </div>
                  </li>
                ))}
                {behavior.map((t, i) => (
                  <li key={`b${i}`} className="pending">
                    <IonIcon icon={ellipseOutline} />
                    <div>
                      <strong>{t.name}</strong>
                      <small>Checked by your tutor when you submit</small>
                    </div>
                  </li>
                ))}
                {!tests.length && !behavior.length && <li className="pending"><div><small>This task has no automatic tests — submit it for tutor review.</small></div></li>}
              </ul>
            )}
          </div>
        </div>
      )}
      {!runnable && task.hints.length > 0 && (
        <p className="tr-note">
          <IonIcon icon={bulbOutline} /> Stuck? Use the hints below the task.
        </p>
      )}
    </div>
  );
}
