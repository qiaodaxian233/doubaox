// ==UserScript==
// @name         🎬 噬渊·豆包投喂(全能参考版 · @素材多图)
// @namespace    luanshi_qingshu_doubao
// @version      0.3.1
// @description  豆包/即梦 Seedance 2.0「全能参考」投喂:可直接载入"成品@prompt文件"(花期全能参考版,逐字用+按上传素材自动排配图)或四字段源(现场套@素材);多图分槽直传(分镜&场景按段号、男主/女主卡全局复用)+发送。v0.3.1:新增成品@prompt双模式解析。
// @author       乱世情书 Project
// @match        *://www.doubao.com/*
// @match        *://doubao.com/*
// @match        *://jimeng.jianying.com/*
// @match        *://*.jianying.com/*
// @match        *://dreamina.com/*
// @match        *://*.dreamina.com/*
// @grant        GM_setValue
// @grant        GM_getValue
// @run-at       document-idle
// @noframes
// ==/UserScript==

/* ============================================================
 *  ⚙ CONFIG —— 唯一需要按实时页面微调的地方
 *  脚本没反应,多半是某个选择器变了:F12 选中元素 → 改这里。
 * ============================================================ */
const SEL = {
  textarea : 'textarea.semi-input-textarea',          // 发消息输入框
  sendBtn  : '#flow-end-msg-send',                    // 发送按钮
  fileInput: 'input[type="file"]',                    // 上传用的文件 input(可能隐藏)
  uploadMenuText: '上传文件或图片',                    // 没找到 fileInput 时点这个菜单项唤出它
};

/* 角色判断关键词(花期默认 男主/女主)。换别的项目:把下面两个词改成你源里的主角称呼即可,
 * 例如《噬渊》可改 { male:'黎尘', female:'' }(female 留空表示该项目无此角色)。*/
const ROLE_KW = { male: '男主', female: '女主' };

(function () {
  'use strict';
  if (window.top !== window.self) return;

  const DEFAULT_SOURCE = "# 示例源（四字段模式）\n\n# 段1 ·《示例·四字段》· 白天 · 预告片：不加\n\"主体描述\":\"这是四字段源示例。请用 载入.md 导入你的《花期全能参考版》(成品@prompt) 或四字段源。\"\n\"镜头语言\":\"中景示例镜头。\"\n\"环境光影\":\"白天柔光示例。\"\n\"画质修饰\":\"8K超高清,电影级。\"\n";

  const store = {
    get: (k, d) => { try { const v = GM_getValue(k); return v === undefined ? d : v; } catch (e) { return d; } },
    set: (k, v) => { try { GM_setValue(k, v); } catch (e) {} },
  };
  let SOURCE = store.get('src', DEFAULT_SOURCE);
  let MODE   = store.get('mode', 'mark');

  // @素材职责文案(可在 storage 改)
  const ATXT = store.get('atxt', {
    board : '参考分镜构图与镜头顺序节奏',
    male  : '锁定男主角色（五官/发型/服饰一致）',
    female: '锁定女主角色（御姐气质/微卷长发，五官/服饰一致）',
    scene : '参考场景（按本段地点与光线）',
  });
  // 头部(运镜/时长/比例)与约束(负面),{时长} 会被替换
  let HEADBASE = store.get('headbase',
    '电影级国漫风格动画CG、电影级动画质感，动态运镜、{时长}，16:9，8K。');
  let NEG = store.get('neg',
    '约束：画面不要出现任何摄影机/录像设备/取景框；不要写实真人脸；不要乱码、错误文字、水印 logo；不要低幼卡通/欧美魔幻风/机甲赛博风；不要人物崩坏、多余手指肢体、重复画面。16:9。');

  let EP = '1';
  let SEGS = [];
  // 全能参考四槽
  let BOARD = {};                 // 段号 -> File(分镜线稿)  按段号配
  let SCENE = {};                 // 段号 -> File(场景图)    按段号配
  let CARD  = { male: null, female: null };  // 男主卡/女主卡  全局复用
  let OVR   = {};                 // 段号 -> { male?:bool, female?:bool } 手动覆盖角色出场

  /* ---------- 解析(双模式:成品@prompt文件 / 四字段源) ---------- */
  // 取成品 @prompt(段内代码块,且含 @图 或 画面:)
  function pickPrompt(block) {
    const mm = block.match(/```[^\n]*\n([\s\S]*?)\n?```/);
    if (!mm) return null;
    const body = mm[1].trim();
    return (/@图|画面[：:]/.test(body)) ? body : null;
  }
  // 从「上传素材：图1＝分镜；图2＝男主卡；…」解析配图角色顺序
  function pickUploadKeys(block) {
    const mm = block.match(/上传素材[：:]\s*([^\n]+)/);
    if (!mm) return null;
    const keys = [];
    mm[1].split(/[；;]/).forEach(it => {
      if (!it.trim()) return;
      if (/分镜/.test(it)) keys.push('board');
      else if (/场景/.test(it)) keys.push('scene');   // 先判场景:"男主书桌场景图"含"男主"但其实是场景
      else if (/男主/.test(it)) keys.push('male');
      else if (/女主/.test(it)) keys.push('female');
      else keys.push('scene');
    });
    return keys.length ? keys : null;
  }
  // 没有上传素材行时,从 prompt 里的 @图N 文案兜底推角色
  function inferKeys(prompt) {
    const keys = []; let m; const re = /@图\d+\s*([^，,。\n]+)/g;
    while ((m = re.exec(prompt))) { const t = m[1];
      if (/分镜/.test(t)) keys.push('board');
      else if (/场景/.test(t)) keys.push('scene');   // 先判场景,同上
      else if (/男主/.test(t)) keys.push('male');
      else if (/女主/.test(t)) keys.push('female'); }
    return keys.length ? keys : ['board', 'scene'];
  }
  function parse(text) {
    const epM = text.match(/第\s*(\d+)\s*集/); EP = epM ? epM[1] : '1';
    const headRe = /^#+[^\n]*《([^》]+)》[^\n]*$/gm;
    const heads = []; let m;
    while ((m = headRe.exec(text))) heads.push({ title: m[1].trim(), line: m[0], end: headRe.lastIndex, start: m.index });
    const out = [];
    for (let i = 0; i < heads.length; i++) {
      const h = heads[i];
      const block = text.slice(h.end, i + 1 < heads.length ? heads[i + 1].start : text.length);
      const numM = h.line.match(/段\s*(\d+)/); const num = numM ? +numM[1] : out.length + 1;
      const scope = h.line + '\n' + block; let trailer = '不加';
      if (/一镜|不快切|不加\s*预告片|预告片\s*[:：]\s*不加/.test(scope)) trailer = '不加';
      else if (/预告片/.test(scope)) trailer = '加';
      // ① 成品 @prompt 模式(花期全能参考版这种)
      const prompt = pickPrompt(block);
      if (prompt) {
        const roleKeys = pickUploadKeys(block) || inferKeys(prompt);
        out.push({ num, title: h.title, trailer, mode: 'prebuilt', prompt, roleKeys });
        continue;
      }
      // ② 四字段源模式(噬渊这种,现场套 @素材)
      const get = k => { const mm = block.match(new RegExp('"' + k + '"\\s*:\\s*"([^"]*)"')); return mm ? mm[1].trim() : ''; };
      const zhuti = get('主体描述');
      if (!zhuti) continue;
      out.push({ num, title: h.title, trailer, mode: 'fourfield', f: {
        主体描述: zhuti, 镜头语言: get('镜头语言'), 环境光影: get('环境光影'), 画质修饰: get('画质修饰') } });
    }
    out.sort((a, b) => a.num - b.num);
    return out;
  }

  /* ---------- 角色出场判断 ---------- */
  function hasRole(seg, which) {
    if (OVR[seg.num] && which in OVR[seg.num]) return OVR[seg.num][which];
    const kw = ROLE_KW[which]; if (!kw) return false;
    const f = seg.f || {};
    return new RegExp(kw).test((f.主体描述 || '') + (f.镜头语言 || ''));
  }
  // 配图角色顺序:成品段照「上传素材」固定;四字段段按出场动态(可被 OVR 手动开关)
  function roleKeysOf(seg) {
    if (seg.mode === 'prebuilt') return seg.roleKeys || ['board', 'scene'];
    const r = ['board'];
    if (hasRole(seg, 'male'))   r.push('male');
    if (hasRole(seg, 'female')) r.push('female');
    r.push('scene');
    return r;
  }
  function roleFile(seg, key) {
    if (key === 'board') return BOARD[seg.num];
    if (key === 'scene') return SCENE[seg.num];
    if (key === 'male')  return CARD.male;
    if (key === 'female')return CARD.female;
    return null;
  }

  /* ---------- 生成 / 取用 prompt ---------- */
  function build(seg) {
    if (seg.mode === 'prebuilt') return seg.prompt;   // 成品 @prompt 直接逐字用
    const keys = roleKeysOf(seg);
    const atLine = keys.map((k, i) => '@图' + (i + 1) + ' ' + ATXT[k]).join('，') + '。';
    const inc = MODE === 'all' ? true : MODE === 'none' ? false : seg.trailer === '加';
    const clip = inc ? '10秒电影预告片（可快切蒙太奇）' : '10秒一镜到底（舒缓推进，不要快切）';
    const head = HEADBASE.replace('{时长}', clip);
    const labels = { 主体描述: '画面：', 镜头语言: '镜头：', 环境光影: '光影氛围：' };
    const story = ['主体描述', '镜头语言', '环境光影']
      .filter(k => seg.f[k]).map(k => labels[k] + seg.f[k]).join('\n');
    return atLine + '\n' + head + '\n' + story + '\n' + NEG;
  }
  // 该段按 @顺序应附的图 + 缺哪些
  function fileList(seg) {
    const keys = roleKeysOf(seg); const files = []; const miss = [];
    keys.forEach((k, i) => { const f = roleFile(seg, k); if (f) files.push(f); else miss.push('图' + (i + 1) + k); });
    return { files, miss };
  }

  /* ---------- 文件选择(挂 DOM 再点,保证弹窗) ---------- */
  function pickFiles({ accept, multiple, asText }, cb) {
    const inp = document.createElement('input');
    inp.type = 'file'; if (accept) inp.accept = accept; inp.multiple = !!multiple;
    inp.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0;width:1px;height:1px';
    document.body.appendChild(inp);
    const cleanup = () => { try { inp.remove(); } catch (e) {} };
    inp.addEventListener('change', () => {
      const files = [...inp.files];
      if (asText && files[0]) { const r = new FileReader(); r.onload = () => { cb([{ name: files[0].name, text: r.result }]); cleanup(); }; r.readAsText(files[0], 'utf-8'); }
      else { cb(files); cleanup(); }
    }, { once: true });
    setTimeout(() => { window.addEventListener('focus', function f() { window.removeEventListener('focus', f); setTimeout(() => { if (!inp.files.length) cleanup(); }, 500); }); }, 0);
    inp.click();
  }
  // 按文件名开头数字(或文件名含段标题)配段号,写进 target{num:File}
  function matchByNum(files, target) {
    let n = 0;
    for (const f of files) {
      if (!/\.(png|jpe?g|webp|gif|bmp)$/i.test(f.name)) continue;
      const mm = f.name.match(/^\s*0*(\d+)/); let key = mm ? +mm[1] : null;
      if (key == null || !SEGS.find(s => s.num === key)) { const seg = SEGS.find(s => f.name.includes(s.title)); if (seg) key = seg.num; }
      if (key != null) { target[key] = f; n++; }
    }
    return n;
  }

  /* ---------- 操作页面 ---------- */
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  function setNativeValue(el, value) {
    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }
  function fill(text) {
    const ta = document.querySelector(SEL.textarea);
    if (!ta) { toast('✗ 没找到输入框(改 CONFIG.SEL.textarea)'); return false; }
    ta.focus(); setNativeValue(ta, text); return true;
  }
  // 一次附多张(全能参考):一个 DataTransfer 塞全部图 → 设 input.files → change
  async function attachMany(files) {
    if (!files || !files.length) return true;
    let inp = document.querySelector(SEL.fileInput);
    if (!inp) {
      const mi = [...document.querySelectorAll('[role="menuitem"],div,button,span')]
        .find(e => e.children.length === 0 && e.textContent && e.textContent.trim() === SEL.uploadMenuText)
        || [...document.querySelectorAll('[role="menuitem"]')].find(e => e.textContent.includes(SEL.uploadMenuText));
      if (mi) { mi.click(); await sleep(450); inp = document.querySelector(SEL.fileInput); }
    }
    if (!inp) { toast('✗ 没找到上传入口,请手动上传配图'); return false; }
    if (!inp.multiple) { try { inp.multiple = true; } catch (e) {} }
    const dt = new DataTransfer(); files.forEach(f => dt.items.add(f)); inp.files = dt.files;
    inp.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  }
  function send() {
    const b = document.querySelector(SEL.sendBtn);
    if (!b) { toast('✗ 没找到发送键(改 CONFIG.SEL.sendBtn)'); return false; }
    if (b.getAttribute('aria-disabled') === 'true' || b.dataset.disabled === 'true') { toast('⚠ 发送键未就绪(内容可能没填上)'); return false; }
    b.click(); return true;
  }
  async function fillSend(seg) {
    fill(build(seg));
    const { files, miss } = fileList(seg);
    if (files.length) { await sleep(220); await attachMany(files); await sleep(1700); }
    if (miss.length) toast('⚠ 第' + seg.num + '段缺图未传:' + miss.join(' / '));
    await sleep(500); send();
  }

  /* ---------- UI ---------- */
  let toastT;
  function toast(msg) {
    let t = document.getElementById('sy-toast');
    if (!t) { t = document.createElement('div'); t.id = 'sy-toast'; document.body.appendChild(t);
      t.style.cssText = 'position:fixed;left:50%;bottom:96px;transform:translateX(-50%);background:#161b22;color:#e6edf3;border:1px solid #2a323d;padding:8px 14px;border-radius:10px;font-size:13px;z-index:2147483647;box-shadow:0 8px 30px rgba(0,0,0,.5);transition:opacity .2s'; }
    t.textContent = msg; t.style.opacity = '1';
    clearTimeout(toastT); toastT = setTimeout(() => t.style.opacity = '0', 2100);
  }

  const css = `
  #sy-panel{position:fixed;right:18px;bottom:18px;width:354px;max-height:78vh;display:flex;flex-direction:column;
    background:#0f1115;color:#e6edf3;border:1px solid #2a323d;border-radius:14px;z-index:2147483646;
    font:13px/1.5 "PingFang SC","Microsoft YaHei",sans-serif;box-shadow:0 12px 40px rgba(0,0,0,.55)}
  #sy-panel,#sy-panel *{box-sizing:border-box}
  #sy-panel.min{height:46px;max-height:46px;overflow:hidden}
  #sy-hd{display:flex;align-items:center;gap:8px;padding:11px 12px;cursor:move;background:#161b22;border-bottom:1px solid #2a323d;user-select:none;flex:0 0 auto}
  #sy-hd b{font-family:"Songti SC",serif;letter-spacing:.5px}
  #sy-hd .sp{flex:1}
  #sy-hd button{cursor:pointer;background:transparent;border:0;color:#8b96a5;font-size:16px;line-height:1;padding:0 4px}
  #sy-body{padding:11px 12px;overflow:auto;display:flex;flex-direction:column;gap:10px}
  .sy-row{display:flex;gap:7px;flex-wrap:wrap;align-items:center}
  .sy-btn{cursor:pointer;border:1px solid #2f8f79;background:linear-gradient(180deg,#4cc3a8,#2f8f79);color:#06231d;font-weight:700;border-radius:8px;padding:6px 11px;font-size:12px;white-space:nowrap}
  .sy-btn.g{background:transparent;color:#4cc3a8;border-color:#2a323d;font-weight:600}
  .sy-btn.s{padding:4px 9px;font-size:11px}
  .sy-btn:hover{filter:brightness(1.08)}
  #sy-panel select{background:#1b212b;color:#e6edf3;border:1px solid #2a323d;border-radius:7px;padding:5px 8px;font:inherit;cursor:pointer}
  #sy-src{width:100%;height:130px!important;min-height:130px;resize:vertical;background:#1b212b;color:#e6edf3;border:1px solid #2a323d;border-radius:8px;padding:8px;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11px}
  .sy-seg{border:1px solid #2a323d;border-radius:9px;padding:8px 9px;background:#161b22}
  .sy-seg .t{display:flex;align-items:center;gap:6px;margin-bottom:6px;flex-wrap:wrap}
  .sy-no{color:#4cc3a8;font-weight:700;font-family:"Songti SC",serif}
  .sy-chip{font-size:10px;padding:1px 7px;border-radius:99px;border:1px solid #2a323d;color:#8b96a5}
  .sy-chip.add{color:#d9a441;border-color:rgba(217,164,65,.5);background:rgba(217,164,65,.08)}
  .sy-chip.ok{color:#06231d;background:#4cc3a8;border-color:#4cc3a8;font-weight:700}
  .sy-chip.miss{color:#e06c75;border-color:rgba(224,108,117,.5)}
  .sy-chip.off{opacity:.45;text-decoration:line-through}
  .sy-chip.tog{cursor:pointer}
  .sy-mut{color:#8b96a5;font-size:11px}
  .sy-divider{height:1px;background:#2a323d;margin:1px 0}
  `;
  const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);

  const panel = document.createElement('div'); panel.id = 'sy-panel';
  panel.innerHTML = `
    <div id="sy-hd"><b>🎬 噬渊·全能参考投喂</b><span class="sp"></span>
      <button id="sy-min" title="收起/展开">▁</button></div>
    <div id="sy-body">
      <div class="sy-row">
        <button class="sy-btn" id="sy-load">📁 载入 .md</button>
        <button class="sy-btn g" id="sy-demo">内置示例</button>
        <button class="sy-btn g" id="sy-paste">粘贴源</button>
        <span class="sy-mut" id="sy-srcname"></span>
      </div>
      <textarea id="sy-src" style="display:none" placeholder="粘贴源内容,再点『解析』"></textarea>
      <div class="sy-row" id="sy-srcrow" style="display:none">
        <button class="sy-btn" id="sy-parse">解析</button>
        <button class="sy-btn g" id="sy-cancel">取消</button>
      </div>
      <div class="sy-divider"></div>
      <div class="sy-row">
        <span class="sy-mut">预告片</span>
        <select id="sy-mode">
          <option value="mark">按每段标记</option>
          <option value="all">全部加</option>
          <option value="none">全部不加</option>
        </select>
        <span class="sy-mut" id="sy-cnt"></span>
      </div>
      <div class="sy-divider"></div>
      <div class="sy-mut">全能参考配图(四槽):分镜&场景按段号配、男主/女主卡全局复用</div>
      <div class="sy-row">
        <button class="sy-btn s" id="sy-board">① 分镜(多选)</button>
        <button class="sy-btn s" id="sy-scene">④ 场景图(多选)</button>
      </div>
      <div class="sy-row">
        <button class="sy-btn s g" id="sy-male">② 男主卡</button>
        <button class="sy-btn s g" id="sy-female">③ 女主卡</button>
        <button class="sy-btn s g" id="sy-imgclr">清空配图</button>
      </div>
      <div class="sy-mut" id="sy-imgcnt"></div>
      <div class="sy-divider"></div>
      <div id="sy-list" style="display:flex;flex-direction:column;gap:8px"></div>
      <div class="sy-mut">载入《花期全能参考版》这类成品@prompt文件→逐字用、并按"上传素材"行自动排配图顺序(成品段标"成品prompt"、角色固定不可切);载入四字段源→现场套@素材、男/女标签可点切换。分镜/场景文件名开头数字配段号(06_xx.png→第6段)或含段标题。配图/发送失灵就 F12 对 CONFIG.SEL。</div>
    </div>`;
  document.body.appendChild(panel);

  const $ = s => panel.querySelector(s);
  function cardState() { return (CARD.male ? 1 : 0) + (CARD.female ? 1 : 0); }
  function renderList() {
    $('#sy-mode').value = MODE;
    $('#sy-cnt').textContent = SEGS.length ? '共' + SEGS.length + '段' : '';
    $('#sy-imgcnt').innerHTML =
      '分镜 <b style="color:#4cc3a8">' + Object.keys(BOARD).length + '</b> 张 · 场景 <b style="color:#4cc3a8">' + Object.keys(SCENE).length + '</b> 张 · '
      + '男主卡 ' + (CARD.male ? '<b style="color:#4cc3a8">✓</b>' : '<span style="color:#e06c75">✗</span>')
      + ' · 女主卡 ' + (CARD.female ? '<b style="color:#4cc3a8">✓</b>' : '<span style="color:#e06c75">✗</span>');
    const list = $('#sy-list'); list.innerHTML = '';
    if (!SEGS.length) { list.innerHTML = '<div class="sy-mut">点「📁 载入.md」选你的源,或「内置示例」。</div>'; return; }
    SEGS.forEach(s => {
      const keys = roleKeysOf(s);
      const inc = MODE === 'all' ? true : MODE === 'none' ? false : s.trailer === '加';
      const trailerChip = s.mode === 'prebuilt'
        ? '<span class="sy-chip add">成品prompt</span>'
        : (inc ? '<span class="sy-chip add">预告片</span>' : '<span class="sy-chip">一镜</span>');
      // 只显示该段实际用到的角色;四字段段 男/女 可点切换,成品段不可切
      const stateCls = (k, f) => !keys.includes(k) ? 'off' : (f ? 'ok' : 'miss');
      const tog = k => s.mode !== 'prebuilt' ? (' tog" data-role="' + k + '"') : '"';
      const chips =
        '<span class="sy-chip ' + stateCls('board', BOARD[s.num]) + '" title="分镜">分</span>' +
        '<span class="sy-chip ' + stateCls('male', CARD.male) + tog('male') + ' title="男主">男</span>' +
        '<span class="sy-chip ' + stateCls('female', CARD.female) + tog('female') + ' title="女主">女</span>' +
        '<span class="sy-chip ' + stateCls('scene', SCENE[s.num]) + '" title="场景">场</span>';
      const row = document.createElement('div'); row.className = 'sy-seg';
      row.innerHTML = '<div class="t"><span class="sy-no">第' + s.num + '段</span>《' + s.title + '》' + trailerChip + chips + '</div>'
        + '<div class="sy-row">'
        + '<button class="sy-btn g" data-act="fill">填入</button>'
        + '<button class="sy-btn g" data-act="copy">复制</button>'
        + '<button class="sy-btn" data-act="go">填入+发送</button>'
        + '</div>';
      row.querySelector('[data-act=fill]').onclick = () => { if (fill(build(s))) toast('已填入 第' + s.num + '段'); };
      row.querySelector('[data-act=copy]').onclick = () => { (navigator.clipboard && navigator.clipboard.writeText(build(s))); toast('已复制 第' + s.num + '段'); };
      row.querySelector('[data-act=go]').onclick = () => fillSend(s);
      row.querySelectorAll('.sy-chip.tog').forEach(c => c.onclick = () => {
        const role = c.dataset.role; const cur = hasRole(s, role);
        OVR[s.num] = OVR[s.num] || {}; OVR[s.num][role] = !cur; renderList();
      });
      list.appendChild(row);
    });
  }
  function reparse() { SEGS = parse(SOURCE); renderList(); }

  $('#sy-load').onclick = () => pickFiles({ accept: '.md,.txt,text/plain,text/markdown', asText: true }, arr => {
    if (!arr[0]) return; SOURCE = arr[0].text; store.set('src', SOURCE);
    $('#sy-srcname').textContent = arr[0].name; reparse(); toast('已载入 ' + arr[0].name);
  });
  $('#sy-demo').onclick = () => { SOURCE = DEFAULT_SOURCE; store.set('src', SOURCE); $('#sy-srcname').textContent = '内置示例'; reparse(); toast('已载入内置示例'); };
  $('#sy-paste').onclick = () => { $('#sy-src').style.display = 'block'; $('#sy-srcrow').style.display = 'flex'; $('#sy-src').value = SOURCE; };
  $('#sy-cancel').onclick = () => { $('#sy-src').style.display = 'none'; $('#sy-srcrow').style.display = 'none'; };
  $('#sy-parse').onclick = () => { SOURCE = $('#sy-src').value; store.set('src', SOURCE); $('#sy-cancel').click(); reparse(); toast('已解析'); };
  $('#sy-mode').onchange = e => { MODE = e.target.value; store.set('mode', MODE); renderList(); };
  $('#sy-min').onclick = () => panel.classList.toggle('min');

  // 四槽上传
  $('#sy-board').onclick = () => pickFiles({ accept: 'image/*', multiple: true }, files => {
    const n = matchByNum(files, BOARD); toast(n ? '已配 ' + n + ' 张分镜(命中段号)' : '没匹配上:文件名开头数字要对应段号'); renderList();
  });
  $('#sy-scene').onclick = () => pickFiles({ accept: 'image/*', multiple: true }, files => {
    const n = matchByNum(files, SCENE); toast(n ? '已配 ' + n + ' 张场景图(命中段号)' : '没匹配上:文件名开头数字要对应段号'); renderList();
  });
  $('#sy-male').onclick = () => pickFiles({ accept: 'image/*', multiple: false }, files => {
    if (files[0]) { CARD.male = files[0]; toast('已设男主卡:' + files[0].name); renderList(); }
  });
  $('#sy-female').onclick = () => pickFiles({ accept: 'image/*', multiple: false }, files => {
    if (files[0]) { CARD.female = files[0]; toast('已设女主卡:' + files[0].name); renderList(); }
  });
  $('#sy-imgclr').onclick = () => { BOARD = {}; SCENE = {}; CARD = { male: null, female: null }; renderList(); toast('已清空全部配图'); };

  // 拖动
  (function () {
    const hd = $('#sy-hd'); let sx, sy, ox, oy, drag = false;
    hd.addEventListener('mousedown', e => { if (e.target.tagName === 'BUTTON') return; drag = true; sx = e.clientX; sy = e.clientY;
      const r = panel.getBoundingClientRect(); ox = r.left; oy = r.top; e.preventDefault(); });
    document.addEventListener('mousemove', e => { if (!drag) return;
      panel.style.left = (ox + e.clientX - sx) + 'px'; panel.style.top = (oy + e.clientY - sy) + 'px';
      panel.style.right = 'auto'; panel.style.bottom = 'auto'; });
    document.addEventListener('mouseup', () => drag = false);
  })();

  reparse();
  console.log('[噬渊·全能参考投喂] v0.3.1 已加载,解析出', SEGS.length, '段');
})();
