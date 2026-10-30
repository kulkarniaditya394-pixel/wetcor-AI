"use client";

import { Camera, CameraOff, ImageUp, Power, RefreshCw } from "lucide-react";
import { useId, useRef } from "react";
import { RESOLUTIONS, useCamera, type Capture } from "@/hooks/useCamera";
import { Alert, Badge, Button, Field, Select } from "./ui";

export function CameraPanel({ onCapture, busy }: { onCapture: (c: Capture & { source: "camera" | "upload"; filename: string }) => void; busy?: boolean }) {
  const cam = useCamera();
  const fileRef = useRef<HTMLInputElement>(null);
  const devId = useId();
  const resId = useId();
  const live = cam.status === "live";

  const upload = async (file: File) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => onCapture({ blob: file, url, width: img.naturalWidth, height: img.naturalHeight, capturedAt: new Date(file.lastModified).toISOString(),
      deviceLabel: "uploaded file", source: "upload", filename: file.name });
    img.onerror = () => alert("This file could not be read as an image.");
    img.src = url;
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="relative aspect-video w-full overflow-hidden rounded-lg border border-line bg-black">
        <video ref={cam.videoRef} className={live ? "h-full w-full object-contain" : "hidden"} playsInline muted aria-label="Live camera preview" />
        {!live && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center">
            <CameraOff className="size-10 text-muted" aria-hidden />
            <div className="text-sm font-semibold text-ink">
              {cam.status === "requesting" ? "Waiting for camera permission…" : cam.status === "idle" ? "Camera is off" : "Camera unavailable"}
            </div>
            <p className="max-w-md text-xs text-muted">
              {cam.status === "idle" ? "Start the camera to see a live preview. The browser will ask for permission; video stays in this browser and is only sent to the local backend when you capture a frame." : cam.message}
            </p>
          </div>
        )}
        {live && (
          <div className="absolute left-2 top-2 flex gap-1.5">
            <Badge tone="good">● Live</Badge>
            <Badge>{cam.actual.width}×{cam.actual.height}</Badge>
          </div>
        )}
        {live && <div className="pointer-events-none absolute inset-x-0 top-1/2 h-px bg-accent/25" aria-hidden />}
      </div>

      {cam.status !== "idle" && cam.status !== "live" && cam.status !== "requesting" && (
        <Alert tone={cam.status === "denied" || cam.status === "unsupported" ? "bad" : "warn"} title={{ denied: "Permission denied", "no-camera": "No camera found", busy: "Camera busy",
          unsupported: "Camera not supported here", disconnected: "Camera disconnected", error: "Camera error" }[cam.status as string]}>{cam.message}</Alert>
      )}

      <div className="grid gap-3 sm:grid-cols-[1fr_180px]">
        <Field label="Camera device" htmlFor={devId} hint={cam.devices.length && !cam.devices[0].label ? "Device names appear after camera permission is granted." : undefined}>
          <Select id={devId} value={cam.deviceId} onChange={(e) => { cam.setDeviceId(e.target.value); if (live) cam.start(e.target.value); }}>
            <option value="">{cam.devices.length ? "Default camera" : "No cameras listed"}</option>
            {cam.devices.map((d, i) => <option key={d.deviceId || i} value={d.deviceId}>{d.label || `Camera ${i + 1}`}</option>)}
          </Select>
        </Field>
        <Field label="Requested resolution" htmlFor={resId} hint={live ? `Delivered: ${cam.actual.width}×${cam.actual.height}` : undefined}>
          <Select id={resId} value={cam.resolution.label} onChange={(e) => { const r = RESOLUTIONS.find((x) => x.label === e.target.value)!; cam.setResolution(r); if (live) cam.start(cam.deviceId, r); }}>
            {RESOLUTIONS.map((r) => <option key={r.label}>{r.label}</option>)}
          </Select>
        </Field>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {live ? (
          <Button variant="secondary" icon={<Power className="size-4" />} onClick={cam.stop}>Stop camera</Button>
        ) : (
          <Button variant="secondary" icon={<Power className="size-4" />} busy={cam.status === "requesting"} onClick={() => cam.start()}>Start camera</Button>
        )}
        <Button variant="ghost" size="sm" icon={<RefreshCw className="size-3.5" />} onClick={cam.refreshDevices}>Refresh devices</Button>
        <div className="flex-1" />
        <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/bmp,image/tiff" className="hidden" aria-label="Upload droplet image"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); e.target.value = ""; }} />
        <Button variant="ghost" icon={<ImageUp className="size-4" />} onClick={() => fileRef.current?.click()}>Upload image</Button>
        <Button variant="primary" size="lg" icon={<Camera className="size-5" />} disabled={!live} busy={busy}
          onClick={async () => { const c = await cam.capture(); if (c) onCapture({ ...c, source: "camera", filename: `capture_${c.capturedAt.replace(/[:.]/g, "-")}.png` }); }}>
          Capture &amp; Analyse
        </Button>
      </div>
    </div>
  );
}
