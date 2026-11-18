import {chapters} from "./bank.js";

const byId = id => document.getElementById(id);
const questions = [];
const responses = new Map();
const pages = byId("pages");
const total = chapters.reduce((n, chapter) => n + chapter.rows.length, 0);
let startTime = null;
let endTime = null;
let timerId = null;
let origin = "";
let firstCount = 0;
let graded = false;
let seed = 29067;

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}
function choices(answers) {
  const result = [...answers];
  for (let i = result.length - 1; i > 0; i--) {
    seed = (Math.imul(1664525, seed) + 1013904223) >>> 0;
    const j = Math.floor(seed / 4294967296 * (i + 1));
    [result[i], result[j]] = [result[j], result[i]];
  }
  return result;
}
function drawClock() {
  const ms = startTime === null ? 0 : (endTime ?? performance.now()) - startTime;
  const tenths = Math.floor(ms / 100);
  byId("clock").textContent = String(Math.floor(tenths / 600)).padStart(2,"0") + ":" +
    String(Math.floor(tenths / 10) % 60).padStart(2,"0") + "." + (tenths % 10);
}
function start(manual) {
  startTime = performance.now();
  firstCount = manual ? 0 : 1;
  origin = manual ? "手动开始计时" : "首个勾选起计时";
  byId("clock-label").textContent = origin;
  byId("timing").textContent = "结束计时";
  byId("timing-help").textContent = manual ? "包含点击扩展和等待首题的时间。" : "此次计时从首次勾选开始，不含首题等待时间。";
  timerId = setInterval(drawClock, 100);
  drawClock();
}
function stop() {
  endTime = performance.now();
  clearInterval(timerId);
  drawClock();
  byId("timing").textContent = "计时已结束";
  byId("timing").disabled = true;
  byId("timing-help").textContent = origin + "，共记录到 " + responses.size + " 道已答题。";
  const timedQuestions = responses.size - firstCount;
  const seconds = (endTime - startTime) / 1000;
  if (timedQuestions > 0 && seconds > 0) {
    byId("rate").hidden = false;
    byId("rate").textContent = (seconds / timedQuestions).toFixed(2) + " 秒/题 · " +
      (timedQuestions * 60 / seconds).toFixed(1) + " 题/分钟";
  }
}
function review() {
  let right = 0;
  for (const q of questions) {
    const value = responses.get(q.index);
    const correct = value === q.answer;
    if (correct) right++;
    q.note.hidden = false;
    q.note.classList.toggle("ok", correct);
    q.note.textContent = correct ? "正确" : (value === undefined ? "未答" : "答错") + " · 正确答案为「" + q.answer + "」";
  }
  byId("score").hidden = false;
  byId("score").textContent = "正确 " + right + " / " + total + " · 错误 " + (responses.size - right) + " · 未答 " + (total - responses.size);
}
function record(index, value) {
  if (startTime === null) start(false);
  responses.set(index, value);
  byId("answered").textContent = String(responses.size);
  byId("meter").value = responses.size;
  if (responses.size === total && endTime === null) stop();
  if (graded) review();
}

function makeChoices(list, q, style) {
  const options = el("div","answers");
  if (style === 1) {
    options.setAttribute("role","radiogroup");
    options.setAttribute("aria-labelledby", "prompt-" + q.index);
  }
  list.forEach((text, i) => {
    if (style === 1) {
      const button = el("button","pick",text);
      button.type = "button";
      button.setAttribute("role","radio");
      button.setAttribute("aria-checked","false");
      button.tabIndex = i === 0 ? 0 : -1;
      button.onclick = () => {
        for (const option of options.children) {
          option.setAttribute("aria-checked",String(option === button));
          option.tabIndex = option === button ? 0 : -1;
        }
        record(q.index,text);
      };
      button.onkeydown = event => {
        const dirs = {ArrowLeft:-1,ArrowUp:-1,ArrowRight:1,ArrowDown:1};
        if (!(event.key in dirs)) return;
        event.preventDefault();
        const next = options.children[(i + dirs[event.key] + list.length) % list.length];
        next.focus();
        next.click();
      };
      options.append(button);
    } else {
      const row = el(style === 0 ? "label" : "div","pick");
      const input = el("input");
      input.type = "radio";
      input.name = "answer-" + q.index;
      input.id = input.name + "-" + i;
      const label = el(style === 0 ? "span" : "label","",text);
      if (style === 2) label.htmlFor = input.id;
      input.onchange = () => { if (input.checked) record(q.index,text); };
      row.append(input,label);
      options.append(row);
    }
  });
  return options;
}

for (const [c, chapter] of chapters.entries()) {
  const unit = el("section","unit");
  unit.id = "unit-" + (c + 1);
  const chapterNumber = String(c + 1).padStart(2,"0");
  const link = el("a"); link.href = "#" + unit.id;
  link.append(el("span","index-num",chapterNumber),el("span","",chapter.title));
  byId("index").append(link);
  const header = el("div","unit-head");
  header.append(el("span","part","UNIT " + chapterNumber),el("h2","",chapter.title));
  unit.append(header);
  for (const [stem, ...answers] of chapter.rows) {
    const index = questions.length + 1;
    const card = el("article","question");
    const prompt = el("div","prompt");
    const heading = el("h3","",stem); heading.id = "prompt-" + index;
    prompt.append(el("span","num",String(index).padStart(2,"0")),heading);
    const note = el("p","review"); note.hidden = true;
    const q = {index, answer:answers[0], note};
    questions.push(q);
    card.append(prompt,makeChoices(choices(answers),q,(index-1) % 3),note);
    unit.append(card);
  }
  pages.append(unit);
}

byId("timing").onclick = () => { if (startTime === null) start(true); else if (endTime === null) stop(); };
byId("grade").onclick = () => { graded = true; review(); };
byId("reset").onclick = () => {
  // A fresh document also cancels an extension run that is still answering.
  location.reload();
};
