import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import test from 'node:test';
import { setTimeout as delay } from 'node:timers/promises';

const demo = process.argv[2];
const init = '{"type":"init","participantId":"test-cpp"}\r\n';

function start(t, ...args) {
  const child = spawn(demo, args, { stdio: ['pipe', 'pipe', 'pipe'] });
  let stdout = '';
  let stderr = '';
  child.stdin.on('error', error => {
    if (error.code !== 'EPIPE' && error.code !== 'ERR_STREAM_DESTROYED') throw error;
  });
  child.stdout.setEncoding('utf8').on('data', chunk => { stdout += chunk; });
  child.stderr.setEncoding('utf8').on('data', chunk => { stderr += chunk; });
  const lines = createInterface({ input: child.stdout })[Symbol.asyncIterator]();
  const done = new Promise((resolve, reject) => {
    child.once('error', reject);
    child.once('close', (code, signal) => resolve({ code, signal }));
  });
  t.after(() => {
    if (child.exitCode === null && child.signalCode === null) child.kill();
  });
  return {
    child, done,
    send: bytes => child.stdin.write(bytes),
    ack: (action, revision = 42) =>
      child.stdin.write(JSON.stringify({ type: 'ack', action, revision }) + '\n'),
    async next(action) {
      const { value, done } = await lines.next();
      assert.equal(done, false, stderr);
      const event = JSON.parse(value);
      assert.equal(event.type, action);
      assert.equal(Object.hasOwn(event, 'participantId'), false);
      return event;
    },
    async expectExit(code, expectedLines, diagnostic) {
      assert.deepEqual(await done, { code, signal: null }, stderr);
      assert.equal(stdout.split('\n').length - 1, expectedLines, stdout);
      assert.equal(stdout.includes('\r'), false, stdout);
      if (diagnostic) assert.match(stderr, diagnostic);
      else assert.equal(stderr, '');
    },
  };
}

for (const reset of [false, true]) {
  test(`successful run with reset=${reset} waits for final ack`, { timeout: 8000 }, async t => {
    const run = start(t, ...(reset ? ['--reset-on-start'] : []));
    run.send(init);
    if (reset) {
      assert.deepEqual(await run.next('reset'), { type: 'reset' });
      run.ack('reset', 4);
    }
    const first = await run.next('acquire');
    run.ack('acquire', 10);
    const released = await run.next('release');
    assert.equal(released.poolSlotId, first.poolSlotId);
    assert.equal(released.generation, 1);
    run.ack('release', 42);
    const last = await run.next('acquire');
    assert.equal(last.poolSlotId, first.poolSlotId);
    assert.equal(last.generation, 2);
    assert.deepEqual(last.data, { name: '별 🌟', type: 'planet', color: '#a78bfa', size: 1.6 });
    assert.equal(await Promise.race([run.done, delay(60, 'pending')]), 'pending');
    run.ack('acquire', Number.MAX_SAFE_INTEGER);
    await run.expectExit(0, reset ? 4 : 3);
  });
}

for (const [name, reply, diagnostic] of [
  ['mismatched action', '{"type":"ack","action":"release","revision":1}\n', /matching ack/],
  ['invalid revision', '{"type":"ack","action":"acquire","revision":9007199254740992}\n', /matching ack/],
  ['fractional revision', '{"type":"ack","action":"acquire","revision":1.5}\n', /matching ack/],
  ['explicit relay rejection', '{"type":"error","message":"slot unavailable"}\n', /remote rejection.*slot unavailable/],
  ['malformed JSON', '{bad}\n', /invalid UTF-8 JSON/],
  ['invalid UTF-8', Buffer.from([0x22, 0xff, 0x22, 0x0a]), /invalid UTF-8 JSON/],
  ['raw NUL', '{"type":"ack","action":"acquire","revision":1}\0hidden\n', /invalid UTF-8 JSON/],
  ['oversized line', 'x'.repeat(8001), /exceeds 8000 bytes/],
  ['duplicate init', init, /matching ack/],
  ['early EOF', null, /EOF/],
  ['stalled reply', undefined, /timed out/],
]) {
  test(name, { timeout: 8000 }, async t => {
    const run = start(t, ...(reply === undefined ? ['--test-short-timeouts'] : []));
    run.send(init);
    await run.next('acquire');
    if (reply === null) run.child.stdin.end();
    else if (reply !== undefined) run.send(reply);
    await run.expectExit(1, 1, diagnostic);
  });
}

for (const [name, bytes, diagnostic] of [
  ['invalid participant', '{"type":"init","participantId":"bad id"}\n', /valid participantId/],
  ['unsolicited ack', init + '{"type":"ack","action":"acquire","revision":1}\n', /unsolicited/],
  ['unterminated init', init.trim(), /unterminated JSONL/],
  ['init timeout', undefined, /init: timed out/],
]) {
  test(name, { timeout: 8000 }, async t => {
    const run = start(t, ...(bytes === undefined ? ['--test-short-timeouts'] : []));
    if (bytes !== undefined) run.child.stdin.end(bytes);
    await run.expectExit(1, 0, diagnostic);
  });
}

test('runner paces serialized events', { timeout: 8000 }, async t => {
  const run = start(t);
  const startTime = performance.now();
  run.send(init);
  await run.next('acquire');
  run.ack('acquire');
  await run.next('release');
  run.ack('release');
  await run.next('acquire');
  // The first and third sends are at least two 25 ms intervals apart.
  assert.ok(performance.now() - startTime >= 48);
  run.ack('acquire');
  await run.expectExit(0, 3);
});
