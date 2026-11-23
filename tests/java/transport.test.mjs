import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { setTimeout as delay } from 'node:timers/promises';
import test from 'node:test';

const classpath = process.env.GALAXY_JAVA_CLASSPATH;
assert.ok(classpath, 'Set GALAXY_JAVA_CLASSPATH to the classes and Gson jar');
const init = '{"type":"init","participantId":"java-test"}\r\n';

function start(t, ...args) {
  const child = spawn('java', ['-cp', classpath, 'galaxy.fixture.Demo', ...args]);
  t.after(() => child.kill());
  const stdout = [];
  let stderr = '';
  const lines = createInterface({ input: child.stdout, crlfDelay: Infinity });
  const nextLine = lines[Symbol.asyncIterator]();
  lines.on('line', line => stdout.push(line));
  child.stderr.setEncoding('utf8');
  child.stderr.on('data', data => { stderr += data; });
  child.stdin.on('error', error => {
    if (!['EPIPE', 'ERR_STREAM_DESTROYED'].includes(error.code)) throw error;
  });
  const exited = new Promise((resolve, reject) => {
    child.once('error', reject);
    child.once('close', resolve);
  });
  return {
    send: data => child.stdin.write(data),
    end: () => child.stdin.end(),
    ack: (action, revision = 31) => child.stdin.write(JSON.stringify({ type: 'ack', action, revision }) + '\n'),
    async event(action) {
      const { value } = await nextLine.next();
      assert.ok(value, stderr);
      const event = JSON.parse(value);
      assert.equal(event.type, action);
      assert.ok(!('participantId' in event));
      return event;
    },
    async waiting(count) {
      await delay(80);
      assert.equal(child.exitCode, null, stderr);
      assert.equal(stdout.length, count);
    },
    async finish(code, count, diagnostic) {
      assert.equal(await exited, code, stderr);
      assert.equal(stdout.length, count);
      assert.match(stderr, diagnostic);
    },
  };
}

test('reset, UTF-8, same slot and final ack before success without EOF', { timeout: 8000 }, async t => {
  const host = start(t, '--reset-on-start');
  host.send(init);
  assert.deepEqual(await host.event('reset'), { type: 'reset' });
  await host.waiting(1);
  host.ack('reset');
  const first = await host.event('acquire');
  assert.equal(first.data.name, '첫 별 🌟');
  assert.equal(first.generation, 1);
  assert.equal(typeof first.poolSlotId, 'string');
  await host.waiting(2);
  host.ack('acquire', 39);
  assert.deepEqual(await host.event('release'), {
    type: 'release', poolSlotId: first.poolSlotId, generation: 1,
  });
  host.ack('release', 44);
  const reused = await host.event('acquire');
  assert.equal(reused.poolSlotId, first.poolSlotId);
  assert.equal(reused.generation, 2);
  assert.deepEqual(reused.data, { name: 'Reborn Nova', type: 'planet', color: '#a78bfa', size: 1.6 });
  await host.waiting(4);
  host.ack('acquire', 48);
  await host.finish(0, 4, /Running Java fixture for java-test/);
});

for (const [name, send, diagnostic] of [
  ['wrong action', host => host.ack('release'), /matching ack/],
  ['unsafe revision', host => host.ack('acquire', 2 ** 53), /matching ack/],
  ['remote rejection', host => host.send('{"type":"error","message":"denied"}\n'), /Rejected by host: denied/],
  ['malformed JSON', host => host.send('{"type":"ack","action":"acquire","revision":NaN}\n'), /Malformed JSON/],
  ['oversized input', host => host.send(' '.repeat(8001) + '\n'), /exceeds 8000 bytes/],
  ['invalid UTF-8', host => host.send(Buffer.from([0xff, 0x0a])), /Invalid control stream/],
  ['EOF', host => host.end(), /stdin closed/],
  ['timeout', () => {}, /Timed out/],
]) {
  test(`${name} stops after the first event`, { timeout: 8000 }, async t => {
    const host = start(t);
    host.send(init);
    await host.event('acquire');
    send(host);
    await host.finish(1, 1, diagnostic);
  });
}

test('invalid init fails before the scenario', { timeout: 8000 }, async t => {
  const host = start(t);
  host.send('{"type":"init","participantId":"bad id"}\n');
  await host.finish(1, 0, /Expected init/);
});

test('startup reset rejection prevents the first acquire', { timeout: 8000 }, async t => {
  const host = start(t, '--reset-on-start');
  host.send(init);
  await host.event('reset');
  host.send('{"type":"error","message":"reset refused"}\n');
  await host.finish(1, 1, /reset refused/);
});
