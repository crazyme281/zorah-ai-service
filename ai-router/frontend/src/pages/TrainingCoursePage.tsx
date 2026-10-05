import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { IonPage, IonContent, IonIcon, IonSpinner, useIonRouter } from "@ionic/react";
import {
  chevronBack, checkmarkCircle, ellipseOutline, playCircleOutline, chevronDown, chevronUp, arrowForward, ribbonOutline,
} from "ionicons/icons";
import { TopBar } from "../components/TopBar";
import { LessonView, ErrorBox } from "../components/training/LessonView";
import { TaskView } from "../components/training/TaskView";
import { QuizView } from "../components/training/QuizView";
import { useCourse } from "../hooks/useCourse";
import { usePlan } from "../hooks/usePlan";
import {
  api, allLessons, courseStats, emptyLesson, isDone, nextLesson, quizResult, recommend, STAGES, STAGE_LABEL,
  type Step,
} from "../lib/training";

const STEPS: { id: Step; label: string }[] = [
  { id: "learn", label: "Learn" },
  { id: "task", label: "Task" },
  { id: "quiz", label: "Quiz" },
];
const ORDER: Step[] = ["learn", "task", "quiz", "done"];

export function TrainingCoursePage() {
  const { courseId } = useParams<{ courseId: string }>();
  const router = useIonRouter();
  const { plan } = usePlan();
  const { course, loading, error, saveError, update, patchLesson, flush } = useCourse(courseId);
  const [view, setView] = useState<Step>("learn");
  const [pathOpen, setPathOpen] = useState(false);
  const [advancing, setAdvancing] = useState(false);
  const [advanceError, setAdvanceError] = useState<string | null>(null);
  const content = useRef<HTMLIonContentElement>(null);
  const shownLesson = useRef<string | null>(null);

  const lessons = course ? allLessons(course) : [];
  const lesson = course ? lessons.find((l) => l.id === course.current_lesson_id) ?? nextLesson(course) ?? lessons[0] : undefined;
  const state = lesson && course ? course.progress.lessons[lesson.id] : undefined;
  const allowed = plan?.tier === "GO" || plan?.tier === "PRO";
  const planKnown = !!plan; // an unknown plan is not a lapsed plan

  // When the lesson changes, open it on the step the learner was up to.
  useEffect(() => {
    if (!lesson) return;
    if (shownLesson.current !== lesson.id) {
      shownLesson.current = lesson.id;
      const st = state?.step ?? "learn";
      setView(st === "done" ? "learn" : st);
    }
  }, [lesson, state?.step]);

  function go(step: Step) {
    setView(step);
    content.current?.scrollToTop(250);
  }

  if (loading) return <IonPage><TopBar /><IonContent className="panel-page"><div className="tr-loading tr-loading--big"><IonSpinner name="dots" /></div></IonContent></IonPage>;
  if (error || !course || !lesson)
    return (
      <IonPage><TopBar /><IonContent className="panel-page"><div className="tr-page">
        <ErrorBox text={error ?? "This course couldn't be found."} />
        <button type="button" className="tr-btn" onClick={() => router.push("/training", "none", "replace")}>All courses</button>
      </div></IonContent></IonPage>
    );

  const stats = courseStats(course);
  const rec = recommend(course);
  const cur = state ?? emptyLesson();
  const reached = ORDER.indexOf(cur.step);
  const done = isDone(course, lesson.id);
  const locked = planKnown && !allowed;

  function selectLesson(id: string) {
    update((c) => ({ ...c, current_lesson_id: id }));
    setPathOpen(false);
    content.current?.scrollToTop(250);
  }

  function finishLesson() {
    patchLesson(lesson!.id, (s) => ({ ...s, step: "done", completedAt: new Date().toISOString() }));
    update((c) => {
      const nxt = nextLesson({ ...c, progress: { ...c.progress, lessons: { ...c.progress.lessons, [lesson!.id]: { ...(c.progress.lessons[lesson!.id] ?? emptyLesson()), step: "done" } } } }, lesson!.id);
      return nxt ? { ...c, current_lesson_id: nxt.id } : c;
    });
    content.current?.scrollToTop(250);
  }

  async function advanceStage(next: (typeof STAGES)[number]) {
    if (!course) return;
    setAdvancing(true);
    setAdvanceError(null);
    try {
      const cur2 = await api.curriculum({
        subject: course.subject, is_coding: course.is_coding, language: course.language, level: course.level, stage: next,
        focus: `Continue from the learner's completed ${STAGE_LABEL[course.stage]} stage.`,
      });
      update((c) => ({
        ...c, stage: next, curriculum: cur2,
        progress: { lessons: {}, history: [...c.progress.history, { stage: c.stage, completedAt: new Date().toISOString(), quizPct: stats.quizPct ?? 0 }] },
        current_lesson_id: cur2.modules[0]?.lessons[0]?.id ?? null,
      }));
      shownLesson.current = null;
      await flush();
    } catch (e) {
      setAdvanceError(e instanceof Error ? e.message : "Couldn't build the next stage.");
    } finally {
      setAdvancing(false);
    }
  }

  return (
    <IonPage>
      <TopBar />
      <IonContent className="panel-page" ref={content}>
        <div className="tr-page">
          <button type="button" className="tr-link" onClick={() => router.push("/training", "none", "replace")}>
            <IonIcon icon={chevronBack} /> All courses
          </button>
          <h1 className="tr-title">{course.title}</h1>

          {course.is_coding && (
            <div className="tr-roadmap" aria-label="Coding path">
              {STAGES.map((s, i) => {
                const passed = STAGES.indexOf(course.stage) > i;
                return (
                  <span key={s} className={`tr-stage ${s === course.stage ? "is-current" : ""} ${passed ? "is-done" : ""}`}>
                    {passed && <IonIcon icon={checkmarkCircle} />}
                    {STAGE_LABEL[s]}
                  </span>
                );
              })}
            </div>
          )}

          <div className="tr-progress">
            <div className="tr-bar"><i style={{ width: `${stats.pct}%` }} /></div>
            <p className="tr-muted">
              {stats.done}/{stats.total} lessons · {stats.tasksPassed} tasks passed{stats.quizPct !== null ? ` · quizzes ${stats.quizPct}%` : ""}
            </p>
          </div>

          {locked && <ErrorBox text="Your plan no longer includes Training. Your progress is saved — upgrade to keep learning." />}
          {saveError && <p className="tr-error-inline">Couldn't save your latest progress ({saveError}). It will retry.</p>}

          {rec.kind !== "continue" && (
            <div className="tr-rec">
              <IonIcon icon={ribbonOutline} />
              <div>
                <strong>{rec.text}</strong>
                {rec.kind === "advance" && (
                  <button type="button" className="tr-btn tr-btn--gold" disabled={advancing || locked} onClick={() => advanceStage(rec.next)}>
                    {advancing ? <><IonSpinner name="dots" /> Building…</> : <>Start {STAGE_LABEL[rec.next]} <IonIcon icon={arrowForward} /></>}
                  </button>
                )}
                {rec.kind === "review" && (
                  <button type="button" className="tr-btn" onClick={() => selectLesson(rec.lessonIds[0])}>Review now</button>
                )}
                {advanceError && <p className="tr-error-inline">{advanceError}</p>}
              </div>
            </div>
          )}

          <button type="button" className="tr-path-toggle" onClick={() => setPathOpen((o) => !o)}>
            Learning path <IonIcon icon={pathOpen ? chevronUp : chevronDown} />
          </button>
          {pathOpen && (
            <div className="tr-path">
              {course.curriculum.overview && <p className="tr-muted">{course.curriculum.overview}</p>}
              {course.curriculum.modules.map((m, mi) => (
                <div key={mi}>
                  <p className="tr-eyebrow">{m.title}</p>
                  {m.lessons.map((l) => {
                    const s = course.progress.lessons[l.id];
                    const q = quizResult(s);
                    return (
                      <button key={l.id} type="button" className={`tr-lesson-row ${l.id === lesson.id ? "is-current" : ""}`} onClick={() => selectLesson(l.id)}>
                        <IonIcon icon={s?.step === "done" ? checkmarkCircle : s ? playCircleOutline : ellipseOutline} />
                        <span>{l.title}</span>
                        {q && <em>{Math.round((100 * q.correct) / q.total)}%</em>}
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>
          )}

          <div className="tr-lesson-head">
            <p className="tr-eyebrow">Lesson {lessons.findIndex((l) => l.id === lesson.id) + 1} of {lessons.length}{done ? " · completed" : ""}</p>
            <h2 className="tr-h tr-h--lg">{lesson.title}</h2>
          </div>

          <div className="tr-tabs tr-tabs--steps" role="tablist">
            {STEPS.map((s, i) => (
              <button key={s.id} role="tab" aria-selected={view === s.id} disabled={i > reached && !done} className={view === s.id ? "is-on" : ""} onClick={() => go(s.id)}>
                {s.label}
              </button>
            ))}
          </div>

          {view === "learn" && (
            <LessonView
              key={`l-${lesson.id}`} course={course} lesson={lesson} state={state}
              onChange={(fn) => patchLesson(lesson.id, fn)}
              onContinue={() => { patchLesson(lesson.id, (s) => (s.step === "learn" ? { ...s, step: "task" } : s)); go("task"); }}
            />
          )}
          {view === "task" && (
            <TaskView
              key={`t-${lesson.id}`} course={course} lesson={lesson} state={cur}
              onChange={(fn) => patchLesson(lesson.id, fn)}
              onContinue={() => { patchLesson(lesson.id, (s) => (s.step === "task" ? { ...s, step: "quiz" } : s)); go("quiz"); }}
            />
          )}
          {view === "quiz" && (
            <QuizView key={`q-${lesson.id}`} course={course} lesson={lesson} state={cur} onChange={(fn) => patchLesson(lesson.id, fn)} onFinish={finishLesson} />
          )}
        </div>
      </IonContent>
    </IonPage>
  );
}