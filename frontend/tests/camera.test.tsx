import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AnnotationCanvas, nextPoint, type Handles } from "@/components/AnnotationCanvas";
import { CameraPanel } from "@/components/CameraPanel";
import { classifyCameraError } from "@/hooks/useCamera";

function fakeStream() {
  const track = { stop: vi.fn(), getSettings: () => ({ width: 1280, height: 720, deviceId: "cam-1" }), label: "USB Microscope", onended: null as null | (() => void) };
  return { track, stream: { getTracks: () => [track], getVideoTracks: () => [track] } };
}

function installMedia(getUserMedia: () => Promise<unknown>) {
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia: vi.fn(getUserMedia), enumerateDevices: vi.fn(async () => [{ kind: "videoinput", deviceId: "cam-1", label: "USB Microscope" }]), addEventListener: vi.fn(), removeEventListener: vi.fn() },
  });
}

beforeEach(() => {
  HTMLMediaElement.prototype.play = vi.fn(async () => undefined);
  Object.defineProperty(HTMLVideoElement.prototype, "videoWidth", { configurable: true, get: () => 1280 });
  Object.defineProperty(HTMLVideoElement.prototype, "videoHeight", { configurable: true, get: () => 720 });
  HTMLCanvasElement.prototype.getContext = vi.fn(() => ({ drawImage: vi.fn() })) as never;
  HTMLCanvasElement.prototype.toBlob = function (cb: BlobCallback) { cb(new Blob(["png"], { type: "image/png" })); };
  URL.createObjectURL = vi.fn(() => "blob:capture");
});

describe("camera error mapping", () => {
  it.each([["NotAllowedError", "denied"], ["NotFoundError", "no-camera"], ["NotReadableError", "busy"], ["Weird", "error"]])("%s -> %s", (name, status) => {
    expect(classifyCameraError({ name, message: "x" }).status).toBe(status);
  });
});

describe("CameraPanel", () => {
  it("does not start the camera without a user action", () => {
    installMedia(async () => fakeStream().stream);
    render(<CameraPanel onCapture={vi.fn()} />);
    expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled();
    expect(screen.getByText("Camera is off")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Capture & Analyse/ })).toBeDisabled();
  });

  it("shows a permission-denied state", async () => {
    installMedia(async () => { throw Object.assign(new Error("denied"), { name: "NotAllowedError" }); });
    render(<CameraPanel onCapture={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Start camera" }));
    expect(await screen.findByText("Permission denied")).toBeInTheDocument();
  });

  it("shows a no-camera state", async () => {
    installMedia(async () => { throw Object.assign(new Error("none"), { name: "NotFoundError" }); });
    render(<CameraPanel onCapture={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Start camera" }));
    expect(await screen.findByText("No camera found")).toBeInTheDocument();
  });

  it("reports an unsupported context when the camera API is missing", async () => {
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: undefined });
    render(<CameraPanel onCapture={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Start camera" }));
    expect(await screen.findByText("Camera not supported here")).toBeInTheDocument();
  });

  it("starts, captures a full-resolution frame, and stops tracks", async () => {
    const { stream, track } = fakeStream();
    installMedia(async () => stream);
    const onCapture = vi.fn();
    const { unmount } = render(<CameraPanel onCapture={onCapture} />);
    fireEvent.click(screen.getByRole("button", { name: "Start camera" }));
    expect(await screen.findByText("● Live")).toBeInTheDocument();
    expect(screen.getByText("1280×720")).toBeInTheDocument();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: /Capture & Analyse/ })));
    await waitFor(() => expect(onCapture).toHaveBeenCalled());
    const shot = onCapture.mock.calls[0][0];
    expect(shot).toMatchObject({ width: 1280, height: 720, source: "camera" });
    expect(shot.blob).toBeInstanceOf(Blob);
    fireEvent.click(screen.getByRole("button", { name: "Stop camera" }));
    expect(track.stop).toHaveBeenCalled();
    track.stop.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Start camera" }));
    await screen.findByText("● Live");
    unmount();
    expect(track.stop).toHaveBeenCalled();  // leaving the page releases the camera
  });
});

describe("AnnotationCanvas manual correction", () => {
  it("moves a focused handle with the keyboard and reports the corrected geometry", () => {
    const handles: Handles = { baseline: [[10, 100], [300, 100]], contact_left: [100, 100], contact_right: [200, 100] };
    const onChange = vi.fn();
    render(<AnnotationCanvas src="blob:x" width={320} height={200} handles={handles} onHandlesChange={onChange} mode="auto" roi={null} roiDrawing={false} />);
    const left = screen.getByRole("button", { name: /Left contact point at x 100, y 100/ });
    fireEvent.keyDown(left, { key: "ArrowRight" });
    expect(onChange).toHaveBeenLastCalledWith({ ...handles, contact_left: [101, 100] });
    fireEvent.keyDown(screen.getByRole("button", { name: /Baseline point 2/ }), { key: "ArrowUp", shiftKey: true });
    expect(onChange).toHaveBeenLastCalledWith({ ...handles, baseline: [[10, 100], [300, 90]] });
    expect(screen.queryByRole("button", { name: /tangent point/ })).not.toBeInTheDocument();
  });

  it("exposes tangent handles only in manual tangent mode", () => {
    const handles: Handles = { baseline: [[10, 100], [300, 100]], contact_left: [100, 100], contact_right: [200, 100], tangent_left: [120, 60], tangent_right: [180, 60] };
    render(<AnnotationCanvas src="blob:x" width={320} height={200} handles={handles} onHandlesChange={vi.fn()} mode="manual_tangent" roi={null} roiDrawing={false} />);
    expect(screen.getAllByRole("button", { name: /tangent point/ })).toHaveLength(2);
  });
});

describe("three-point placement", () => {
  it("places start, end and top in order from clicks and then stops placing", () => {
    let h: Handles = { baseline: [[0, 0], [320, 0]] };
    const onChange = vi.fn((n: Handles) => { h = n; });
    const view = render(<AnnotationCanvas src="blob:x" width={320} height={200} handles={h} onHandlesChange={onChange} mode="three_point" roi={null} roiDrawing={false} />);
    const svg = view.container.querySelector("svg")!;
    svg.getBoundingClientRect = () => ({ left: 0, top: 0, width: 320, height: 200 }) as DOMRect;
    const click = (x: number, y: number) => {
      fireEvent.pointerDown(svg, { clientX: x, clientY: y });
      view.rerender(<AnnotationCanvas src="blob:x" width={320} height={200} handles={h} onHandlesChange={onChange} mode="three_point" roi={null} roiDrawing={false} />);
    };
    click(100, 150);
    expect(nextPoint(h)?.step).toBe(2);
    click(220, 150);
    click(160, 90);
    expect(h).toMatchObject({ contact_left: [100, 150], contact_right: [220, 150], apex: [160, 90] });
    expect(nextPoint(h)).toBeNull();
    click(10, 10);
    expect(onChange).toHaveBeenCalledTimes(3);
  });
});

