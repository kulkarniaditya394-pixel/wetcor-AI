/* WETCOR AI in-browser analysis engine (ES-module web worker).
 * Loads Pyodide (Python for WebAssembly) from the jsDelivr CDN, the scientific packages it needs, and the WETCOR
 * analysis code from ./app.zip, then answers {id, fn, args, blob} requests. Files never leave the browser. */
import { loadPyodide } from "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/pyodide.mjs";

const PYODIDE_VERSION = "v314.0.7";
const PYODIDE_URL = "https://cdn.jsdelivr.net/pyodide/" + PYODIDE_VERSION + "/full/";
const PACKAGES = ["numpy", "scipy", "pandas", "opencv-python"];

const post = (msg) => self.postMessage(msg);
let engine = null;

async function init() {
  post({ type: "progress", stage: 1, of: 4, message: "Downloading the Python runtime" });
  const pyodide = await loadPyodide({ indexURL: PYODIDE_URL });
  post({ type: "progress", stage: 2, of: 4, message: "Loading NumPy, SciPy, pandas and OpenCV (largest download, cached afterwards)" });
  await pyodide.loadPackage(PACKAGES);
  post({ type: "progress", stage: 3, of: 4, message: "Loading the WETCOR analysis code" });
  const zip = await (await fetch(new URL("app.zip", self.location.href))).arrayBuffer();
  pyodide.unpackArchive(zip, "zip");
  engine = pyodide.pyimport("app.browser_engine");
  post({ type: "progress", stage: 4, of: 4, message: "Ready" });
  post({ type: "ready", python: pyodide.version });
}

const ready = init().catch((err) => {
  post({ type: "error", message: String((err && err.message) || err) });
  throw err;
});

self.onmessage = async (e) => {
  const { id, fn, args, blob } = e.data;
  try {
    await ready;
    const raw = engine.dispatch(fn, JSON.stringify(args || {}), blob ? new Uint8Array(blob) : undefined);
    post({ type: "result", id, response: JSON.parse(raw) });
  } catch (err) {
    post({ type: "result", id, response: { ok: false, status: 500, detail: "Analysis engine unavailable: " + String((err && err.message) || err) } });
  }
};
