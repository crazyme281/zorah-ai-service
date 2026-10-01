import { useEffect, useRef, useState } from "react";
import { IonIcon, IonSpinner } from "@ionic/react";
import { bulbOutline, checkmarkCircle, alertCircle, arrowForward, eyeOutline } from "ionicons/icons";
import { RichText, CodeBlock } from "./CodeBlock";
import { CodeConsole } from "./CodeConsole";
import { Loading, ErrorBox } from "./LessonView";
import { runCode, executableTests, type RunResult, type RunLanguage } from "../../lib/sandbox";
import {
  api, TrainingApiError, lessonPerformance, type Course, type LessonRef, type LessonState,
} from "../../lib/training";

const SKIP_AFTER = 2; // failed attempts before "show solution" / "skip" appear

/** Step 2 — a practical task. Coding tasks get the in-page console. */
export function TaskView({
  course, lesson, state, onChange, onContinue,
}: {
  course: Course; lesson: LessonRef; state: LessonState;
  onChange: (fn: (s: LessonState) => LessonState) => void; onContinue: () => void;
}) {
  const task = state.task;
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [run, setRun] = useState<RunResult | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [hints, setHints] = useState(0);
  const [showSolution, setShowSolution] = useState(false);
  const inflight = useRef(false);

  async function generate() {
    if (inflight.current) return;
    inflight.current = true;
    setLoading(true);
    setError(null);
    try {
      const t = await api.task(course, lesson, lessonPerformance(state));
      onChange((s) => ({ ...s, task: t, taskCode: s.taskCode ?? t.starter_code }));
    } catch (e) {
      setError(e instanceof TrainingApiError ? e.message : "Couldn't prepare the task.");
    } finally {
      inflight.current = false;
      setLoading(false);
    }
  }
  useEffect(() => {
    if (!task) void generate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lesson.id]);

  if (error) return <ErrorBox text={error} onRetry={generate} />;
  if (!task || loading) return <Loading text="Your tutor is designing a practice task…" />;

  const isCode = task.kind === "code";
  const code = state.taskCode ?? task.starter_code;
  const review = state.taskReview;
  const failedAttempts = state.taskAttempts - (review?.passed ? 1 : 0);

  async function submit() {
    if (!task || submitting) return;
    if (!code.trim()) return setError("Write something first.");
    setSubmitting(true);
    setError(null);
    try {
      let result = run;
      let mode: "review" | "tests" = "review";
      // Always grade the code as it is NOW, not a stale earlier run.
      if (isCode && task.execution !== "none") {
        result = await runCode(task.execution as RunLanguage, code, task.tests);
        setRun(result);
        if (executableTests(task.tests).length > 0 && !result.timedOut) mode = "tests";
      }
      const executable = executableTests(task.tests).length;
      const allPassed = !!result && !result.error && result.tests.length === executable && result.tests.every((t) => t.passed);
      const r = await api.reviewTask({
        subject: course.subject, language: task.language, task, submission: code, mode,
        run_result: result ? { stdout: result.stdout.slice(0, 1500), error: result.error, tests: result.tests } : undefined,
        all_tests_passed: allPassed,
      });
      onChange((s) => ({ ...s, taskReview: r, taskAttempts: s.taskAttempts + 1 }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't review your work.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="tr-task">
      <p className="tr-eyebrow">Practice task</p>
      <h3 className="tr-h">{task.title}</h3>
      <RichText>{task.instructions_md}</RichText>

      {isCode ? (
        <CodeConsole
          task={task} code={code} result={run} onResult={setRun} disabled={submitting || !!review?.passed}
          onCode={(v) => onChange((s) => ({ ...s, taskCode: v }))}
        />
      ) : (
        <>
          {task.rubric.length > 0 && (
            <div className="tr-objectives">
              <p className="tr-eyebrow">A strong answer…</p>
              <ul>{task.rubric.map((r, i) => <li key={i}>{r}</li>)}</ul>
            </div>
          )}
          <textarea
            className="tr-input tr-input--tall" rows={9} value={code} disabled={submitting || !!review?.passed}
            placeholder="Write your answer here…" onChange={(e) => onChange((s) => ({ ...s, taskCode: e.target.value }))}
          />
        </>
      )}

      {task.hints.length > 0 && !review?.passed && (
        <div className="tr-hints">
          {task.hints.slice(0, hints).map((h, i) => <p key={i} className="tr-hint"><IonIcon icon={bulbOutline} /> {h}</p>)}
          {hints < task.hints.length && (
            <button type="button" className="tr-link" onClick={() => setHints((n) => n + 1)}>
              <IonIcon icon={bulbOutline} /> {hints === 0 ? "Need a hint?" : "Another hint"}
            </button>
          )}
        </div>
      )}

      {error && <p className="tr-error-inline">{error}</p>}

      {!review?.passed && (
        <button type="button" className="tr-btn tr-btn--gold tr-btn--block" disabled={submitting} onClick={submit}>
          {submitting ? <><IonSpinner name="dots" /> Checking your work…</> : "Submit for feedback"}
        </button>
      )}

      {review && (
        <div className={`tr-result ${review.passed ? "tr-result--ok" : "tr-result--bad"}`}>
          <strong>
            <IonIcon icon={review.passed ? checkmarkCircle : alertCircle} />
            {review.passed ? "Task complete" : "Almost — keep going"} · {review.score}/100
          </strong>
          <RichText>{review.feedback_md}</RichText>
          {review.next_steps.length > 0 && (
            <ul>{review.next_steps.map((n, i) => <li key={i}>{n}</li>)}</ul>
          )}
        </div>
      )}

      {!review?.passed && failedAttempts >= SKIP_AFTER && (
        <div className="tr-stuck">
          <p className="tr-muted">Stuck? That's part of learning.</p>
          {task.solution && !showSolution && (
            <button type="button" className="tr-btn" onClick={() => setShowSolution(true)}>
              <IonIcon icon={eyeOutline} /> Show a solution
            </button>
          )}
          {showSolution && task.solution && (
            isCode ? <CodeBlock code={task.solution} language={task.language ?? undefined} /> : <RichText>{task.solution}</RichText>
          )}
          <button
            type="button" className="tr-link"
            onClick={() => { onChange((s) => ({ ...s, taskSkipped: true })); onContinue(); }}
          >
            Skip this task for now
          </button>
        </div>
      )}

      {(review?.passed || state.taskSkipped) && (
        <button type="button" className="tr-btn tr-btn--gold tr-btn--block" onClick={onContinue}>
          Continue to the quiz <IonIcon icon={arrowForward} />
        </button>
      )}
    </div>
  );
}
