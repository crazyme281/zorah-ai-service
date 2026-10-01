/**
 * The in-app "secure console" for coding tasks.
 *
 * Learner code never touches the app's own page. It runs in a Web Worker
 * created from a Blob (see ./sandbox/*.js): no DOM, no access to the app's
 * storage or auth session, network APIs stripped out, and the worker is
 * terminate()d on a timeout — which is what stops infinite loops.
 *
 *   JavaScript -> runs directly in the worker.
 *   Python     -> Pyodide (CPython on WebAssembly), downloaded once from
 *                 jsDelivr on first use and cached after that.
 *
 * Other languages can't be executed here; the tutor reviews them instead
 * (see TaskView). Tests of type "behavior" are likewise reviewed by the
 * tutor, never executed.
 */
import jsWorkerSrc from "./sandbox/jsWorker.js?raw";
import pyWorkerSrc from "./sandbox/pyWorker.js?raw";
import harnessSrc from "./sandbox/harness.py?raw";

export type RunLanguage = "javascript" | "python";

export interface SandboxTest {
  name: string;
  type: "call" | "stdout" | "behavior";
  expr?: string;
  expected: string;
}
export interface TestResult {
  name: string;
  passed: boolean;
  message: string;
}
export interface RunResult {
  stdout: string;
  error: string | null;
  tests: TestResult[];
  timedOut: boolean;
}

const JS_TIMEOUT_MS = 5000;
const PY_TIMEOUT_MS = 10000;
const PY_LOAD_TIMEOUT_MS = 90000;

function blobUrl(src: string) {
  return URL.createObjectURL(new Blob([src], { type: "text/javascript" }));
}
const token = () => Math.random().toString(36).slice(2);
const failed = (error: string, timedOut = false): RunResult => ({ stdout: "", error, tests: [], timedOut });

/** Only these can be executed; "behavior" tests are judged by the tutor. */
export function executableTests(tests: SandboxTest[]) {
  return tests.filter((t) => t.type === "call" || t.type === "stdout");
}

function runJs(code: string, tests: SandboxTest[]): Promise<RunResult> {
  return new Promise((resolve) => {
    const url = blobUrl(jsWorkerSrc);
    const worker = new Worker(url);
    const id = token();
    let done = false;
    const finish = (r: RunResult) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      worker.terminate();
      URL.revokeObjectURL(url);
      resolve(r);
    };
    const timer = setTimeout(
      () => finish(failed(`Timed out after ${JS_TIMEOUT_MS / 1000}s — check for an infinite loop.`, true)),
      JS_TIMEOUT_MS,
    );
    worker.onmessage = (e) => {
      if (e.data?.token !== id) return;
      finish({ stdout: e.data.stdout ?? "", error: e.data.error ?? null, tests: e.data.tests ?? [], timedOut: false });
    };
    worker.onerror = (e) => finish(failed(e.message || "The code crashed."));
    worker.postMessage({ token: id, code, tests });
  });
}

// ---- Python -------------------------------------------------------------
interface PyHandle {
  worker: Worker;
  url: string;
  ready: Promise<void>;
}
let py: PyHandle | null = null;

function resetPy() {
  if (!py) return;
  py.worker.terminate();
  URL.revokeObjectURL(py.url);
  py = null;
}

function startPy(): PyHandle {
  const src = pyWorkerSrc.replace("__PY_HARNESS__", () => JSON.stringify(harnessSrc));
  const url = blobUrl(src);
  const worker = new Worker(url);
  const ready = new Promise<void>((resolve, reject) => {
    const timer = setTimeout(
      () => reject(new Error("Python took too long to load. Check your connection and try again.")),
      PY_LOAD_TIMEOUT_MS,
    );
    const onMsg = (e: MessageEvent) => {
      if (e.data?.type === "ready") {
        clearTimeout(timer);
        worker.removeEventListener("message", onMsg);
        resolve();
      } else if (e.data?.type === "fatal") {
        clearTimeout(timer);
        reject(new Error(`Couldn't load Python (${e.data.error}). Check your connection and try again.`));
      }
    };
    worker.addEventListener("message", onMsg);
    worker.onerror = (e) => {
      clearTimeout(timer);
      reject(new Error(e.message || "Couldn't start Python."));
    };
  });
  return { worker, url, ready };
}

/** Starts downloading Python in the background (call when a Python task opens). */
export function warmUpPython() {
  if (!py) {
    py = startPy();
    py.ready.catch(() => resetPy());
  }
}

async function runPy(code: string, tests: SandboxTest[], onStatus?: (s: string) => void): Promise<RunResult> {
  onStatus?.("Loading Python — first run only…");
  if (!py) py = startPy();
  const handle = py;
  try {
    await handle.ready;
  } catch (e) {
    resetPy();
    return failed(e instanceof Error ? e.message : "Couldn't load Python.");
  }
  onStatus?.("Running…");
  return new Promise((resolve) => {
    const id = token();
    let done = false;
    const finish = (r: RunResult) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      handle.worker.removeEventListener("message", onMsg);
      resolve(r);
    };
    const timer = setTimeout(() => {
      resetPy(); // the only way to stop an infinite loop; reloads (from cache) next run
      finish(failed(`Timed out after ${PY_TIMEOUT_MS / 1000}s — check for an infinite loop.`, true));
    }, PY_TIMEOUT_MS);
    const onMsg = (e: MessageEvent) => {
      if (e.data?.type !== "result" || e.data.token !== id) return;
      finish({ stdout: e.data.stdout ?? "", error: e.data.error ?? null, tests: e.data.tests ?? [], timedOut: false });
    };
    handle.worker.addEventListener("message", onMsg);
    handle.worker.postMessage({ token: id, code, tests });
  });
}

export function runCode(
  language: RunLanguage,
  code: string,
  tests: SandboxTest[],
  onStatus?: (s: string) => void,
): Promise<RunResult> {
  const runnable = executableTests(tests);
  return language === "python" ? runPy(code, runnable, onStatus) : runJs(code, runnable);
}
