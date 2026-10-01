// Runs a learner's JavaScript inside a Web Worker: no DOM, no access to the
// app's memory or storage, and the parent can terminate() it at any moment
// (that is what stops infinite loops). Network and worker APIs are removed
// before any learner code runs, and `postMessage` is shadowed so learner
// code cannot forge a result — only the bound `post` below can answer.
"use strict";
(function () {
  var post = self.postMessage.bind(self);
  ["fetch", "XMLHttpRequest", "WebSocket", "EventSource", "importScripts", "indexedDB", "caches",
    "BroadcastChannel", "SharedWorker", "Worker", "postMessage"].forEach(function (k) {
    try { Object.defineProperty(self, k, { value: undefined, writable: false, configurable: false }); } catch (e) {}
  });

  var MAX_OUT = 20000;
  var out = [];
  var outLen = 0;
  var silent = false;

  function show(v) {
    if (typeof v === "string") return v;
    if (v === undefined) return "undefined";
    try { return typeof v === "object" && v !== null ? JSON.stringify(v) : String(v); } catch (e) { return String(v); }
  }
  function write(prefix, args) {
    if (silent || outLen > MAX_OUT) return;
    var line = prefix + Array.prototype.map.call(args, show).join(" ");
    out.push(line);
    outLen += line.length + 1;
    if (outLen > MAX_OUT) out.push("…(output truncated)");
  }
  var shim = {
    log: function () { write("", arguments); },
    info: function () { write("", arguments); },
    debug: function () { write("", arguments); },
    warn: function () { write("[warn] ", arguments); },
    error: function () { write("[error] ", arguments); },
  };

  function deepEqual(a, b) {
    if (a === b) return true;
    if (typeof a === "number" && typeof b === "number") return Math.abs(a - b) < 1e-9;
    if (a === null || b === null || typeof a !== "object" || typeof b !== "object") return false;
    if (Array.isArray(a) !== Array.isArray(b)) return false;
    var ka = Object.keys(a), kb = Object.keys(b);
    if (ka.length !== kb.length) return false;
    for (var i = 0; i < ka.length; i++) {
      if (!Object.prototype.hasOwnProperty.call(b, ka[i]) || !deepEqual(a[ka[i]], b[ka[i]])) return false;
    }
    return true;
  }
  function parseExpected(s) {
    try { return { ok: true, value: JSON.parse(s) }; } catch (e) { return { ok: false, value: String(s).trim() }; }
  }
  function errText(e) {
    if (e && typeof e === "object" && e.name) return e.name + ": " + e.message;
    return String(e);
  }

  var AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;

  self.onmessage = async function (ev) {
    var d = ev.data || {};
    var res = { token: d.token, stdout: "", error: null, tests: [] };
    out = []; outLen = 0; silent = false;

    // 1) Run the whole program once, capturing its output.
    try {
      await new AsyncFunction("console", d.code)(shim);
    } catch (e) {
      res.error = errText(e);
    }
    res.stdout = out.join("\n");

    // 2) Tests. Each "call" test re-evaluates the learner's code plus one
    //    expression, with console muted so tests can't pollute the output.
    silent = true;
    var tests = d.tests || [];
    for (var i = 0; i < tests.length; i++) {
      var t = tests[i];
      var r = { name: t.name, passed: false, message: "" };
      try {
        if (t.type === "stdout") {
          if (res.error) throw new Error("your program stopped with an error, see the Errors tab");
          var want = String(t.expected).replace(/\r/g, "").trim();
          var got = res.stdout.replace(/\r/g, "").trim();
          r.passed = got === want;
          if (!r.passed) r.message = "expected output " + JSON.stringify(want) + " but got " + JSON.stringify(got);
        } else {
          var value = await new AsyncFunction("console", d.code + "\n;return (" + t.expr + ");")(shim);
          var exp = parseExpected(t.expected);
          r.passed = exp.ok ? deepEqual(value, exp.value) : show(value).trim() === exp.value;
          if (!r.passed) r.message = t.expr + " gave " + show(value) + " but should give " + t.expected;
        }
      } catch (e) {
        r.message = errText(e);
      }
      res.tests.push(r);
    }
    post(res);
  };
})();
