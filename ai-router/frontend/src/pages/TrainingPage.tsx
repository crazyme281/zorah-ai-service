import { useState } from "react";
import { IonPage, IonContent, IonIcon, IonSpinner, useIonRouter, useIonViewWillEnter } from "@ionic/react";
import { schoolOutline, lockClosedOutline, trashOutline, arrowForward, sparklesOutline, chevronBack } from "ionicons/icons";
import { TopBar } from "../components/TopBar";
import { usePlan } from "../hooks/usePlan";
import {
  api, createCourse, deleteCourse, listCourses, courseStats, looksLikeCoding, guessLanguage,
  CODING_LANGUAGES, LEVELS, STAGE_LABEL, STAGES, TrainingApiError, type Course, type Stage,
} from "../lib/training";

const IDEAS = ["Python", "JavaScript", "Spanish", "Personal finance", "Photography", "Chemistry", "Public speaking", "Music theory"];
const START_STAGE: Record<string, Stage> = {
  "Complete beginner": "basic", "Some experience": "basic", Comfortable: "intermediate", Experienced: "advanced",
};
const OTHER_LEVELS = ["Complete beginner", "I know a little", "Fairly confident", "Advanced"];

function Locked() {
  const router = useIonRouter();
  return (
    <div className="tr-locked">
      <IonIcon icon={lockClosedOutline} />
      <h2>Training is a Go feature</h2>
      <p>
        Learn anything with a personal tutor: a custom curriculum, lessons that adapt to you, hands-on tasks, a built-in
        code console and quizzes that explain your mistakes.
      </p>
      <button type="button" className="tr-btn tr-btn--gold" onClick={() => router.push("/upgrade", "forward")}>
        See plans <IonIcon icon={arrowForward} />
      </button>
    </div>
  );
}

function Setup({ onCancel, onCreated }: { onCancel: () => void; onCreated: (c: Course) => void }) {
  const [step, setStep] = useState<1 | 2>(1);
  const [subject, setSubject] = useState("");
  const [coding, setCoding] = useState(false);
  const [language, setLanguage] = useState<string | null>(null);
  const [level, setLevel] = useState<string>("");
  const [focus, setFocus] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function next() {
    const s = subject.trim();
    if (!s) return;
    const isCoding = looksLikeCoding(s);
    setCoding(isCoding);
    setLanguage(isCoding ? guessLanguage(s) : null);
    setLevel("");
    setStep(2);
  }

  async function create() {
    if (!level || (coding && !language)) return;
    setBusy(true);
    setError(null);
    try {
      const stage: Stage = coding ? START_STAGE[level] ?? "basic" : "basic";
      const cur = await api.curriculum({
        subject: subject.trim(), is_coding: coding, language: coding ? language : null, level, stage, focus: focus.trim() || undefined,
      });
      onCreated(
        await createCourse({ subject: subject.trim(), is_coding: coding, language: coding ? language : null, level, stage, curriculum: cur }),
      );
    } catch (e) {
      setError(e instanceof TrainingApiError || e instanceof Error ? e.message : "Couldn't build your course.");
      setBusy(false);
    }
  }

  if (busy)
    return (
      <div className="tr-loading tr-loading--big">
        <IonSpinner name="dots" />
        <h3>Building your learning path…</h3>
        <p>Your tutor is designing a curriculum for {subject.trim()}. This takes a few seconds.</p>
      </div>
    );

  return (
    <div className="tr-setup">
      <button type="button" className="tr-link" onClick={step === 1 ? onCancel : () => setStep(1)}>
        <IonIcon icon={chevronBack} /> Back
      </button>

      {step === 1 && (
        <>
          <h2 className="tr-title">What do you want to learn?</h2>
          <p className="tr-muted">Anything — a programming language, a school subject, a skill, a language.</p>
          <input
            className="tr-input" value={subject} maxLength={120} autoFocus placeholder="e.g. Python, Spanish, Photography…"
            onChange={(e) => setSubject(e.target.value)} onKeyDown={(e) => e.key === "Enter" && next()}
          />
          <div className="tr-chips">
            {IDEAS.map((i) => (
              <button key={i} type="button" className="tr-chip" onClick={() => setSubject(i)}>{i}</button>
            ))}
          </div>
          <button type="button" className="tr-btn tr-btn--gold tr-btn--block" disabled={!subject.trim()} onClick={next}>
            Continue <IonIcon icon={arrowForward} />
          </button>
        </>
      )}

      {step === 2 && (
        <>
          <h2 className="tr-title">{coding ? "Set up your coding path" : "Where are you starting from?"}</h2>
          <label className="tr-toggle">
            <input type="checkbox" checked={coding} onChange={(e) => { setCoding(e.target.checked); setLevel(""); setLanguage(e.target.checked ? guessLanguage(subject) : null); }} />
            This is a programming topic
          </label>

          {coding && (
            <>
              <p className="tr-eyebrow">Programming language</p>
              <div className="tr-chips">
                {CODING_LANGUAGES.map((l) => (
                  <button key={l} type="button" className={`tr-chip ${language === l ? "is-on" : ""}`} onClick={() => setLanguage(l)}>{l}</button>
                ))}
              </div>
            </>
          )}

          <p className="tr-eyebrow">{coding ? "Your current level" : "Your current level"}</p>
          <div className="tr-chips">
            {(coding ? LEVELS : OTHER_LEVELS).map((l) => (
              <button key={l} type="button" className={`tr-chip ${level === l ? "is-on" : ""}`} onClick={() => setLevel(l)}>{l}</button>
            ))}
          </div>
          {coding && level && (
            <p className="tr-muted">
              You'll start at <strong>{STAGE_LABEL[START_STAGE[level] ?? "basic"]}</strong> and work towards{" "}
              {STAGES.map((s) => STAGE_LABEL[s]).join(" → ")}.
            </p>
          )}

          <p className="tr-eyebrow">Anything specific? (optional)</p>
          <input className="tr-input" value={focus} maxLength={300} placeholder={coding ? "e.g. I want to build mobile apps" : "e.g. I'm preparing for an exam"} onChange={(e) => setFocus(e.target.value)} />

          {error && <p className="tr-error-inline">{error}</p>}
          <button type="button" className="tr-btn tr-btn--gold tr-btn--block" disabled={!level || (coding && !language)} onClick={create}>
            <IonIcon icon={sparklesOutline} /> Create my learning path
          </button>
        </>
      )}
    </div>
  );
}

export function TrainingPage() {
  const router = useIonRouter();
  const { plan } = usePlan();
  const allowed = plan?.tier === "GO" || plan?.tier === "PRO";
  const [courses, setCourses] = useState<Course[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [setup, setSetup] = useState(false);

  useIonViewWillEnter(() => {
    listCourses().then(setCourses).catch((e) => setError(e instanceof Error ? e.message : "Couldn't load your courses."));
  });

  async function remove(c: Course) {
    if (!window.confirm(`Delete "${c.title}" and all its progress?`)) return;
    try {
      await deleteCourse(c.id);
      setCourses((cs) => (cs ?? []).filter((x) => x.id !== c.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't delete that course.");
    }
  }

  return (
    <IonPage>
      <TopBar />
      <IonContent className="panel-page">
        <div className="tr-page">
          {!allowed ? (
            <Locked />
          ) : setup ? (
            <Setup onCancel={() => setSetup(false)} onCreated={(c) => { setSetup(false); router.push(`/training/${c.id}`, "forward"); }} />
          ) : (
            <>
              <div className="tr-hero">
                <IonIcon icon={schoolOutline} />
                <h1 className="tr-title">Training</h1>
                <p className="tr-muted">Your personal tutor — lessons, tasks and quizzes that adapt to you.</p>
                <button type="button" className="tr-btn tr-btn--gold" onClick={() => setSetup(true)}>
                  <IonIcon icon={sparklesOutline} /> Start learning something new
                </button>
              </div>

              {error && <p className="tr-error-inline">{error}</p>}
              {!courses && !error && <div className="tr-loading"><IonSpinner name="dots" /></div>}
              {courses && courses.length > 0 && <h3 className="tr-h">Continue learning</h3>}
              {courses?.map((c) => {
                const s = courseStats(c);
                return (
                  <div key={c.id} className="tr-course">
                    <button type="button" className="tr-course__main" onClick={() => router.push(`/training/${c.id}`, "forward")}>
                      <strong>{c.title}</strong>
                      <span className="tr-muted">
                        {c.is_coding ? `${c.language} · ${STAGE_LABEL[c.stage]}` : c.subject} · {s.done}/{s.total} lessons
                      </span>
                      <div className="tr-bar"><i style={{ width: `${s.pct}%` }} /></div>
                    </button>
                    <button type="button" className="tr-icon-btn" aria-label={`Delete ${c.title}`} onClick={() => remove(c)}>
                      <IonIcon icon={trashOutline} />
                    </button>
                  </div>
                );
              })}
            </>
          )}
        </div>
      </IonContent>
    </IonPage>
  );
}
