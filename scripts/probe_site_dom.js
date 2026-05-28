// ════════════════════════════════════════════════════════════════════
// doubaox 站点 DOM 探查脚本
// 用法:在豆包 / 即梦 / GPT 镜像 等页面登录后,F12 → Console 粘贴回车
//      输出会自动复制到剪贴板,粘给 Claude 用来更新 site_profiles.py
// ════════════════════════════════════════════════════════════════════

(async function probe() {
  const out = {
    backend: location.hostname,
    url: location.href,
    title: document.title,
    suggestions: {},
  };

  // ─── 1. 输入框候选 ───────────────────────────────────
  // 找所有可见的 textarea / contenteditable
  const inputCandidates = [];
  document.querySelectorAll('textarea, [contenteditable="true"]').forEach(el => {
    const rect = el.getBoundingClientRect();
    if (rect.width < 100 || rect.height < 20) return;   // 太小跳过
    const sel = uniqueSelector(el);
    inputCandidates.push({
      selector: sel,
      tag: el.tagName,
      id: el.id || '',
      testid: el.getAttribute('data-testid') || '',
      aria: el.getAttribute('aria-label') || '',
      placeholder: el.getAttribute('placeholder') || '',
      sizeOk: rect.width >= 200,
    });
  });
  out.suggestions.input_box = inputCandidates;

  // ─── 2. 发送按钮候选 ────────────────────────────────
  const sendCandidates = [];
  document.querySelectorAll('button').forEach(btn => {
    const text = (btn.innerText || '').trim();
    const aria = btn.getAttribute('aria-label') || '';
    const testid = btn.getAttribute('data-testid') || '';
    const score = (
      /send|发送|生成|提交/i.test(text + aria + testid) ? 3 :
      btn.querySelector('svg') ? 1 : 0
    );
    if (score >= 1) {
      sendCandidates.push({
        selector: uniqueSelector(btn),
        text: text.slice(0, 30),
        aria, testid,
        disabled: btn.disabled,
        score,
      });
    }
  });
  sendCandidates.sort((a, b) => b.score - a.score);
  out.suggestions.send_btn = sendCandidates.slice(0, 8);

  // ─── 3. 文件上传 input ─────────────────────────────
  const uploadCandidates = [];
  document.querySelectorAll('input[type="file"]').forEach(el => {
    uploadCandidates.push({
      selector: uniqueSelector(el),
      id: el.id || '',
      multiple: el.multiple,
      accept: el.accept || '',
      hidden: el.offsetParent === null,
    });
  });
  out.suggestions.upload_btn = uploadCandidates;

  // ─── 4. 附件 / 上传 触发按钮(点了会弹文件选择)──────
  const attachBtns = [];
  document.querySelectorAll('button, [role="button"]').forEach(btn => {
    const aria = btn.getAttribute('aria-label') || '';
    const testid = btn.getAttribute('data-testid') || '';
    if (/attach|upload|附加|上传|添加文件/i.test(aria + testid)) {
      attachBtns.push({
        selector: uniqueSelector(btn),
        aria, testid,
      });
    }
  });
  out.suggestions.attach_trigger = attachBtns;

  // ─── 5. 已生成的图(找页面里所有 src 不是 data: 的 img)─
  const imgs = [];
  const seenSrcDomains = new Set();
  document.querySelectorAll('img').forEach(img => {
    const src = img.src || '';
    if (!src || src.startsWith('data:') || src.length < 20) return;
    try {
      const dom = new URL(src).hostname;
      if (!seenSrcDomains.has(dom)) {
        seenSrcDomains.add(dom);
        imgs.push({
          domain: dom,
          srcSample: src.slice(0, 100),
          natural: `${img.naturalWidth}x${img.naturalHeight}`,
        });
      }
    } catch (e) {}
  });
  out.suggestions.image_domains = imgs;

  // ─── 6. 已生成的视频 ─────────────────────────────
  const videos = [];
  document.querySelectorAll('video').forEach(v => {
    const src = v.src || (v.querySelector('source') || {}).src || '';
    videos.push({ src: src.slice(0, 100) });
  });
  out.suggestions.video_elements = videos;

  // ─── 7. 消息容器(用于 result_selector)──────────────
  // 找所有带 data-testid 或 data-message-author-role 的容器
  const msgContainers = new Map();
  document.querySelectorAll('[data-message-author-role], [data-testid*="message"]').forEach(el => {
    const role = el.getAttribute('data-message-author-role') || '';
    const testid = el.getAttribute('data-testid') || '';
    const key = `role=${role}|testid=${testid}`;
    msgContainers.set(key, (msgContainers.get(key) || 0) + 1);
  });
  out.suggestions.message_containers = [...msgContainers.entries()].map(([k, count]) => ({ pattern: k, count }));

  // ─── 工具:为单个元素生成稳定选择器 ─────────────
  function uniqueSelector(el) {
    if (el.id) return '#' + CSS.escape(el.id);
    const testid = el.getAttribute('data-testid');
    if (testid) return `[data-testid="${testid}"]`;
    const aria = el.getAttribute('aria-label');
    if (aria) return `${el.tagName.toLowerCase()}[aria-label="${aria}"]`;
    // 兜底:tag + class 第一个
    let s = el.tagName.toLowerCase();
    if (el.className && typeof el.className === 'string') {
      const cls = el.className.split(/\s+/).filter(Boolean)[0];
      if (cls) s += '.' + CSS.escape(cls);
    }
    return s;
  }

  const json = JSON.stringify(out, null, 2);

  // 复制到剪贴板
  try {
    await navigator.clipboard.writeText(json);
    console.log('%c✓ 探查结果已复制到剪贴板 — 粘给 Claude', 'color:#0d9488;font-weight:bold');
  } catch (e) {
    console.log('%c⚠ 剪贴板写入失败,手动复制下面输出', 'color:#dc5a3a');
  }

  console.log(json);
  return out;
})();
