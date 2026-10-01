import { useCallback, useEffect, useRef, useState } from "react";
import { getCourse, saveCourse, emptyLesson, type Course, type LessonState } from "../lib/training";

/**
 * Loads one course and keeps it in sync with Supabase. Edits apply to local
 * state immediately and are saved (debounced) so the learner can resume
 * exactly where they left off; anything pending is flushed when the screen
 * closes or the app is backgrounded.
 */
export function useCourse(id: string) {
  const [course, setCourse] = useState<Course | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const latest = useRef<Course | null>(null);
  const dirty = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    getCourse(id)
      .then((c) => {
        if (!alive) return;
        if (!c) setError("This course couldn't be found.");
        latest.current = c;
        setCourse(c);
      })
      .catch((e) => alive && setError(e instanceof Error ? e.message : "Couldn't load this course."))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [id]);

  const flush = useCallback(async () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    const c = latest.current;
    if (!c || !dirty.current) return;
    dirty.current = false;
    try {
      await saveCourse(c.id, {
        progress: c.progress,
        current_lesson_id: c.current_lesson_id,
        stage: c.stage,
        curriculum: c.curriculum,
        title: c.title,
      });
      setSaveError(null);
    } catch (e) {
      dirty.current = true; // retry on the next change / flush
      setSaveError(e instanceof Error ? e.message : "Couldn't save your progress.");
    }
  }, []);

  /** Apply a change to the course and schedule a save. */
  const update = useCallback(
    (fn: (c: Course) => Course) => {
      const next = latest.current ? fn(latest.current) : null;
      if (!next) return;
      latest.current = next;
      dirty.current = true;
      setCourse(next);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(flush, 700);
    },
    [flush],
  );

  const patchLesson = useCallback(
    (lessonId: string, fn: (s: LessonState) => LessonState) =>
      update((c) => ({
        ...c,
        progress: { ...c.progress, lessons: { ...c.progress.lessons, [lessonId]: fn(c.progress.lessons[lessonId] ?? emptyLesson()) } },
      })),
    [update],
  );

  useEffect(() => {
    const onHide = () => {
      if (document.visibilityState === "hidden") void flush();
    };
    document.addEventListener("visibilitychange", onHide);
    return () => {
      document.removeEventListener("visibilitychange", onHide);
      void flush();
    };
  }, [flush]);

  return { course, loading, error, saveError, update, patchLesson, flush };
}
