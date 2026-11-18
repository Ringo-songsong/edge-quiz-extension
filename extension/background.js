chrome.action.onClicked.addListener(async (tab) => {
  if (!tab.id) return;
  try {
    await chrome.scripting.executeScript({
      target: {tabId: tab.id},
      files: ["recognize.js", "question-images.js", "answer-page.js"]
    });
  } catch {
    // Restricted pages and closed tabs have no document to process.
  }
});

const answerUrl = "http://127.0.0.1:8766/api/answer";

async function getAnswer(stem, options, images) {
  let response;
  try {
    response = await fetch(answerUrl, {
      method: "POST",
      headers: {"Content-Type": "application/json", "X-Edge-Quiz": "1"},
      body: JSON.stringify({stem, options, images}),
      redirect: "error", credentials: "omit", signal: AbortSignal.timeout(images?.length ? 90000 : 25000)
    });
  } catch (error) {
    throw new Error(error.name === "TimeoutError" ? "本机服务响应超时，请重试。"
      : "无法连接本机服务，请在项目目录运行 python3 server.py。");
  }
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error("本机服务响应格式有误，请确认端口 8766 运行的是答题服务。");
  }
  if (!response.ok) throw new Error(data?.error || "本机服务未能取得模型答案。");
  if (!Number.isInteger(data?.choice) || data.choice < 1 || data.choice > options.length) {
    throw new Error("服务返回的选项编号无效。");
  }
  return {choice: data.choice};
}

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg?.type !== "answer-single" || sender.id !== chrome.runtime.id ||
      !sender.tab || sender.frameId !== 0) return;
  getAnswer(msg.stem, msg.options, msg.images).then(reply, error => reply({error: error.message}));
  return true;
});
