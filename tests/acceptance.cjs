// Optional regression run with Node.js, Playwright and Microsoft Edge installed.
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const { spawn } = require("node:child_process");
const { once } = require("node:events");
const { createInterface } = require("node:readline");
const os = require("node:os");
const path = require("node:path");
const { chromium } = require("playwright");

async function run() {
  const project = path.resolve(__dirname, "..");
  const fixture = spawn("python3", [path.join(__dirname, "model_fixture.py")], {stdio: ["ignore", "pipe", "inherit"]});
  const profile = await fs.mkdtemp(path.join(os.tmpdir(), "single-choice-edge-"));
  let context;
  try {
    const lines = createInterface({input: fixture.stdout});
    const [port] = await Promise.race([
      once(lines, "line"), once(fixture, "exit").then(() => { throw new Error("Test server exited"); })
    ]);
    lines.close();
    assert(/^\d+$/.test(port));
    const url = "http://127.0.0.1:" + port;
    // Isolate tests from any production bridge running on the user's chosen port.
    const extension = path.join(profile, "fixture-extension");
    await fs.cp(path.join(project, "extension"), extension, {recursive: true});
    const workerFile = path.join(extension, "background.js");
    const source = await fs.readFile(workerFile, "utf8");
    assert(source.includes("http://127.0.0.1:8766/api/answer"));
    await fs.writeFile(workerFile, source.replace("http://127.0.0.1:8766/api/answer", url + "/api/answer"));
    context = await chromium.launchPersistentContext(profile, {
      channel: "msedge", headless: true,
      args: ["--enable-unsafe-extension-debugging"], ignoreDefaultArgs: ["--disable-extensions"]
    });
    const page = context.pages()[0];
    page.setDefaultTimeout(5000);
    // Exercise a native form submission, including the actual browser Origin header.
    const setupEnv = {...process.env, QUIZ_ENV_FILE: path.join(profile, "setup.env")};
    delete setupEnv.MODEL_PROVIDER;
    delete setupEnv.ANTHROPIC_API_KEY;
    delete setupEnv.ANTHROPIC_MODEL;
    const setup = spawn("python3", [path.join(project, "configure.py"), "--provider", "anthropic", "--no-browser"],
      {env: setupEnv, stdio: ["ignore", "pipe", "inherit"]});
    const setupLines = createInterface({input: setup.stdout});
    try {
      const setupDone = once(setup, "exit");
      for await (const line of setupLines) {
        if (!line.startsWith("http://127.0.0.1:")) continue;
        await page.goto(line);
        await page.getByLabel("API Key").fill("browser-test-key");
        await page.getByRole("button", {name: "保存本机配置"}).click();
        await page.getByText("配置已保存。可以关闭此页，返回安装助手继续。").waitFor();
        break;
      }
      assert.equal((await setupDone)[0], 0);
      assert((await fs.readFile(setupEnv.QUIZ_ENV_FILE, "utf8")).includes("MODEL_PROVIDER=anthropic"));
      console.log("PASS first-run local configuration in Edge");
    } finally {
      setupLines.close();
      setup.kill();
    }
    await page.goto(url + "/?case=native");
    const browserSession = await context.browser().newBrowserCDPSession();
    const { id } = await browserSession.send("Extensions.loadUnpacked", {path: extension});
    const worker = context.serviceWorkers()[0] || await context.waitForEvent("serviceworker");
    assert(await worker.evaluate(() => chrome.action.onClicked.hasListeners()));
    const targets = await browserSession.send("Target.getTargets", {filter: [{type: "tab"}]});
    const targetId = targets.targetInfos[0].targetId;
    const visit = mode => page.goto(url + "/?case=" + mode);
    const trigger = () => browserSession.send("Extensions.triggerAction", {id, targetId});
    await worker.evaluate(() => {
      const originalFetch = globalThis.fetch;
      globalThis.sent = [];
      globalThis.fetch = async (url, init) => {
        const question = JSON.parse(init.body);
        globalThis.sent.push(question);
        const response = await originalFetch(url, init);
        if (question.stem === globalThis.holdStem) {
          globalThis.holdStem = null;
          await new Promise(resolve => { globalThis.releaseHeld = resolve; });
          globalThis.releaseHeld = null;
        }
        return response;
      };
    });
    const requests = () => worker.evaluate(() => globalThis.sent.length);
    async function until(predicate, message) {
      const deadline = Date.now() + 6500;
      while (Date.now() < deadline) {
        if (await predicate()) return;
        await new Promise(resolve => setTimeout(resolve, 45));
      }
      throw new Error(message);
    }
    // Observe the content script in its isolated world without adding page UI.
    async function finished() {
      return worker.evaluate(async () => {
        const [tab] = await chrome.tabs.query({active: true, lastFocusedWindow: true});
        const [status] = await chrome.scripting.executeScript({
          target: {tabId: tab.id}, func: () => globalThis.pageAnswerState?.active === null
        });
        return status.result;
      });
    }
    async function settle() {
      await until(finished, "Toolbar run did not finish");
      assert.equal(await page.locator("aside, [role=dialog], [role=status], dialog").count(), 0);
      assert.equal(await worker.evaluate(() => chrome.action.getBadgeText({})), "");
    }
    async function answer() {
      await trigger();
      await settle();
    }

    for (const [mode, selected] of [
      ["native", "input:checked"], ["custom", '[aria-checked=true]'],
      ["buttons", '[data-selected=true]']
    ]) {
      await visit(mode);
      const before = await requests();
      await answer();
      assert.equal(await requests(), before + 1);
      if (mode === "native") {
        assert(await page.getByRole("radio", {name: "满月"}).isChecked());
      } else {
        assert.deepEqual(await page.locator(selected).allTextContents(), [mode === "custom" ? "红光" : "15 分钟"]);
      }
      console.log("PASS", mode);
    }

    const checkedLabels = scope => scope.locator("input:checked").evaluateAll(nodes =>
      nodes.map(node => node.labels[0].textContent.trim()));
    const firstStem = "哪颗行星离太阳最近？";
    const secondStem = "哪颗行星最大？";
    const hold = stem => worker.evaluate(s => { globalThis.holdStem = s; }, stem);
    const waitHeld = () => until(() => worker.evaluate(() => Boolean(globalThis.releaseHeld)), "Missing held reply");
    const release = () => worker.evaluate(() => globalThis.releaseHeld());
    const pending = () => worker.evaluate(async () => {
      const [tab] = await chrome.tabs.query({active: true, lastFocusedWindow: true});
      const [status] = await chrome.scripting.executeScript({
        target: {tabId: tab.id}, func: () => globalThis.pageAnswerState?.pending.size
      });
      return status.result;
    });

    await visit("images");
    await page.locator("#exercise .diagram").evaluate(img => {
      const link = document.createElement("a");
      link.href = img.src;
      img.replaceWith(link);
      link.append(img);
      document.querySelector("header").append(img.cloneNode());
    });
    const imageStart = await requests();
    await answer();
    const imageSelections = () => page.locator("#exercise input:checked").evaluateAll(nodes =>
      nodes.map(node => [node.name, [...document.getElementsByName(node.name)].indexOf(node) + 1]));
    assert.deepEqual(await imageSelections(), [["count", 2], ["direction", 3]]);
    const imageBodies = await worker.evaluate(n => globalThis.sent.slice(n), imageStart);
    assert.deepEqual(imageBodies.map(q => q.images.map(i => i.part)), [[0], [1, 2, 3]]);
    const sources = await page.locator("#exercise img").evaluateAll(nodes => nodes.map(img => img.src));
    assert.deepEqual(imageBodies.flatMap(q => q.images.map(i => i.data)), sources);
    console.log("PASS stem and image-only options send correct pixel data in DOM order");

    await visit("images");
    const brokenStart = await requests();
    await page.locator("#exercise .diagram").evaluate(img => img.src = "data:image/png;base64,broken");
    await answer();
    assert.deepEqual(await imageSelections(), [["direction", 3]]);
    assert.equal(await requests(), brokenStart + 1);
    console.log("PASS unreadable image skips only its own question");

    await visit("images");
    await hold("图中有几个蓝色圆形？");
    await trigger();
    await waitHeld();
    await page.locator("#exercise .diagram").evaluate(img => img.src = document.querySelector(".row img").src);
    await release();
    await settle();
    assert.deepEqual(await imageSelections(), [["direction", 3]]);
    console.log("PASS replaced diagram invalidates a pending answer");

    await visit("rows");
    const start = await requests();
    await hold(secondStem);
    await trigger();
    await waitHeld();
    assert.deepEqual(await checkedLabels(page), ["水星"]);
    await trigger();
    await settle();
    await release();
    await until(async () => await pending() === 0, "Late reply not drained");
    assert.deepEqual(await checkedLabels(page), ["水星"]);
    assert.equal(await requests(), start + 2);
    await trigger();
    await until(() => page.getByRole("radio", {name: "木星"}).isChecked(), "Resume did not fill unanswered question");
    await settle();
    assert.deepEqual(await checkedLabels(page), ["水星", "木星"]);
    assert.deepEqual(await worker.evaluate(n => globalThis.sent.slice(n).map(q => q.stem), start),
      [firstStem, secondStem, secondStem]);
    console.log("PASS pause discards late replies and resumes only unanswered questions");

    await visit("rows");
    const restart = await requests();
    await hold(firstStem);
    await trigger();
    await waitHeld();
    await trigger();
    await settle();
    await trigger();
    await until(async () => !(await finished()), "New run did not start");
    await release();
    await settle();
    assert.deepEqual(await checkedLabels(page), ["水星", "木星"]);
    assert.equal(await requests(), restart + 2);
    console.log("PASS rapid stop/resume shares in-flight request and old run cannot clear new run");

    await visit("rows");
    await hold(firstStem);
    await trigger();
    await waitHeld();
    await page.locator("#o2").check();
    await release();
    await settle();
    assert.deepEqual(await checkedLabels(page), ["金星", "木星"]);
    console.log("PASS manual choice during model request is preserved");

    await visit("rows");
    await page.evaluate(() => {
      const frame = document.createElement("iframe");
      frame.srcdoc = document.querySelector("#exercise").innerHTML;
      document.querySelector("#exercise").replaceChildren(frame);
    });
    const embedded = page.frameLocator("iframe");
    await embedded.locator("input").first().waitFor();
    await answer();
    assert.deepEqual(await checkedLabels(embedded), ["水星", "木星"]);
    console.log("PASS same-origin iframe");

    await visit("rows");
    await page.locator("#exercise .prompt").evaluate(el => el.textContent = "哪项是无效编号？");
    await answer();
    assert.deepEqual(await checkedLabels(page), ["木星"]);
    console.log("PASS invalid answer is skipped and later questions proceed");

    await visit("rows");
    const prior = await requests();
    await trigger();
    await until(async () => await requests() > prior, "Missing request before DOM change");
    await page.locator("label[for=o1]").evaluate(el => el.textContent = "替换后的选项");
    await settle();
    assert.deepEqual(await checkedLabels(page), ["木星"]);
    console.log("PASS changed question skipped without affecting next question");

    await visit("rows");
    await page.evaluate(() => {
      document.querySelector("#o1").onclick = event => event.preventDefault();
    });
    await answer();
    assert.deepEqual(await checkedLabels(page), ["木星"]);
    console.log("PASS unconfirmed click does not stop subsequent question");

    async function skipped(name) {
      const before = await requests();
      await answer();
      assert.equal(await requests(), before);
      assert.equal(await page.locator("#exercise :checked, #exercise [aria-checked=true]").count(), 0);
      console.log("PASS", name);
    }
    await visit("canvas");
    await skipped("canvas");
    await visit("native");
    await page.locator("#exercise input").last().evaluate(el => el.disabled = true);
    await skipped("disabled choice");
    await visit("custom");
    await page.evaluate(() => {
      const form = document.createElement("form");
      const exercise = document.querySelector("#exercise");
      form.append(...exercise.childNodes);
      exercise.append(form);
      form.querySelectorAll("button").forEach(el => el.removeAttribute("type"));
    });
    await skipped("form submit controls");
    await visit("buttons");
    await page.locator("#exercise h2").evaluate(el => el.textContent = "选择喜欢的颜色");
    await skipped("ambiguous group");
    await visit("custom");
    await page.evaluate(() => {
      const article = document.querySelector("#exercise article");
      article.after(article.cloneNode(true));
    });
    await skipped("duplicate question");
  } finally {
    try {
      await context?.close();
    } finally {
      fixture.kill();
      await fs.rm(profile, {recursive: true, force: true});
    }
  }
}

run().catch(error => { console.error(error); process.exitCode = 1; });
