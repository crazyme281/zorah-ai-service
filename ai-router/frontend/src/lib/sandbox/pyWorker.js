// Runs a learner's Python via Pyodide (CPython compiled to WebAssembly)
// inside a Web Worker, so an infinite loop can be terminate()d without
// freezing the app. Pyodide (~10 MB) downloads once from jsDelivr and is
// then cached by the browser. After loading, network, worker and storage
// APIs are removed and `postMessage` is shadowed so learner code cannot
// forge a result.
"use strict";
(function () {
  var post = self.postMessage.bind(self);
  var BASE = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/";
  var HARNESS = __PY_HARNESS__;

  var ready = (async function () {
    importScripts(BASE + "pyodide.js");
    var py = await loadPyodide({ indexURL: BASE });
    py.runPython(HARNESS);
    ["fetch", "XMLHttpRequest", "WebSocket", "EventSource", "importScripts", "indexedDB", "caches",
      "BroadcastChannel", "SharedWorker", "Worker", "postMessage"].forEach(function (k) {
      try { Object.defineProperty(self, k, { value: undefined, writable: false, configurable: false }); } catch (e) {}
    });
    post({ type: "ready" });
    return py;
  })().catch(function (e) {
    post({ type: "fatal", error: String((e && e.message) || e) });
    return null;
  });

  self.onmessage = async function (ev) {
    var d = ev.data || {};
    var py = await ready;
    if (!py) return;
    try {
      var raw = py.globals.get("_zorah_run")(d.code, JSON.stringify(d.tests || []));
      var res = JSON.parse(raw);
      res.token = d.token;
      res.type = "result";
      post(res);
    } catch (e) {
      post({ type: "result", token: d.token, stdout: "", error: String((e && e.message) || e), tests: [] });
    }
  };
})();
