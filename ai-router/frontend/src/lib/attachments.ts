/**
 * Attachment pipeline: authorize → pick → downscale → upload → reference.
 *
 * Phones produce 4-12MB photos. Sending those raw is the single biggest
 * cause of a slow-feeling chat, so everything is re-encoded to a bounded
 * JPEG before it leaves the device. The model gets no benefit from more
 * than ~1568px on the long edge, which is also the cap most vision APIs
 * downscale to server-side anyway.
 */
import { supabase } from "./supabase";

const BASE = import.meta.env.VITE_AI_BACKEND_URL;

export const MAX_EDGE = 1568;
export const JPEG_QUALITY = 0.82;
/** Refuse anything absurd before we bother decoding it. */
export const MAX_INPUT_BYTES = 25 * 1024 * 1024;

export interface Attachment {
  type: "image";
  /** Public URL in Supabase Storage — what gets persisted on the message. */
  url: string;
  /** Data URL, kept in memory for the current request only. */
  dataUrl?: string;
  mime: string;
  width: number;
  height: number;
  bytes: number;
  name: string;
}

/**
 * Server-side quota check — the ONLY place an image upload actually
 * counts against the user's daily limit (see backend's
 * POST /images/authorize + access/image_policy.py). Runs before any
 * compression or Storage upload, so a rejected upload never burns
 * bandwidth and never touches Storage.
 */
async function authorizeUpload(userId: string): Promise<void> {
  if (!BASE) return; // backend not configured — let it through (dev/placeholder mode)

  const resp = await fetch(`${BASE}/images/authorize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId }),
  });

  if (resp.status === 429) {
    const data = await resp.json().catch(() => ({}));
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "You've reached today's image upload limit.",
    );
  }
  if (!resp.ok) {
    throw new Error("Couldn't verify your image upload quota. Try again.");
  }
}

function loadImage(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve(img);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("That file couldn't be read as an image."));
    };
    img.src = url;
  });
}

/** Downscale to fit MAX_EDGE and re-encode as JPEG. Returns a data URL. */
export async function compressImage(file: File): Promise<{
  dataUrl: string;
  width: number;
  height: number;
  bytes: number;
}> {
  if (file.size > MAX_INPUT_BYTES) {
    throw new Error("That image is too large. Try one under 25MB.");
  }

  const img = await loadImage(file);
  const scale = Math.min(1, MAX_EDGE / Math.max(img.width, img.height));
  const width = Math.round(img.width * scale);
  const height = Math.round(img.height * scale);

  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Couldn't process that image on this device.");
  // White matte: JPEG has no alpha, and transparent PNGs otherwise come
  // out with black backgrounds that confuse the model.
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, width, height);
  ctx.drawImage(img, 0, 0, width, height);

  const dataUrl = canvas.toDataURL("image/jpeg", JPEG_QUALITY);
  const bytes = Math.round((dataUrl.length - dataUrl.indexOf(",") - 1) * 0.75);
  return { dataUrl, width, height, bytes };
}

function dataUrlToBlob(dataUrl: string): Blob {
  const [head, b64] = dataUrl.split(",");
  const mime = head.match(/:(.*?);/)?.[1] ?? "image/jpeg";
  const bin = atob(b64);
  const buf = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
  return new Blob([buf], { type: mime });
}

/**
 * Authorize against the daily quota, compress, then store in the
 * `attachments` bucket under the user's own folder so row-level
 * policies can scope access by path prefix.
 */
export async function prepareImage(file: File, userId: string): Promise<Attachment> {
  await authorizeUpload(userId);

  const { dataUrl, width, height, bytes } = await compressImage(file);
  const path = `${userId}/${crypto.randomUUID()}.jpg`;

  const { error } = await supabase.storage
    .from("attachments")
    .upload(path, dataUrlToBlob(dataUrl), { contentType: "image/jpeg", upsert: false });

  if (error) {
    // Storage isn't configured yet — still let the send go through with the
    // inline data URL so image chat works before the bucket exists.
    return {
      type: "image",
      url: "",
      dataUrl,
      mime: "image/jpeg",
      width,
      height,
      bytes,
      name: file.name,
    };
  }

  const { data } = supabase.storage.from("attachments").getPublicUrl(path);
  return {
    type: "image",
    url: data.publicUrl,
    dataUrl,
    mime: "image/jpeg",
    width,
    height,
    bytes,
    name: file.name,
  };
}