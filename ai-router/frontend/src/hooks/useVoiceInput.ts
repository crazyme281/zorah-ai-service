/**
 * Voice capture with two paths, because no single one works everywhere:
 *
 *  1. Web Speech API — instant, free, no round trip. Chrome, Edge, and
 *     Safari 14.1+. This is the happy path.
 *  2. MediaRecorder -> POST /transcribe — everywhere else (Firefox, some
 *     Android webviews). Needs the backend endpoint to exist.
 *
 * Both run at once when available: recognition gives live interim text for
 * the composer, and the recorded blob is the fallback if recognition yields
 * nothing by the time the user stops.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { transcribeAudio } from "../lib/aiBackend";

type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((e: any) => void) | null;
  onerror: ((e: any) => void) | null;
  onend: (() => void) | null;
};

function getRecognitionCtor(): (new () => SpeechRecognitionLike) | null {
  const w = window as any;
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export type VoiceStatus = "idle" | "recording" | "transcribing" | "error";

export function useVoiceInput(onTranscript: (text: string) => void) {
  const [status, setStatus] = useState<VoiceStatus>("idle");
  const [interim, setInterim] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [seconds, setSeconds] = useState(0);

  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const finalRef = useRef("");
  const streamRef = useRef<MediaStream | null>(null);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const supported =
    typeof window !== "undefined" &&
    (!!getRecognitionCtor() || !!navigator.mediaDevices?.getUserMedia);

  /** Release the mic — the browser keeps the indicator lit otherwise. */
  const teardown = useCallback(() => {
    if (tickRef.current) clearInterval(tickRef.current);
    tickRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    recognitionRef.current = null;
    recorderRef.current = null;
  }, []);

  useEffect(() => teardown, [teardown]);

  const start = useCallback(async () => {
    setError(null);
    setInterim("");
    setSeconds(0);
    finalRef.current = "";
    chunksRef.current = [];

    const Ctor = getRecognitionCtor();

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const recorder = new MediaRecorder(stream);
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.start();
      recorderRef.current = recorder;
    } catch {
      setError("Microphone access was blocked. Allow it in your browser settings.");
      setStatus("error");
      return;
    }

    if (Ctor) {
      const rec = new Ctor();
      rec.lang = navigator.language || "en-US";
      rec.continuous = true;
      rec.interimResults = true;

      rec.onresult = (e: any) => {
        let live = "";
        for (let i = e.resultIndex; i < e.results.length; i++) {
          const text = e.results[i][0].transcript;
          if (e.results[i].isFinal) finalRef.current += text;
          else live += text;
        }
        setInterim(live);
      };
      // A no-speech error isn't worth surfacing — the blob fallback covers it.
      rec.onerror = (e: any) => {
        if (e.error !== "no-speech" && e.error !== "aborted") {
          setError("Couldn't hear that clearly. Try again.");
        }
      };

      try {
        rec.start();
        recognitionRef.current = rec;
      } catch {
        recognitionRef.current = null;
      }
    }

    setStatus("recording");
    tickRef.current = setInterval(() => setSeconds((s) => s + 1), 1000);
  }, []);

  const stop = useCallback(async () => {
    if (status !== "recording") return;
    if (tickRef.current) clearInterval(tickRef.current);
    tickRef.current = null;

    recognitionRef.current?.stop();

    const recorder = recorderRef.current;
    const blob = await new Promise<Blob | null>((resolve) => {
      if (!recorder || recorder.state === "inactive") return resolve(null);
      recorder.onstop = () =>
        resolve(new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" }));
      recorder.stop();
    });

    // Give recognition a beat to flush its last final result.
    await new Promise((r) => setTimeout(r, 250));

    const spoken = (finalRef.current + " " + interim).trim();
    if (spoken) {
      teardown();
      setInterim("");
      setStatus("idle");
      onTranscript(spoken);
      return;
    }

    if (blob && blob.size > 0) {
      setStatus("transcribing");
      const text = await transcribeAudio(blob);
      teardown();
      setStatus("idle");
      if (text?.trim()) {
        onTranscript(text.trim());
      } else {
        setError("Couldn't transcribe that. Type it instead, or check /transcribe is running.");
      }
      return;
    }

    teardown();
    setStatus("idle");
    setError("Nothing was recorded.");
  }, [status, interim, onTranscript, teardown]);

  const cancel = useCallback(() => {
    recognitionRef.current?.abort();
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
    teardown();
    setInterim("");
    setSeconds(0);
    setStatus("idle");
  }, [teardown]);

  return { supported, status, interim, error, seconds, start, stop, cancel, setError };
}