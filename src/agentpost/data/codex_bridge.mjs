import { execFile } from "node:child_process";
import { appendFileSync, mkdirSync, renameSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

const options = parseArgs(process.argv.slice(2));
mkdirSync(dirname(options.log), { recursive: true });
writeFileSync(options.log, "");
const socket = new WebSocket(options.url);
let requestId = 0;
const requests = new Map();
let threadId = null;
let turnId = null;
let active = false;
let known = new Set();
let deferred = new Set();
let pollRunning = false;

socket.addEventListener("open", async () => {
  try {
    await request("initialize", {
      clientInfo: { name: "agentpost", title: "AgentPost", version: "0.0.9" },
      capabilities: {
        experimentalApi: true,
        requestAttestation: false,
        optOutNotificationMethods: [],
      },
    });
    notify("initialized");
    threadId = await waitForLoadedThread();
    trace("attached", { threadId });
    writePresence("idle");
    setInterval(poll, 250).unref();
    setInterval(() => writePresence(active ? "working" : "idle"), 1000).unref();
    await poll();
    process.stderr.write(`agentpost: Codex mailbox bridge attached to ${options.agent}\n`);
  } catch (error) {
    fail(error);
  }
});

socket.addEventListener("message", (event) => {
  let message;
  try {
    message = JSON.parse(String(event.data));
  } catch {
    return;
  }
  if (message.id !== undefined && requests.has(message.id)) {
    const pending = requests.get(message.id);
    requests.delete(message.id);
    if (message.error) pending.reject(new Error(JSON.stringify(message.error)));
    else pending.resolve(message.result);
    return;
  }
  const params = message.params || {};
  if (params.threadId && threadId && params.threadId !== threadId) return;
  if (message.method === "turn/started") {
    active = true;
    writePresence("working");
    turnId = params.turn?.id || params.turnId || null;
    trace("turn-started", { turnId, params });
  } else if (
    message.method === "turn/completed" ||
    message.method === "turn/failed"
  ) {
    trace("turn-ended", { method: message.method });
    onIdle();
  } else if (message.method === "thread/status/changed") {
    trace("status", params);
    if (params.status?.type === "active") {
      active = true;
      writePresence("working");
      refreshTurnId();
    }
    if (params.status?.type === "idle") onIdle();
  }
});

socket.addEventListener("close", () => process.exit(0));
socket.addEventListener("error", () => fail(new Error("app-server connection failed")));

async function poll() {
  if (pollRunning || !threadId || socket.readyState !== WebSocket.OPEN) return;
  pollRunning = true;
  try {
    const messages = await snapshot();
    const current = new Set(messages.map((item) => item.message_id));
    known = new Set([...known].filter((id) => current.has(id)));
    deferred = new Set([...deferred].filter((id) => current.has(id)));
    for (const item of messages) {
      if (known.has(item.message_id)) continue;
      known.add(item.message_id);
      if (active && item.notify === "idle") {
        deferred.add(item.message_id);
        trace("deferred-idle", { messageId: item.message_id });
      } else {
        await deliver([item.message_id], item.notify);
      }
    }
  } catch (error) {
    process.stderr.write(`agentpost: Codex mailbox poll failed: ${error.message}\n`);
  } finally {
    pollRunning = false;
  }
}

async function refreshTurnId() {
  try {
    const response = await request("thread/read", {
      threadId,
      includeTurns: true,
    });
    const turns = response?.thread?.turns || [];
    const latest = turns[turns.length - 1];
    if (latest?.id) turnId = latest.id;
    trace("turn-id-refreshed", { turnId, turnCount: turns.length });
  } catch (error) {
    trace("turn-id-refresh-failed", { error: error.message });
  }
}

async function deliver(ids, mode) {
  const text =
    `AgentPost ${mode} mail is waiting for ${options.agent}: ${ids.join(", ")}. ` +
    "Load the agentpost skill and process exactly the listed Message-ID(s). Do not " +
    "list, read, claim, or process any other unread mail during this turn; other " +
    "messages may be intentionally deferred. Read and claim each listed message " +
    "only when starting it, reply by Message-ID when appropriate, and give the " +
    "user a short synopsis.";
  const input = [{ type: "text", text, text_elements: [] }];
  if (active && turnId && mode === "immediate") {
    try {
      await request("turn/steer", {
        threadId,
        expectedTurnId: turnId,
        input,
      });
      trace("steered", { ids, turnId });
      return;
    } catch {
      deferred = new Set([...deferred, ...ids]);
      trace("steer-deferred", { ids, turnId });
      return;
    }
  }
  if (active) {
    deferred = new Set([...deferred, ...ids]);
    trace("active-deferred", { ids, mode, turnId });
    return;
  }
  active = true;
  writePresence("working");
  const result = await request("turn/start", {
    threadId,
    input,
    cwd: options.cwd,
    runtimeWorkspaceRoots: [options.cwd],
  });
  turnId = result?.turn?.id || null;
  trace("turn-start-request", { ids, mode, turnId });
}

async function onIdle() {
  if (!active && deferred.size === 0) return;
  active = false;
  writePresence("idle");
  turnId = null;
  if (deferred.size) {
    const ids = [...deferred];
    deferred.clear();
    try {
      await deliver(ids, "idle");
    } catch (error) {
      process.stderr.write(`agentpost: deferred Codex delivery failed: ${error.message}\n`);
      ids.forEach((id) => deferred.add(id));
    }
  }
}

async function waitForLoadedThread() {
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    const response = await request("thread/loaded/list", {});
    if (Array.isArray(response?.data) && response.data.length) return response.data[0];
    await sleep(250);
  }
  throw new Error("no Codex TUI thread loaded within 30 seconds");
}

function snapshot() {
  return new Promise((resolve, reject) => {
    execFile(
      "agentpost",
      ["--root", options.root, "internal-snapshot", options.agent],
      { cwd: options.cwd, encoding: "utf8", timeout: 5000 },
      (error, stdout, stderr) => {
        if (error) reject(new Error(stderr.trim() || error.message));
        else {
          try {
            resolve(JSON.parse(stdout));
          } catch (parseError) {
            reject(parseError);
          }
        }
      },
    );
  });
}

function request(method, params) {
  const id = ++requestId;
  socket.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      requests.delete(id);
      reject(new Error(`${method} timed out`));
    }, 30000);
    requests.set(id, {
      resolve: (value) => { clearTimeout(timer); resolve(value); },
      reject: (error) => { clearTimeout(timer); reject(error); },
    });
  });
}

function notify(method, params = {}) {
  socket.send(JSON.stringify({ method, params }));
}

function parseArgs(args) {
  const parsed = {};
  for (let index = 0; index < args.length; index += 2) {
    parsed[args[index].replace(/^--/, "")] = args[index + 1];
  }
  for (const key of ["url", "agent", "root", "cwd", "log", "presence", "ownerPid", "instanceId"]) {
    if (!parsed[key]) throw new Error(`missing --${key}`);
  }
  return parsed;
}

function writePresence(state) {
  const temporary = `${options.presence}.${process.pid}.tmp`;
  writeFileSync(
    temporary,
    JSON.stringify({
      pid: Number(options.ownerPid),
      updated_at: Date.now() / 1000,
      state,
      instance_id: options.instanceId,
      adapter: "codex",
    }),
  );
  renameSync(temporary, options.presence);
}

function trace(event, details = {}) {
  appendFileSync(
    options.log,
    `${new Date().toISOString()} ${event} ${JSON.stringify(details)}\n`,
  );
}

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function fail(error) {
  process.stderr.write(`agentpost: Codex mailbox bridge stopped: ${error.message}\n`);
  process.exit(1);
}
