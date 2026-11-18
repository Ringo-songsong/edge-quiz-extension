// Copy only images already associated with this question's DOM controls.
globalThis.encodeQuestionImages ??= (() => {
  function decode(image) {
    let timer;
    return Promise.race([
      image.decode(),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("图片加载超时")), 4000); })
    ]).finally(() => clearTimeout(timer));
  }

  function rasterize(image) {
    const width = image.naturalWidth, height = image.naturalHeight;
    if (!width || !height) throw new Error("图片尚未加载");
    const scale = Math.min(1, 1800 / Math.max(width, height));
    const canvas = image.ownerDocument.createElement("canvas");
    canvas.width = Math.max(1, Math.round(width * scale));
    canvas.height = Math.max(1, Math.round(height * scale));
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "white";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
    // Keep fine diagram lines lossless when possible. Bound photos separately.
    let data = canvas.toDataURL("image/png");
    if (data.length > 1024 * 1024) data = canvas.toDataURL("image/jpeg", 0.86);
    if (data.length > 1024 * 1024) data = canvas.toDataURL("image/jpeg", 0.70);
    if (data.length > 1024 * 1024 || data === "data:,") throw new Error("图片过大或无法读取");
    return data;
  }

  async function encode(node) {
    const src = node.currentSrc || node.src;
    if (!src) throw new Error("图片地址为空");
    if (!node.complete && node.loading !== "lazy") await decode(node);
    if (node.complete && node.naturalWidth) {
      try { return rasterize(node); }
      catch (error) { if (error.name !== "SecurityError") throw error; }
    }
    // An eager copy handles off-screen lazy images and CORS-enabled image hosts.
    const copy = node.ownerDocument.createElement("img");
    const url = new URL(src);
    if (url.origin !== node.ownerDocument.location.origin && /^https?:$/.test(url.protocol)) {
      copy.crossOrigin = "anonymous";
    }
    copy.referrerPolicy = node.referrerPolicy;
    copy.src = src;
    await decode(copy);
    return rasterize(copy);
  }

  return async (images, running) => {
    const encoded = [];
    let size = 0;
    for (const {part, node} of images) {
      if (!running()) throw new Error("作答已暂停");
      const data = await encode(node);
      size += data.length;
      if (size > 6 * 1024 * 1024) throw new Error("本题图片总量过大");
      encoded.push({part, data});
    }
    return encoded;
  };
})();
