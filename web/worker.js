// Runs Pyodide and the shuffle_solver package off the main thread.
// Messages in:  {id, op, args}   Messages out: {id, result} or {id, error}
// plus {type: "progress", text} while starting up.

const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.27.2/full/";
importScripts(PYODIDE + "pyodide.js");

const say = (text) => postMessage({ type: "progress", text });

async function start() {
  say("Starting Python…");
  const py = await loadPyodide({ indexURL: PYODIDE });
  say("Loading numpy…");
  const [, zip] = await Promise.all([
    py.loadPackage("numpy"),
    fetch("py/solver.zip").then((r) => {
      if (!r.ok) throw new Error(`solver.zip: HTTP ${r.status}`);
      return r.arrayBuffer();
    }),
  ]);
  say("Loading the solver…");
  py.unpackArchive(zip, "zip", { extractDir: "/home/pyodide/app" });
  py.runPython("import sys; sys.path.insert(0, '/home/pyodide/app')");
  return py.pyimport("webbridge").handle;
}

const ready = start();
ready.then(
  // The files it loaded, so the service worker can keep them for offline use
  // (on a first visit it isn't in control yet, so it didn't see them go by).
  () => postMessage({
    type: "ready",
    resources: performance.getEntriesByType("resource").map((e) => e.name),
  }),
  (err) => postMessage({ type: "failed", text: String(err && err.message || err) }),
);

onmessage = async (event) => {
  const { id, op, args } = event.data;
  try {
    const handle = await ready;
    postMessage({ id, result: JSON.parse(handle(op, JSON.stringify(args || {}))) });
  } catch (err) {
    postMessage({ id, error: String(err && err.message || err) });
  }
};
