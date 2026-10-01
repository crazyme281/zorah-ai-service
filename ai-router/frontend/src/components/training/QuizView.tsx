import { useEffect, useRef, useState } from "react";
import { IonIcon } from "@ionic/react";
import { checkmarkCircle, closeCircle, arrowForward, refreshOutline } from "ionicons/icons";
import { RichText } from "./CodeBlock";
import { Loading, ErrorBox } from "./LessonView";
import { api, TrainingApiError, lessonPerformance, quizResult, type Course, type LessonRef, type LessonState } from "../../lib/training";

/** Step 3 — a quiz that explains mistakes rather than just marking them wrong. */
export function QuizView({
  course, lesson, state, onChange, onFinish,
}: {
  course: Course; lesson: LessonRef; state: LessonState;
  onChange: (fn: (s: LessonState) => LessonState) => void; onFinish: () => void;
}) {
  const quiz = state.quiz;
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [idx, setIdx] = useState(0);
  const [picked, setPicked] = useState<number | null>(null);
  const inflight = useRef(false);

  async function generate(fresh = false) {
    if (inflight.current) return;
    inflight.current = true;
    setLoading(true);
    setError(null);
    try {
      const q = await api.quiz(course, lesson, lessonPerformance(state));
      onChange((s) => ({ ...s, quiz: q, quizAnswers: {} }));
      setIdx(0);
      setPicked(null);
    } catch (e) {
      setError(e instanceof TrainingApiError ? e.message : "Couldn't prepare the quiz.");
    } finally {
      inflight.current = false;
      setLoading(false);
    }
    void fresh;
  }
  useEffect(() => {
    if (!quiz) void generate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lesson.id]);

  // Resume at the first unanswered question.
  useEffect(() => {
    if (!quiz) return;
    const first = quiz.questions.findIndex((q) => state.quizAnswers[q.id] === undefined);
    setIdx(first === -1 ? quiz.questions.length : first);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [quiz?.questions.length]);

  if (error) return <ErrorBox text={error} onRetry={() => generate()} />;
  if (!quiz || loading) return <Loading text="Writing your quiz…" />;

  const total = quiz.questions.length;
  const result = quizResult(state);

  if (idx >= total && result) {
    const pct = Math.round((100 * result.correct) / result.total);
    const missed = quiz.questions.filter((q) => state.quizAnswers[q.id] !== q.correct_index);
    return (
      <div className="tr-quiz-result">
        <div className={`tr-score ${pct >= 70 ? "tr-score--ok" : "tr-score--low"}`}>
          <strong>{pct}%</strong>
          <span>{result.correct} of {result.total} correct</span>
        </div>
        <p>
          {pct >= 80 ? "Excellent — you've got this topic." : pct >= 60 ? "Good progress. Review the points below and you'll lock it in." : "This one's tricky — go back over the lesson, then retake the quiz when you're ready."}
        </p>
        {missed.length > 0 && <h3 className="tr-h">Worth another look</h3>}
        {missed.map((q) => {
          const chosen = state.quizAnswers[q.id];
          return (
            <div key={q.id} className="tr-q tr-q--bad">
              <RichText>{q.prompt}</RichText>
              <p className="tr-why"><IonIcon icon={closeCircle} /> You chose: {q.options[chosen]}</p>
              {q.why_wrong[chosen] && <p className="tr-muted">{q.why_wrong[chosen]}</p>}
              <p className="tr-why tr-why--ok"><IonIcon icon={checkmarkCircle} /> Answer: {q.options[q.correct_index]}</p>
              <RichText>{q.explanation}</RichText>
            </div>
          );
        })}
        <div className="tr-row">
          <button type="button" className="tr-btn" onClick={() => { onChange((s) => ({ ...s, quiz: undefined, quizAnswers: {} })); setTimeout(() => generate(true), 0); }}>
            <IonIcon icon={refreshOutline} /> Retake with new questions
          </button>
          <button type="button" className="tr-btn tr-btn--gold" onClick={onFinish}>
            Finish lesson <IonIcon icon={arrowForward} />
          </button>
        </div>
      </div>
    );
  }

  const q = quiz.questions[idx];
  const answered = state.quizAnswers[q.id];
  const hasAnswered = answered !== undefined;

  return (
    <div className="tr-quiz">
      <div className="tr-bar"><i style={{ width: `${(100 * idx) / total}%` }} /></div>
      <p className="tr-eyebrow">Question {idx + 1} of {total}</p>
      <RichText>{q.prompt}</RichText>
      <div className="tr-options">
        {q.options.map((o, i) => {
          const right = hasAnswered && i === q.correct_index;
          const wrong = hasAnswered && i === answered && i !== q.correct_index;
          return (
            <button
              key={i} type="button" disabled={hasAnswered}
              className={`tr-opt ${picked === i && !hasAnswered ? "is-picked" : ""} ${right ? "is-right" : ""} ${wrong ? "is-wrong" : ""}`}
              onClick={() => setPicked(i)}
            >
              <span>{String.fromCharCode(65 + i)}</span>
              {o}
            </button>
          );
        })}
      </div>

      {!hasAnswered && (
        <button
          type="button" className="tr-btn tr-btn--gold tr-btn--block" disabled={picked === null}
          onClick={() => picked !== null && onChange((s) => ({ ...s, quizAnswers: { ...s.quizAnswers, [q.id]: picked } }))}
        >
          Check answer
        </button>
      )}

      {hasAnswered && (
        <div className={`tr-feedback ${answered === q.correct_index ? "tr-feedback--ok" : "tr-feedback--bad"}`}>
          <strong>
            <IonIcon icon={answered === q.correct_index ? checkmarkCircle : closeCircle} />
            {answered === q.correct_index ? "Correct" : "Not quite"}
          </strong>
          {answered !== q.correct_index && q.why_wrong[answered] && <p>{q.why_wrong[answered]}</p>}
          {answered !== q.correct_index && <p className="tr-why tr-why--ok">The answer: {q.options[q.correct_index]}</p>}
          <RichText>{q.explanation}</RichText>
          <button type="button" className="tr-btn tr-btn--gold tr-btn--block" onClick={() => { setPicked(null); setIdx(idx + 1); }}>
            {idx + 1 < total ? "Next question" : "See my results"} <IonIcon icon={arrowForward} />
          </button>
        </div>
      )}
    </div>
  );
}
