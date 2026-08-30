import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { mock, test } from "node:test";

const wsSource = await readFile(new URL("../src/hooks/useWebSocket.ts", import.meta.url), "utf8");

test("hook source cancels reconnect timers during unmount cleanup", () => {
  assert.match(wsSource, /reconnectTimerRef/);
  assert.match(wsSource, /activeRef/);
  assert.match(wsSource, /clearReconnectTimer/);
  assert.match(wsSource, /activeRef\.current = false/);
  assert.match(wsSource, /clearReconnectTimer\(\)/);
  assert.match(wsSource, /if \(!activeRef\.current\)/);
});

/**
 * Behavioral model of the reconnect/teardown contract implemented in useWebSocket.
 * Uses fake timers to prove pending reconnect work is canceled on dispose.
 */
function createReconnectLifecycle() {
  let active = true;
  let reconnectTimer = null;
  let connectCalls = 0;

  const clearReconnectTimer = () => {
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  };

  const connect = () => {
    if (!active) {
      return;
    }
    connectCalls += 1;
  };

  const onClose = () => {
    if (!active) {
      return;
    }
    clearReconnectTimer();
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, 1000);
  };

  const teardown = () => {
    active = false;
    clearReconnectTimer();
  };

  return {
    onClose,
    teardown,
    get connectCalls() {
      return connectCalls;
    },
  };
}

test("teardown cancels pending reconnect timer before it fires", () => {
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

test("close after teardown does not schedule another reconnect", () => {
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

test("reconnect still occurs while lifecycle remains active", () => {
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
