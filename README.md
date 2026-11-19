# 作答本页 · Edge 单选题扩展

在 Microsoft Edge 中打开练习页，点击一次「作答本页」，扩展会逐道读取页面上尚未作答的单选题，把题干、选项和配图交给你配置的模型，再勾选并核验网页上的实际状态。整个过程直接使用网页原有控件。你可以随时暂停、修改答案并自行交卷。

适合有标准单选控件的在线练习、看图选择题，以及测试自建题库的答题耗时。能否适配一个新网站，主要取决于网页如何标记题干、选项和选中状态。扩展没有课程网址白名单，也无需预先录入该网站的题目。

## 让 AI 帮你安装

把仓库链接发给能操作你电脑的 AI 助手，可以直接说：“请下载并安装这个 Edge 扩展。下载好后问我用哪家的 API，打开本机页面让我填密钥，然后帮我检查配置。”

**给安装助手：** 下载或解压后请继续按 [安装助手指引](AGENTS.md) 操作。先运行 `python3 server.py --check-config`。首次安装时主动询问用户使用哪家 API；已有配置时询问是否沿用。确定厂家后，在用户本机运行相应的命令，例如 Claude 使用：

```sh
python3 configure.py --provider anthropic
```

配置工具会打开一个只在本机回环地址监听的临时页面。用户在密码框输入该厂家的 API Key 并点「保存本机配置」，工具就会写好对应字段、保留其他厂家的设置并关闭。密钥无需发到聊天里。助手随后再次运行 `--check-config`，再继续加载扩展。页面链接 10 分钟有效；浏览器未自动打开时，可在运行工具的同一台电脑打开终端显示的链接。仅能在云端运行的助手可把命令交给用户在本机执行。GitHub 下载 ZIP 本身不会执行程序，助手是否主动询问取决于它是否读取安装指引。

## 安装和首次运行

需要桌面版 Microsoft Edge、Python 3.7 或以上版本，以及可用的 OpenAI、Claude、DeepSeek、Kimi 或其他兼容模型服务。本机服务只使用 Python 标准库，日常使用无需安装 Node.js 或 Python 依赖。

1. [下载项目 ZIP](https://github.com/Ringo-songsong/edge-quiz-extension/archive/refs/heads/main.zip) 并解压，或克隆本仓库。打开解压后能看见 `server.py`、`extension/` 和 `.env.example` 的目录。
2. 在这个目录打开终端，运行 `python3 configure.py --provider anthropic`。把 `anthropic` 换成你的服务商即可，其他可选值有 `openai`、`deepseek`、`kimi`、`custom`。Windows 将 `python3` 换为 `py -3`。也可以手动把 `.env.example` 复制为 `.env`，再按下面的一组示例填写。已有配置可直接沿用。
3. 先用 `python3 server.py --check-config` 检查配置，再执行 `python3 server.py`（Windows 可用 `py -3 server.py`）。让终端在作答期间持续运行。打开[本机练习页](http://127.0.0.1:8766/)即可确认服务已启动。
4. 在 Edge 地址栏输入 `edge://extensions/`，开启「开发人员模式」，点「加载解压缩的扩展」，**选择解压目录下的 `extension` 文件夹**。它直接包含 `manifest.json`。可在工具栏的「扩展」菜单中将「作答本页」固定到工具栏。
5. 打开[双题练习页](http://127.0.0.1:8766/?case=rows)，点击「作答本页」图标。两道题应依次选中「水星」和「木星」。这一步会实际调用 API，可同时验证密钥、网络和网页勾选。

## 选择模型服务

只需将下面一组配置写入项目根目录的 `.env`。密钥来自对应服务商的 **API 开放平台**，模型 ID 以你的 API 账户可用列表为准。切换时修改 `MODEL_PROVIDER` 并保存，再启动一轮作答。

### Claude（Anthropic Messages API）

```dotenv
MODEL_PROVIDER=anthropic
ANTHROPIC_API_KEY=替换为你的Anthropic密钥
ANTHROPIC_MODEL=claude-sonnet-5-5
```

官方预设调用 `https://api.anthropic.com/v1/messages`。使用 Claude Console 的 API 密钥，模型 ID 可换成你账户有权限的型号。如密钥要求指定工作区，另加 `ANTHROPIC_WORKSPACE_ID`。文字、题干配图和图片选项均可发送，图片以带归属标签的 Base64 内容块传入。[Claude API 文档](https://platform.claude.com/docs/en/api/messages/create) · [模型列表](https://platform.claude.com/docs/en/about-claude/models/overview)

如果密钥来自提供 **Claude Messages 格式的第三方**，请选择 `custom`，填写该服务自己的地址和密钥。下面使用占位域名示范：

```dotenv
MODEL_PROVIDER=custom
CUSTOM_API_FORMAT=anthropic
CUSTOM_BASE_URL=https://gateway.example/v1
CUSTOM_MODEL=替换为网关提供的模型ID
CUSTOM_API_KEY=替换为网关发放的密钥
```

该示例会访问 `https://gateway.example/v1/messages`，使用 `x-api-key` 和 `anthropic-version: 2023-06-01`。基础地址也可以是完整的 `/v1/messages` 端点。要求云平台 IAM 签名等其他认证的接口，需要对应的网关。

### DeepSeek

```dotenv
MODEL_PROVIDER=deepseek
DEEPSEEK_API_KEY=替换为你的DeepSeek密钥
DEEPSEEK_MODEL=deepseek-flash
```

预设端点为 `https://api.deepseek.com/chat/completions`。示例模型支持文字和图片。选择其他模型时请核对它的输入能力。[DeepSeek 接入指南](https://api-docs.deepseek.com/) · [视觉输入说明](https://api-docs.deepseek.com/guides/vision/)

### Kimi（月之暗面）

```dotenv
MODEL_PROVIDER=kimi
MOONSHOT_API_KEY=替换为你的Kimi密钥
MOONSHOT_MODEL=kimi-k3.1-pro
```

此预设使用 `https://api.moonshot.cn/v1/chat/completions`。若发放密钥的平台列出了不同的基础地址，可选用下一节的自定义配置，填入该平台的地址、模型 ID 和配套密钥。[Kimi 官方快速开始](https://platform.kimi.com/docs/get-api-key)

### 其他兼容接口与本机模型

适用于兼容 OpenAI **Chat Completions** 的非流式服务。接口需接受 `messages`，并返回 `choices[0].message.content`。下面以运行在本机 1234 端口的服务为例。

```dotenv
MODEL_PROVIDER=custom
CUSTOM_BASE_URL=http://127.0.0.1:1234/v1
CUSTOM_MODEL=替换为服务中已加载的模型ID
CUSTOM_API_KEY=
```

先启动模型服务并加载模型，再填入它显示的基础地址和模型 ID。云端服务请填写服务商提供的 HTTPS 地址和密钥；本机回环服务免认证时可留空。自定义接口默认使用 `CUSTOM_API_FORMAT=chat`，保留基础地址的版本路径并补上 `/chat/completions`，也接受完整端点。Claude Messages 格式使用前面的 `anthropic` 配置。仅提供 Gemini 原生协议的服务需要兼容入口。

### OpenAI 和旧配置

```dotenv
MODEL_PROVIDER=openai
OPENAI_API_KEY=替换为你的OpenAI密钥
OPENAI_MODEL=gpt-6.2-sol
OPENAI_REASONING_EFFORT=xhigh
```

旧版配置缺少 `MODEL_PROVIDER` 时默认使用 OpenAI。升级时保留自己的 `.env`，更新项目文件、重启 Python 服务，并在 Edge 的扩展管理页重新加载「作答本页」。OpenAI 仍使用 Responses API。若模型不接受推理强度参数，可将 `OPENAI_REASONING_EFFORT=` 留空。这个参数只发给 OpenAI。

### 验证配置和排查权限问题

在项目目录执行下列命令。Windows 可将 `python3` 换为 `py -3`。

| 命令或现象 | 如何判断 |
| --- | --- |
| `python3 server.py --check-config` | 仅读取配置并显示服务商和模型 ID，不发请求、不显示密钥。成功表示本机配置可用 |
| `python3 server.py --test-api` | 向所选端点实际发送一道文字题，可能计费。返回选项 2 即答对。图片能力另用下方图片练习页验证 |
| 提示 Python 无权读取配置文件 | 此时尚未调用模型。确认已解压、文件名为 `.env`（Windows 注意 `.env.txt`），检查当前用户和启动 Python 的终端对文件及所在目录的读取权限 |
| 提示缺少密钥 | 检查所选服务商对应的变量名。例如 DeepSeek 使用 `DEEPSEEK_API_KEY`，Kimi 使用 `MOONSHOT_API_KEY` |
| 终端显示服务商名和 HTTP 401 / 403 | 请求已到上游。401 先核对密钥和端点是否配套；403 核对账户、区域和模型权限 |
| HTTP 402 / 429、404、400 / 422 | 分别检查余额或请求频率、端点或模型 ID、输入格式或图片能力。服务商拒绝带图请求时，该题保持未答 |
| 提示未取得响应 | 检查该端点的网络、代理及超时。本机模型还需检查进程和端口 |

读取配置的是 **Python 本机服务**。如果项目目录受限，可将配置保存到当前用户可读的位置，再在启动服务的同一个终端设置路径。macOS / Linux 使用 `export QUIZ_ENV_FILE="$HOME/edge-quiz.env"`；Windows PowerShell 使用 `$env:QUIZ_ENV_FILE = "$HOME/edge-quiz.env"`。在该文件中保存相同配置后重新运行检查。也可以把 `QUIZ_ENV_FILE` 设为单个减号 `-`，通过进程环境变量提供上面同名的服务商、模型和密钥设置，完全跳过文件读取。Edge 扩展无需读取本机文件。

## 在作业页使用

| 操作 | 行为 |
| --- | --- |
| 自行登录网站，打开题目页，等题目加载后点一次图标 | 从本页第一道可识别、未勾选的单选题开始，按顺序处理 |
| 作答过程中再点一次 | 暂停。已经选好的答案保留。已发出的请求可能仍会完成并计费，暂停期间返回的答案不会触发点击 |
| 暂停后再点一次 | 重新扫描页面，从第一道仍未勾选的题继续，保留你手动选择的答案 |
| 切换到下一页或手动加载更多题目 | 在新一批题目加载后再次启动。每轮处理的是该轮开始时已加载的题目 |
| 准备交卷 | 在原网页核对或修改选项，然后手动提交 |

扩展全程无弹窗、提示条和自动交卷。每道云端模型题都需要能访问所选 API。使用已加载的本机模型时，模型调用可以留在本机。

## 具体原理

以「哪颗行星最大？」为例，若页面依次给出「火星、木星」，扩展会记录「1 对应火星的单选框，2 对应木星的单选框」。模型收到题目和编号后的选项，若返回 `{"choice":2}`，扩展就回到原页面，重新核对题目并点击「木星」。网页可能改变题目顺序，因此勾选前还会检查选项文字、图片来源和排列顺序。

| 环节 | 实现 |
| --- | --- |
| 找到属于同一题的控件 | 在当前页面及可访问的同源 iframe 中遍历 DOM（浏览器表示网页结构的节点树）。原生 `input[type=radio]` 按所属表单和 `name` 分组；自定义 `role=radio` 按最近的 `radiogroup` 分组。对于同组使用 `aria-pressed` 或 `data-selected` 的按钮，还要求题干有「单选」等标记。 |
| 配对题干和选项 | 从控件的共同容器向上查找 `legend`、关联标题或附近唯一的题干。选项文字来自 `label`、`aria-labelledby`、`aria-label` 或相邻选项行。发现其他题组时停止向上搜索；题目重复到无法唯一定位时跳过。 |
| 处理图片 | 从题干和每个选项各自的 DOM 范围读取 `img` 的实际像素，标明「题干配图」或「选项 N 配图」。浏览器先等比缩放，优先编码为 PNG，较大图片转 JPEG。每题最多 12 张，长边最多 1800 像素。图片无法读取或超限时跳过该题。 |
| 请求模型 | 扩展后台把一题发到本机 `POST /api/answer`。Python 服务验证输入，按配置逐题调用 OpenAI Responses、Anthropic Messages 或 Chat Completions。有图时将实际图片与归属标签一同发送。OpenAI 路径使用严格 JSON Schema；其他路径通过提示要求 JSON。本机服务统一校验整数编号及其范围。 |
| 点击并核验 | 请求前、模型返回后都检查题目是否仍可唯一定位且未作答。点击后回读整组控件的 `checked` 或相应状态属性，在最长 1.5 秒内确认只有目标项连续选中至少 200 毫秒。确认失败就继续下一题，不反复点击。 |

**识别控件由浏览器里的 JavaScript 完成，选择答案由配置的模型完成。** 更换模型可能影响正确率和耗时；遇到网页结构不受支持的题型，需要调整识别代码。核验成功表示网页已勾选目标项，答案是否正确仍需对照题意或评分结果。

## 哪些网页适用

| 页面情况 | 当前版本的表现 |
| --- | --- |
| 一页多道文字单选题，使用原生单选框或上文所列的自定义控件 | 可逐题作答，已有选择的题会跳过 |
| 题干含示意图、照片，或选项只有图片 | 支持普通 `img` 和 `picture` 内的 `img`。图片需可由当前页面读取；跨域图片还取决于图片服务器的访问策略 |
| 题目放在同源 iframe | 支持可见、可访问的子页面；跨域 iframe 和 Shadow DOM 内部未适配 |
| 不断滚动才加载题目或需要翻页 | 先手动加载或翻页，再启动新一轮 |
| 多选、填空、拖拽排序、整题绘制在 Canvas 上 | 未实现这些题型，也没有截图定位点击功能 |
| 图片只作为 CSS 背景，或用内嵌 SVG 绘图；按钮用网站私有样式表示选中 | 无法可靠提取图意或核验选中状态，需针对该页面适配 |

## 模型、权限与数据

- 服务逐题读取配置，同名系统环境变量优先。只使用所选服务商的密钥，费用计入相应账户。
- Edge 通过 `activeTab` 和 `scripting` 在你点击图标后读取当前标签页。后台把当前题的文字、选项及配图传给监听在 `127.0.0.1:8766` 的本机服务，由服务向选定的 API 地址发请求。发送的内容不含整页截图、作业网址或登录 Cookie。
- Git 忽略 `.env`，仓库提供的 `.env.example` 只包含配置示例。扩展端不保存密钥。OpenAI Responses 请求设置 `store: false`。其他服务商的数据保存策略由对应的端点和账户设置决定。

## 验证识别、速度和正确率

| 样本 | 验证内容 |
| --- | --- |
| [双题文字练习](http://127.0.0.1:8766/?case=rows) | 验证同页两题能分别识别和勾选。可在两题之间暂停，然后继续 |
| [图片练习](http://127.0.0.1:8766/?case=images) | 第一题应选「三个」蓝色圆形；第二题应选第三张图，即向左的箭头 |
| [50 道航海综合练习的源文件](samples/nautical-check/dist/) | 5 个单元，混合三种控件结构，可记录整页用时、每题耗时、正确数、错误数和未答数 |

要运行 50 题练习，保持答题服务运行，在项目根目录另开终端执行以下命令（Windows 可将 `python3` 换为 `py -3`）。

```sh
python3 -m http.server 8767 --bind 127.0.0.1 --directory samples/nautical-check/dist
```

打开[本机 50 题测验](http://127.0.0.1:8767/)，先点页面上的「开始计时」，再点扩展。答满 50 题会自动停表，点「核对答案」可评分。如果从首次勾选才自动起表，统计会少算等待第一题的时间。评分答案存于样本网站；扩展作答时按 DOM 提取当前题并实时请求模型。

### 开发者验收

安装 Node.js、Playwright 和 Microsoft Edge 后，在项目根目录运行：

```sh
npm install --no-save --package-lock=false playwright
node tests/acceptance.cjs
python3 -m unittest discover -s tests
```

验收脚本启动临时本机服务和独立的 Edge 配置，从真实工具栏入口验证文字题、图片与选项映射、暂停续答、手动选项保护、页面变更和跳题行为。使用模拟模型响应，无需 API 密钥。要验证真实模型效果，请使用上面的练习页。

## 排查常见问题

| 现象 | 检查方法 |
| --- | --- |
| Edge 显示「清单文件丢失或不可读取」 | 先解压 ZIP，再选择直接包含 `manifest.json` 的 `extension/`，不要选项目根目录 |
| 点图标后看不到任何变化 | 先试本机双题练习。打不开页面时检查服务终端和端口；页面能开但始终空白时，检查密钥、模型权限、额度及 API 网络连接 |
| 练习页正常，特定网站漏题 | 确认题目已加载且尚未勾选，再对照上方兼容表。排查 DOM 时，在 Edge「检查」面板选中包住一道题的题干和全部选项的元素，右键选择「复制 → 复制 outerHTML」 |
| 更新文件后仍像旧版本 | 在 `edge://extensions/` 重新加载扩展，刷新练习页；若更新了 `server.py`，同时重启本机服务 |

## 源码导航

- [识题、分组和勾选核验](extension/recognize.js) · [逐题执行与暂停续答](extension/answer-page.js)
- [图片提取与编码](extension/question-images.js) · [工具栏入口和后台请求](extension/background.js) · [扩展清单](extension/manifest.json)
- [Python 本机服务](server.py) · [模型配置与协议适配](model_api.py) · [环境配置示例](.env.example)
- [基础练习页](samples/index.html) · [自动验收入口](tests/acceptance.cjs) · [模拟模型服务](tests/model_fixture.py)
