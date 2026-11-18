// State is isolated per document. Each start owns a distinct run so an older
// response or finally block cannot click for, or stop, a newer run.
(async () => {
  const state = globalThis.pageAnswerState ??= {active: null, pending: new Map()};
  if (state.active) {
    state.active = null;
    return;
  }

  const run = {};
  state.active = run;
  const reader = globalThis.singleChoiceReader;
  const url = location.href;
  const running = () => state.active === run && location.href === url;
  function release() {
    if (state.active === run) state.active = null;
  }
  window.addEventListener("pagehide", release, {once: true});

  // A rapid resume may need the exact request that is still on the wire.
  // Share it only until it settles; a later run requests a fresh answer.
  async function requestAnswer({key, stem, options, images}) {
    const requestKey = JSON.stringify([url, key]);
    if (state.pending.has(requestKey)) return state.pending.get(requestKey);
    const attachments = images.length ? await encodeQuestionImages(images, running) : undefined;
    if (!running() || (attachments && !reader.findUnanswered(key))) return;
    if (!state.pending.has(requestKey)) {
      const promise = chrome.runtime.sendMessage({type: "answer-single", stem, options, images: attachments})
        .finally(() => state.pending.delete(requestKey));
      state.pending.set(requestKey, promise);
    }
    return state.pending.get(requestKey);
  }

  try {
    const questions = reader.scan();
    const seen = new Set();
    const duplicates = new Set();
    for (const {key} of questions) {
      if (seen.has(key)) duplicates.add(key);
      seen.add(key);
    }
    for (const {key} of questions) {
      if (!running()) break;
      const question = !duplicates.has(key) && reader.findUnanswered(key);
      if (!question) continue;
      try {
        const reply = await requestAnswer(question);
        if (!running()) break;
        if (!Number.isInteger(reply?.choice) || reply.choice < 1 || reply.choice > question.options.length) continue;
        await reader.choose(key, reply.choice - 1, running);
      } catch {
        // Unreadable images, changed questions and unconfirmed clicks are local to this question.
      }
    }
  } finally {
    window.removeEventListener("pagehide", release);
    release();
  }
})();
