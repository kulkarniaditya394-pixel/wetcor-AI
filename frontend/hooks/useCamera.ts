"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type CameraStatus = "idle" | "requesting" | "live" | "denied" | "no-camera" | "busy" | "unsupported" | "disconnected" | "error";
export type Capture = { blob: Blob; url: string; width: number; height: number; capturedAt: string; deviceLabel: string };

export const RESOLUTIONS = [
  { label: "640 × 480", w: 640, h: 480 },
  { label: "1280 × 720", w: 1280, h: 720 },
  { label: "1920 × 1080", w: 1920, h: 1080 },
  { label: "2592 × 1944", w: 2592, h: 1944 },
];

export function classifyCameraError(err: unknown): { status: CameraStatus; message: string } {
  const name = (err as { name?: string })?.name;
  if (name === "NotAllowedError" || name === "SecurityError")
    return { status: "denied", message: "Camera permission was denied. Allow camera access for this localhost page in the browser's site settings, then press Start camera again." };
  if (name === "NotFoundError" || name === "OverconstrainedError" || name === "DevicesNotFoundError")
    return { status: "no-camera", message: "No camera matching the selection was found. Connect the USB camera, wait a few seconds, then press Refresh devices." };
  if (name === "NotReadableError" || name === "TrackStartError" || name === "AbortError")
    return { status: "busy", message: "The camera is in use by another application (Camera app, Teams, Zoom, OBS…). Close it, then press Start camera again." };
  return { status: "error", message: `Camera could not be started: ${(err as Error)?.message || String(err)}` };
}

/** Browser camera via getUserMedia. Never starts without an explicit call to start(); tracks are stopped on unmount. */
export function useCamera() {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [status, setStatus] = useState<CameraStatus>("idle");
  const [message, setMessage] = useState<string>("");
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [deviceId, setDeviceId] = useState<string>("");
  const [resolution, setResolution] = useState(RESOLUTIONS[1]);
  const [actual, setActual] = useState<{ width?: number; height?: number; label?: string }>({});

  const refreshDevices = useCallback(async () => {
    if (!navigator.mediaDevices?.enumerateDevices) return [];
    const list = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "videoinput");
    setDevices(list);
    return list;
  }, []);

  const stop = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setStatus((s) => (s === "live" || s === "requesting" ? "idle" : s));
  }, []);

  const start = useCallback(
    async (id = deviceId, res = resolution) => {
      if (!navigator.mediaDevices?.getUserMedia) {
        setStatus("unsupported");
        setMessage("Camera API unavailable. Open WETCOR AI at http://localhost:3100 (not a file:// path) in a current Chrome, Edge or Firefox.");
        return;
      }
      streamRef.current?.getTracks().forEach((t) => t.stop());
      setStatus("requesting");
      setMessage("");
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: false,
          video: { deviceId: id ? { exact: id } : undefined, width: { ideal: res.w }, height: { ideal: res.h } },
        });
        streamRef.current = stream;
        const track = stream.getVideoTracks()[0];
        const s = track.getSettings();
        setActual({ width: s.width, height: s.height, label: track.label });
        if (s.deviceId) setDeviceId(s.deviceId);
        track.onended = () => {
          setStatus("disconnected");
          setMessage("The camera stream ended (device unplugged or taken by another app). Reconnect it and press Start camera.");
        };
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play().catch(() => undefined);
        }
        setStatus("live");
        refreshDevices();
      } catch (err) {
        const c = classifyCameraError(err);
        setStatus(c.status);
        setMessage(c.message);
      }
    },
    [deviceId, resolution, refreshDevices],
  );

  const capture = useCallback(async (): Promise<Capture | null> => {
    const v = videoRef.current;
    if (!v || status !== "live" || !v.videoWidth) return null;
    const canvas = document.createElement("canvas");
    canvas.width = v.videoWidth;
    canvas.height = v.videoHeight;
    canvas.getContext("2d")!.drawImage(v, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob | null>((r) => canvas.toBlob(r, "image/png"));
    if (!blob) return null;
    return { blob, url: URL.createObjectURL(blob), width: canvas.width, height: canvas.height, capturedAt: new Date().toISOString(), deviceLabel: actual.label || "camera" };
  }, [status, actual.label]);

  useEffect(() => {
    refreshDevices();
    const md = navigator.mediaDevices;
    md?.addEventListener?.("devicechange", refreshDevices);
    return () => {
      md?.removeEventListener?.("devicechange", refreshDevices);
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, [refreshDevices]);

  return { videoRef, status, message, devices, deviceId, setDeviceId, resolution, setResolution, actual, start, stop, capture, refreshDevices };
}
