import { useEffect, useMemo, useRef, useState } from "react";
import { IonIcon, IonSpinner } from "@ionic/react";
import { checkmarkCircle, closeCircle, bulbOutline, arrowForward } from "ionicons/icons";
import { RichText } from "./CodeBlock";
import {
  api, TrainingApiError, type Course, type LessonRef, type LessonState, type LessonQ, type QuestionRecord,
} from "../../lib/training";

export function Loading({ text }: { text: string }) {
  return (
    <div className="tr-loading">
      <IonSpinner name="dots" />
      <p>{text}</p>
    </div>
  );
}
export function ErrorBox({ text, onRetry }: { text: string; onRetry?: () => void }) {
  return (
    <div className="tr-error">
      <p>{text}</p>
      {onRetry && (
        <button type="button" className="tr-btn" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

/** Inline SVG diagram from the tutor. Rendered via <img>, which never runs scripts. */
function Diagram({ svg, caption }: { svg: string; caption: string }) {
  const src = useMemo(() => `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`, [svg]);
  return (
    <figure className="tr-figure">
      <img src={src} alt={caption || "Diagram"} />
      {caption && <figcaption>{caption}</figcaption>}
    </figure>
  );
}

function Question({
  course, lesson, q, record, onRecord,
}: {
  course: Course; lesson: LessonRef; q: LessonQ; record?: QuestionRecord; onRecord: (r: QuestionRecord) => void;
}) {
  const [picked, setPicked] = useState<number | null>(null);
  const [text, setText] = useState("");
  const [follow, setFollow] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [hint, setHint] = useState(false);

  async function submitChoice() {
    if (q.type !== "choice" || picked === null) return;
    const correct = picked === q.correct_index;
    // Show the answer instantly, then let the tutor adapt (feedback + an
    // easier follow-up) when the learner got it wrong.
    onRecord({ answer: q.options[picked], correct, feedback_md: q.explanation });
    if (!correct) {
      setBusy(true);
      try {
        const r = await api.answer({
          subject: course.subject, lesson_title: lesson.title, question: q.prompt, options: q.options,
          reference: q.options[q.correct_index], user_answer: q.options[picked], was_correct: false,
        });
        onRecord({ answer: q.options[picked], correct, feedback_md: r.feedback_md || q.explanation, follow_up: r.follow_up ?? undefined });
      } catch {
        /* the built-in explanation is already showing */
      } finally {
        setBusy(false);
      }
    }
  }

  async function submitShort() {
    if (q.type !== "short" || !text.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await api.answer({
        subject: course.subject, lesson_title: lesson.title, question: q.prompt, reference: q.reference, user_answer: text.trim(),
      });
      onRecord({ answer: text.trim(), correct: r.correct, feedback_md: r.feedback_md, follow_up: r.follow_up ?? undefined });
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Couldn't check that answer.");
    } finally {
      setBusy(false);
    }
  }

  async function submitFollow() {
    if (!record?.follow_up || !follow.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await api.answer({
        subject: course.subject, lesson_title: lesson.title, question: record.follow_up.prompt,
        reference: record.follow_up.reference, user_answer: follow.trim(),
      });
      onRecord({ ...record, follow_up: { ...record.follow_up, answer: follow.trim(), feedback_md: r.feedback_md } });
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Couldn't check that answer.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={`tr-q ${record ? (record.correct ? "tr-q--ok" : "tr-q--bad") : ""}`}>
      <RichText>{q.prompt}</RichText>
      {q.type === "choice" && (
        <div className="tr-options">
          {q.options.map((o, i) => {
            const answered = !!record;
            const isRight = answered && i === q.correct_index;
            const isWrongPick = answered && !record!.correct && o === record!.answer;
            return (
              <button
                key={i} type="button" disabled={answered}
                className={`tr-opt ${picked === i && !answered ? "is-picked" : ""} ${isRight ? "is-right" : ""} ${isWrongPick ? "is-wrong" : ""}`}
                onClick={() => setPicked(i)}
              >
                <span>{String.fromCharCode(65 + i)}</span>
                {o}
              </button>
            );
          })}
        </div>
      )}
      {q.type === "short" && (
        <textarea
          className="tr-input" rows={3} value={record ? record.answer : text} disabled={!!record || busy}
          placeholder="Type your answer…" onChange={(e) => setText(e.target.value)}
        />
      )}

      {!record && (
        <div className="tr-row">
          {q.hint && (
            <button type="button" className="tr-link" onClick={() => setHint((h) => !h)}>
              <IonIcon icon={bulbOutline} /> {hint ? "Hide hint" : "Hint"}
            </button>
          )}
          <button
            type="button" className="tr-btn tr-btn--gold"
            disabled={busy || (q.type === "choice" ? picked === null : !text.trim())}
            onClick={q.type === "choice" ? submitChoice : submitShort}
          >
            {busy ? <IonSpinner name="dots" /> : "Check"}
          </button>
        </div>
      )}
      {!record && hint && q.hint && <p className="tr-hint">{q.hint}</p>}

      {record && (
        <div className="tr-feedback">
          <strong>
            <IonIcon icon={record.correct ? checkmarkCircle : closeCircle} /> {record.correct ? "Correct" : "Not quite"}
          </strong>
          {record.feedback_md && <RichText>{record.feedback_md}</RichText>}
          {busy && !record.follow_up && <p className="tr-muted">Your tutor is thinking about what to ask next…</p>}
          {record.follow_up && (
            <div className="tr-follow">
              <p className="tr-eyebrow">Let's try an easier one</p>
              <RichText>{record.follow_up.prompt}</RichText>
              {record.follow_up.answer === undefined ? (
                <>
                  <textarea className="tr-input" rows={2} value={follow} disabled={busy} onChange={(e) => setFollow(e.target.value)} placeholder="Your answer…" />
                  <button type="button" className="tr-btn" disabled={busy || !follow.trim()} onClick={submitFollow}>
                    {busy ? <IonSpinner name="dots" /> : "Check"}
                  </button>
                </>
              ) : (
                record.follow_up.feedback_md && <RichText>{record.follow_up.feedback_md}</RichText>
              )}
            </div>
          )}
        </div>
      )}
      {err && <p className="tr-error-inline">{err}</p>}
    </div>
  );
}

/** Step 1 — the lesson: explanation, examples, diagram and adaptive questions. */
export function LessonView({
  course, lesson, state, onChange, onContinue,
}: {
  course: Course; lesson: LessonRef; state: LessonState | undefined;
  onChange: (fn: (s: LessonState) => LessonState) => void; onContinue: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const inflight = useRef<string | null>(null);
  const content = state?.content;

  async function generate() {
    if (inflight.current === lesson.id) return;
    inflight.current = lesson.id;
    setLoading(true);
    setError(null);
    try {
      const c = await api.lesson(course, lesson);
      onChange((s) => ({ ...s, content: c }));
    } catch (e) {
      setError(e instanceof TrainingApiError ? e.message : "Couldn't prepare this lesson.");
    } finally {
      inflight.current = null;
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!content) void generate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lesson.id]);

  if (error) return <ErrorBox text={error} onRetry={generate} />;
  if (!content || loading) return <Loading text={`Your tutor is preparing "${lesson.title}"…`} />;

  const answered = content.questions.filter((q) => state?.answers[q.id]).length;
  const allDone = answered === content.questions.length;

  return (
    <div className="tr-lesson">
      {content.objectives.length > 0 && (
        <div className="tr-objectives">
          <p className="tr-eyebrow">In this lesson you'll learn</p>
          <ul>{content.objectives.map((o, i) => <li key={i}>{o}</li>)}</ul>
        </div>
      )}
      <RichText>{content.explanation_md}</RichText>
      {content.diagram_svg && <Diagram svg={content.diagram_svg} caption={content.diagram_caption} />}
      {content.examples.map((e, i) => (
        <section key={i} className="tr-example">
          <p className="tr-eyebrow">{e.title || `Example ${i + 1}`}</p>
          <RichText>{e.body_md}</RichText>
        </section>
      ))}

      <h3 className="tr-h">Check your understanding</h3>
      <p className="tr-muted">{answered}/{content.questions.length} answered — your tutor adapts to how you do.</p>
      {content.questions.map((q) => (
        <Question
          key={q.id} course={course} lesson={lesson} q={q} record={state?.answers[q.id]}
          onRecord={(r) => onChange((s) => ({ ...s, answers: { ...s.answers, [q.id]: r } }))}
        />
      ))}

      <button type="button" className="tr-btn tr-btn--gold tr-btn--block" disabled={!allDone} onClick={onContinue}>
        {allDone ? "Continue to the task" : "Answer all questions to continue"} <IonIcon icon={arrowForward} />
      </button>
    </div>
  );
}
