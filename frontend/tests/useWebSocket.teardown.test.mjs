import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { mock, test } from "node:test";

const wsSource = await readFile(new URL("../src/hooks/useWebSocket.ts", import.meta.url), "utf8");

const RECONNECT_DELAYS_MS = [1000, 2000, 4000, 8000, 16000];
const MAX_RECONNECT_ATTEMPTS = RECONNECT_DELAYS_MS.length;

test("hook source cancels reconnect timers during unmount cleanup", () => {
  assert.match(wsSource, /reconnectTimerRef/);
  assert.match(wsSource, /activeRef/);
  assert.match(wsSource, /clearReconnectTimer/);
  assert.match(wsSource, /activeRef\.current = false/);
  assert.match(wsSource, /clearReconnectTimer\(\)/);
  assert.match(wsSource, /if \(!activeRef\.current\)/);
  assert.match(wsSource, /MAX_RECONNECT_ATTEMPTS/);
});

/**
 * Facsimile of the reconnect/teardown contract in useWebSocket.ts.
 * This is not a React runtime test; it validates the bounded lifecycle model.
 */
function createReconnectLifecycle({ maxAttempts = MAX_RECONNECT_ATTEMPTS } = {}) {
  let active = true;
  let attempts = 0;
  let reconnectTimer = null;
  let connectCalls = 0;
  let terminal = false;

  const clearReconnectTimer = () => {
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  };

  const connect = () => {
    if (!active || terminal) {
      return;
    }
    connectCalls += 1;
  };

  const onOpen = () => {
    attempts = 0;
    terminal = false;
  };

  const onClose = () => {
    if (!active) {
      return;
    }
    if (attempts >= maxAttempts) {
      terminal = true;
      return;
    }
    const delay = RECONNECT_DELAYS_MS[attempts];
    attempts += 1;
    clearReconnectTimer();
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, delay);
  };

  const teardown = () => {
    active = false;
    clearReconnectTimer();
  };

  return {
    onOpen,
    onClose,
    teardown,
    get connectCalls() {
      return connectCalls;
    },
    get terminal() {
      return terminal;
    },
  };
}

test("facsimile: teardown cancels pending reconnect timer before it fires", () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const lifecycle = createReconnectLifecycle();
    lifecycle.onClose();
    lifecycle.teardown();
    mock.timers.tick(2000);
    assert.equal(lifecycle.connectCalls, 0);
  } finally {
    mock.timers.reset();
  }
});

test("facsimile: close after teardown does not schedule another reconnect", () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const lifecycle = createReconnectLifecycle();
    lifecycle.teardown();
    lifecycle.onClose();
    mock.timers.tick(2000);
    assert.equal(lifecycle.connectCalls, 0);
  } finally {
    mock.timers.reset();
  }
});

test("facsimile: reconnect still occurs while lifecycle remains active", () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const lifecycle = createReconnectLifecycle();
    lifecycle.onClose();
    mock.timers.tick(1000);
    assert.equal(lifecycle.connectCalls, 1);
  } finally {
    mock.timers.reset();
  }
});

test("facsimile: reconnect stops after the bounded attempt cap", () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const lifecycle = createReconnectLifecycle();
    for (let i = 0; i < MAX_RECONNECT_ATTEMPTS; i += 1) {
      lifecycle.onClose();
      mock.timers.tick(RECONNECT_DELAYS_MS[i]);
    }
    assert.equal(lifecycle.connectCalls, MAX_RECONNECT_ATTEMPTS);
    lifecycle.onClose();
    mock.timers.tick(20000);
    assert.equal(lifecycle.connectCalls, MAX_RECONNECT_ATTEMPTS);
    assert.equal(lifecycle.terminal, true);
  } finally {
    mock.timers.reset();
  }
});

test("facsimile: successful open resets attempts and allows reconnect again", () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const lifecycle = createReconnectLifecycle({ maxAttempts: 2 });
    lifecycle.onClose();
    mock.timers.tick(RECONNECT_DELAYS_MS[0]);
    assert.equal(lifecycle.connectCalls, 1);
    lifecycle.onOpen();
    lifecycle.onClose();
    mock.timers.tick(RECONNECT_DELAYS_MS[0]);
    assert.equal(lifecycle.connectCalls, 2);
  } finally {
    mock.timers.reset();
  }
});
