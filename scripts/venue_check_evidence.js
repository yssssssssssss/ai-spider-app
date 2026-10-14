/* Screenshot coordinates always refer to the original image, including manual marks. */
const CheckEvidence = (() => {
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
  const storageKey = 'official-venue-check-annotations-v1';
  let annotations = [], storageAvailable = true, current = null, drag = null;
  try { const saved = JSON.parse(localStorage.getItem(storageKey) || '[]'); if (Array.isArray(saved)) annotations = saved; }
  catch { storageAvailable = false; }
  const validBox = (box, size) => Array.isArray(box) && box.length === 4 && box.every(Number.isFinite) &&
    box[0] >= 0 && box[1] >= 0 && box[0] < box[2] && box[1] < box[3] && box[2] <= size[0] && box[3] <= size[1];
  const identity = (venue, rule, item) => JSON.stringify([venue.venue_id, venue.project_id, rule, item.file, item.sha256]);
  function stored(venue, rule, item) {
    const found = annotations.find(entry => entry && entry.key === identity(venue, rule, item));
    return (Array.isArray(found?.boxes_px) ? found.boxes_px : []).filter(box => validBox(box, item.image_size));
  }
  function marksSvg(item, marks, manual = []) {
    const color = ({fail:'#dc2626',pass:'#16804a',uncertain:'#b77908',not_applicable:'#64748b'})[current?.check.status] || '#64748b';
    return marks.map(mark => {
      const stroke = mark.color || color, label = `<title>${escape(mark.label)}</title>`;
      if (mark.kind === 'line') return `<line x1="${mark.start_px[0]}" y1="${mark.start_px[1]}" x2="${mark.end_px[0]}" y2="${mark.end_px[1]}" stroke="${stroke}" stroke-width="2" vector-effect="non-scaling-stroke" ${mark.dashed ? 'stroke-dasharray="7 4"' : ''}>${label}</line>`;
      const [x,y,r,b] = mark.bbox_px;
      return `<rect x="${x}" y="${y}" width="${r-x}" height="${b-y}" fill="${mark.filled ? stroke : 'none'}" fill-opacity="0.12" stroke="${stroke}" stroke-width="1.5" vector-effect="non-scaling-stroke">${label}</rect>`;
    }).join('') + manual.map(([x,y,r,b]) => `<rect class="manual-mark" x="${x}" y="${y}" width="${r-x}" height="${b-y}" fill="#7c3aed" fill-opacity="0.07" stroke="#7c3aed" stroke-dasharray="6 3" stroke-width="2" vector-effect="non-scaling-stroke"><title>人工补充框选</title></rect>`).join('');
  }
  function imageView(item, manual, full = false) {
    const [x,y,r,b] = full ? [0,0,...item.image_size] : item.crop_px;
    const width = r-x, height = b-y;
    const style = `aspect-ratio:${width}/${height};` + (full ? '' : `width:min(100%,${Math.min(360,300*width/height)}px);`);
    return `<div class="evidence-image" style="${style}"><img ${full ? '' : 'loading="lazy"'} src="${escape(item.file)}" width="${item.image_size[0]}" height="${item.image_size[1]}" alt="${escape(item.label)}" draggable="false" style="width:${100*item.image_size[0]/width}%;left:${-100*x/width}%;top:${-100*y/height}%"><span class="evidence-load-state">截图加载中</span><svg viewBox="${x} ${y} ${width} ${height}" aria-label="检查区域标注">${marksSvg(item,item.marks,manual)}</svg></div>`;
  }
  function render(check, venue, details) {
    if (!details?.items?.length) return '';
    const saved = details.items.some(item => stored(venue,check.rule_id,item).length);
    const localized = details.items.some(item => item.marks.length);
    // A temporary color context for rendering only. No screenshot or verdict is modified.
    const previous = current; current = {check};
    const content = `<details class="check-evidence" data-evidence-state="${escape(details.state)}" ${localized ? 'open' : ''}><summary>细节截图与框选 · ${localized ? '已有定位标注' : '暂无局部定位'}${saved ? ' · 有本机人工标注' : ''}</summary>${details.note ? `<p class="evidence-note">${escape(details.note)}</p>` : ''}<div class="evidence-grid">${details.items.map((item,index) => `<figure><button type="button" class="evidence-open" data-venue="${escape(venue.record_id)}" data-rule="${escape(check.rule_id)}" data-item="${index}" aria-label="放大并框选 ${escape(check.rule_id)} ${escape(item.label)}">${imageView(item,stored(venue,check.rule_id,item))}</button><figcaption>${escape(item.label)}</figcaption><div class="evidence-actions"><button type="button" class="evidence-open" data-venue="${escape(venue.record_id)}" data-rule="${escape(check.rule_id)}" data-item="${index}">放大 / 框选</button><a href="${escape(item.file)}" target="_blank" rel="noopener">查看原图</a></div></figure>`).join('')}</div></details>`;
    current = previous;
    return content;
  }
  function save() {
    annotations = annotations.filter(entry => entry?.key !== identity(current.venue,current.check.rule_id,current.item));
    if (current.manual.length) annotations.push({key:identity(current.venue,current.check.rule_id,current.item), venue_id:current.venue.venue_id,
      venue_name:current.venue.venue_name, project_id:current.venue.project_id, rule_id:current.check.rule_id,
      file:current.item.file, screenshot_sha256:current.item.sha256, image_size:current.item.image_size, boxes_px:current.manual,
      rule_version:data.rule_version, updated_at:new Date().toISOString()});
    try { localStorage.setItem(storageKey,JSON.stringify(annotations)); storageAvailable = true; }
    catch { storageAvailable = false; }
    update();
    refreshInline();
  }
  function refreshInline() {
    const row = data.results.find(r => r.venue.record_id === current.venue.record_id);
    for (const card of document.querySelectorAll("#cards .card")) {
      if (card.dataset.venueId !== current.venue.venue_id) continue;
      for (const check of card.querySelectorAll(".check")) {
        if (check.dataset.ruleId !== current.check.rule_id) continue;
        const previous = check.querySelector(".check-evidence"), holder = document.createElement("div");
        if (!previous) continue;
        holder.innerHTML = render(current.check,current.venue,row.check_evidence[current.check.rule_id]);
        const next = holder.firstElementChild; next.open = previous.open; previous.replaceWith(next);
      }
    }
  }
  let dialog, stage, info, toggle, undo, showMarks, status, zoom;
  function update() {
    const view = stage.querySelector('.evidence-image'), svg = view.querySelector('svg');
    svg.innerHTML = marksSvg(current.item,showMarks.checked ? current.item.marks : [],current.manual) +
      (drag?.box ? marksSvg(current.item,[],[drag.box]) : '');
    view.classList.toggle('drawing',toggle.getAttribute('aria-pressed') === 'true');
    undo.disabled = !current.manual.length;
    status.textContent = `${current.manual.length} 个人工框选 · ${storageAvailable ? '自动保存在当前浏览器' : '本机存储不可用，请导出保存'}`;
    info.textContent = current.manual.map((box,i) => `人工框 ${i+1}：[${box.join(', ')}]`).join('；');
  }
  function point(event) {
    const rect = stage.querySelector('.evidence-image').getBoundingClientRect(), [width,height] = current.item.image_size;
    return [Math.round(Math.max(0,Math.min(width,(event.clientX-rect.left)*width/rect.width))),
      Math.round(Math.max(0,Math.min(height,(event.clientY-rect.top)*height/rect.height)))];
  }
  function setup() {
    for (const event of ['load','error']) document.addEventListener(event, e => {
      if (!(e.target instanceof HTMLImageElement)) return;
      const view = e.target.closest('.evidence-image'); if (!view) return;
      view.classList.toggle('image-ready',event === 'load');
      if (event === 'error') view.querySelector('.evidence-load-state').textContent = '截图加载失败，请查看原图';
    },true);
    dialog = document.createElement('dialog'); dialog.id = 'evidence-viewer';
    dialog.innerHTML = `<div class="viewer-heading"><h2 id="viewer-title"></h2><button type="button" id="viewer-close">关闭</button></div><p id="viewer-label"></p><div class="viewer-tools"><button type="button" id="viewer-draw" aria-pressed="false">新增框选</button><button type="button" id="viewer-undo">撤销人工框选</button><label><input type="checkbox" id="viewer-marks" checked>显示审核标注</label><label>截图倍率 <select id="viewer-zoom"><option value="1">适应宽度</option><option value="2">2倍</option><option value="3">3倍</option></select></label><a id="viewer-original" target="_blank" rel="noopener">查看原图</a></div><p class="muted">开启“新增框选”后在截图上拖动。紫色虚线为人工补充，保存在当前浏览器；导出标注可交接给他人，审核结论不会自动改变。</p><p id="viewer-status" aria-live="polite"></p><div id="viewer-stage"></div><p id="viewer-boxes"></p>`;
    document.body.append(dialog); stage = dialog.querySelector('#viewer-stage'); info = dialog.querySelector('#viewer-boxes');
    toggle = dialog.querySelector('#viewer-draw'); undo = dialog.querySelector('#viewer-undo'); showMarks = dialog.querySelector('#viewer-marks'); status = dialog.querySelector('#viewer-status'); zoom = dialog.querySelector('#viewer-zoom');
    dialog.querySelector('#viewer-close').onclick = () => dialog.close();
    dialog.addEventListener('cancel',() => {drag = null;});
    dialog.addEventListener('close',() => {current = null; drag = null;});
    toggle.onclick = () => {toggle.setAttribute('aria-pressed',String(toggle.getAttribute('aria-pressed') !== 'true')); update();};
    undo.onclick = () => {current.manual.pop(); save();}; showMarks.onchange = update;
    zoom.onchange = () => {
      const image = stage.querySelector('.evidence-image'), scale = Number(zoom.value);
      image.style.width = `${current.item.image_size[0]*scale}px`; image.style.maxWidth = scale === 1 ? '100%' : 'none';
      stage.scrollTop = stage.scrollLeft = 0;
    };
    stage.addEventListener('pointerdown',event => {
      if (!current || !dialog.open || !event.target.closest('.evidence-image') || toggle.getAttribute('aria-pressed') !== 'true' || event.button !== 0 || drag) return;
      const image = stage.querySelector('img'); if (!image.complete || !image.naturalWidth) return;
      event.preventDefault(); drag = {pointer:event.pointerId,start:point(event),box:null}; stage.setPointerCapture(event.pointerId);
    });
    stage.addEventListener('pointermove',event => {
      if (!current || !dialog.open || !drag || drag.pointer !== event.pointerId) return;
      const end = point(event), [x,y] = drag.start;
      const box = [Math.min(x,end[0]),Math.min(y,end[1]),Math.max(x,end[0]),Math.max(y,end[1])];
      drag.box = validBox(box,current.item.image_size) ? box : null; update();
    });
    stage.addEventListener('pointerup',event => {
      if (!current || !dialog.open || !drag || drag.pointer !== event.pointerId) return;
      const end = point(event), [x,y] = drag.start, box = [Math.min(x,end[0]),Math.min(y,end[1]),Math.max(x,end[0]),Math.max(y,end[1])];
      drag = null; stage.releasePointerCapture(event.pointerId);
      if (validBox(box,current.item.image_size) && box[2]-box[0] >= 2 && box[3]-box[1] >= 2) {current.manual.push(box); save();} else update();
    });
    for (const event of ['pointercancel','lostpointercapture']) stage.addEventListener(event,() => {drag = null; if (current) update();});
    document.addEventListener('click',event => {
      const button = event.target.closest('button.evidence-open'); if (!button) return;
      const row = data.results.find(r => r.venue.record_id === button.dataset.venue);
      const check = row?.audit?.checks.find(c => c.rule_id === button.dataset.rule), item = row?.check_evidence?.[button.dataset.rule]?.items[Number(button.dataset.item)];
      if (!check || !item) return;
      current = {venue:row.venue,check,item,manual:stored(row.venue,check.rule_id,item)}; drag = null;
      dialog.querySelector('#viewer-title').textContent = `${row.venue.venue_name} · ${check.rule_id} ${check.title}`;
      dialog.querySelector('#viewer-label').textContent = item.label;
      dialog.querySelector('#viewer-original').href = item.file;
      stage.innerHTML = imageView(item,current.manual,true); showMarks.checked = true; toggle.setAttribute('aria-pressed','false');
      zoom.value = '1'; dialog.showModal(); update(); stage.scrollTop = stage.scrollLeft = 0;
    });
    const exportButton = document.createElement('button'); exportButton.type = 'button'; exportButton.id = 'export-annotations'; exportButton.textContent = '导出人工标注';
    exportButton.onclick = () => {
      const entries = data.results.flatMap(row => Object.entries(row.check_evidence || {}).flatMap(([rule,details]) => details.items.flatMap(item => {
        const boxes = stored(row.venue,rule,item); return boxes.length ? [{venue_name:row.venue.venue_name,venue_id:row.venue.venue_id,project_id:row.venue.project_id,rule_id:rule,
          file:item.file,screenshot_sha256:item.sha256,image_size:item.image_size,boxes_px:boxes}] : [];
      })));
      const blob = new Blob([JSON.stringify({schema_version:1,rule_version:data.rule_version,exported_at:new Date().toISOString(),coordinate_system:'original_screenshot_pixels',annotations:entries},null,2)],{type:'application/json'});
      const url = URL.createObjectURL(blob), link = document.createElement('a'); link.href = url; link.download = 'venue-check-annotations.json'; link.click(); setTimeout(() => URL.revokeObjectURL(url),1000);
    };
    document.querySelector('.controls').append(exportButton);
  }
  return {render,setup};
})();
