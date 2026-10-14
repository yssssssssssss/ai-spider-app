// Run through ego-browser nodejs with globalThis.tabSpacingCapture configured.
const fs = await import('node:fs/promises');
const path = await import('node:path');
const crypto = await import('node:crypto');
const options = globalThis.tabSpacingCapture;
if (!options?.space || !options?.root || !options?.source) throw new Error('space, root and source are required');
const {probeWebVisual} = await import(path.join(options.project, 'scripts/web_visual_probe.mjs'));
const task = await taskSpace(options.space);
const root = path.resolve(options.root);
const source = JSON.parse(await fs.readFile(path.join(options.source, 'results.json'), 'utf8'));
const directory = path.join(root, 'spacing');
await fs.mkdir(directory, {recursive: true});
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const atomic = async (file, value) => {
  await fs.writeFile(file + '.tmp', JSON.stringify(value, null, 2) + '\n');
  await fs.rename(file + '.tmp', file);
};
const records = options.records || source.results.filter(row => row.audit.page_state === 'ready').map(row => row.venue.record_id);
const selected = source.results.filter(row => records.includes(row.venue.record_id));
if (new Set(records).size !== records.length || selected.length !== records.length) throw new Error('Unknown or duplicate records');
let cursor = 0;
async function capture(row) {
  const venue = row.venue;
  const file = path.join(directory, `${venue.venue_id}-review.json`);
  try { await fs.access(file); return; } catch {}
  const page = await task.newPage();
  let stopped = false;
  try {
    await page.cdp('Emulation.setDeviceMetricsOverride', {width: 390, height: 844, deviceScaleFactor: 1, mobile: false});
    await page.goto(venue.preview_url, {waitUntil: 'domcontentloaded', timeout: 30000});
    let settled = true;
    try {
      await page.waitForFunction(() => {
        const visible = [...document.images].filter(e => { const r = e.getBoundingClientRect(); return r.width && r.height && r.bottom > 0 && r.top < innerHeight; });
        return document.readyState === 'complete' && (document.querySelector('.tabs_bar') || document.body.innerText.includes('活动迷路了')) && visible.every(e => e.complete);
      }, undefined, {timeout: 15000});
    } catch { settled = false; }
    if (await page.evaluate(() => { const e = document.querySelector('.warning-close'); return !!e && e.getBoundingClientRect().width > 0; })) await page.click('.warning-close');
    await page.evaluate(() => window.scrollTo(0, 0));
    const structure = await page.evaluate(() => {
      const visible = e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e); return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility === 'visible'; };
      const modules = [...document.querySelectorAll('.bab_opt_mod')].filter(e => !e.parentElement.closest('.bab_opt_mod'));
      const tabs = [...document.querySelectorAll('.tabs_bar')].filter(e => visible(e) && e.closest('.bab_opt_mod.feeds'));
      const describe = e => ({classes: [...e.classList], rect: e.getBoundingClientRect().toJSON(), text: e.innerText.slice(0,180)});
      const inventory = modules.map(describe).filter(e => e.rect.top < 1688);
      if (tabs.length !== 1) return {status: 'uncertain', reason: `可见feeds分类Tab数量为${tabs.length}，不能唯一定位`, inventory};
      const tab = tabs[0], feeds = tab.closest('.bab_opt_mod.feeds'), index = modules.indexOf(feeds);
      const preceding = modules.slice(0,index).reverse();
      const upper = preceding.find(e => visible(e) && !e.classList.contains('jiange'));
      if (!upper || upper.parentElement !== feeds.parentElement) return {status:'uncertain', reason:'上方模块与feeds未形成可核验的同级楼层关系', inventory};
      const token = e => [...e.classList].find(c => /^module_\d+$/.test(c) && document.querySelectorAll(`.bab_opt_mod.${c}`).length === 1);
      const a = token(upper), b = token(feeds);
      if (!a || !b) return {status:'uncertain', reason:'未取得唯一楼层选择器', inventory};
      const between = modules.slice(modules.indexOf(upper)+1,index).filter(visible);
      const clear = between.every(e => e.classList.contains('jiange')) && !/楼层异常|该楼层未修改异常/.test(upper.innerText);
      const label = upper.classList.contains('daCuTouTu') ? '头图' : upper.classList.contains('flexcubeCoupon') ? '权益券包' : upper.classList.contains('hotzone') ? '热区模块' : upper.classList.contains('SsrCodeTemplate') ? '自定义业务模块' : '上方业务模块';
      return {status:'located', upper_selector:`.bab_opt_mod.${a}`, tab_selector:`.bab_opt_mod.${b} .tabs_bar`,
        upper_module:label, semantic_boundary_verified:clear, inventory,
        semantic_review:clear ? '唯一feeds分类Tab与其同级最近可见业务楼层；中间仅有间隔组件或零高度模块。' : '上方含楼层异常提示或未辨明模块，不能认定为正常业务边界。', tab_top:tab.getBoundingClientRect().top};
    });
    if (structure.tab_top > 844) await page.evaluate(y => window.scrollTo(0,y), Math.min(844,Math.max(0,structure.tab_top-700)));
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const actual = new URL(await page.url()), expected = new URL(venue.preview_url);
    const verifiedEntry = actual.origin === expected.origin && actual.pathname === expected.pathname && actual.searchParams.get('pageId') === expected.searchParams.get('pageId');
    const screenshotFile = `spacing/${venue.venue_id}-live.png`;
    await page.screenshot({path:path.join(root,screenshotFile)});
    const bytes = await fs.readFile(path.join(root,screenshotFile));
    if (bytes.readUInt32BE(16) !== 390 || bytes.readUInt32BE(20) !== 844) throw new Error('Screenshot dimensions changed');
    const review = {venue, rule_id:'OV-009', source:'live_h5_dom_spacing', measurement_status:'uncertain',
      skip_reason:structure.reason || structure.semantic_review, screenshot_file:screenshotFile, screenshot_sha256:hash(bytes),
      evidence_bbox_px:[0,0,390,844], measured_at:new Date().toISOString(), semantic_boundary_verified:false,
      original_screen:row.capture.screens[0], settled, entry_verified:verifiedEntry};
    if (structure.status === 'located' && verifiedEntry && settled) {
      const measurement = await probeWebVisual(page, {targets:[{id:'upper-module',selector:structure.upper_selector},{id:'category-tabs',selector:structure.tab_selector}], distances:[{id:'tab-gap',first:'upper-module',second:'category-tabs',axis:'vertical'}]});
      const dom = {venue, requested_preview_url:venue.preview_url, selectors:structure, measurement};
      const domFile = `spacing/${venue.venue_id}-dom.json`;
      await atomic(path.join(root,domFile),dom);
      review.dom_file=domFile; review.dom_sha256=hash(await fs.readFile(path.join(root,domFile)));
      if (measurement.distances[0].status === 'measured') {
        const upper=measurement.elements.find(e=>e.id==='upper-module').rect_css_px;
        const tab=measurement.elements.find(e=>e.id==='category-tabs').rect_css_px;
        Object.assign(review,{measurement_status:'measured', upper_module:structure.upper_module,
          distance_css_px:measurement.distances[0].distance_css_px, upper_bottom_css_px:upper.bottom, tab_top_css_px:tab.top,
          semantic_boundary_verified:structure.semantic_boundary_verified, semantic_review:structure.semantic_review,
          device_pixel_ratio:measurement.source.device_pixel_ratio, css_px_to_screenshot_px:1,
          screenshot_export_scale:'390×844截图与390×844 CSS视口对应，按尺寸校验1:1。',
          evidence_bbox_px:[0,Math.max(0,Math.floor(Math.min(upper.bottom,tab.top)-8)),390,Math.min(844,Math.ceil(Math.max(upper.bottom,tab.top)+8))]});
      } else review.skip_reason='两屏深度内无法同时完整呈现上方模块与分类Tab的边界';
    }
    if (!verifiedEntry) review.skip_reason='当前页面未到达已核验的会场预览入口';
    if (!settled) review.skip_reason='当前H5未稳定就绪或没有可定位的分类Tab';
    await atomic(file,review);
    console.log(JSON.stringify({stage:'spacing_captured', record_id:venue.record_id, status:review.measurement_status, semantic_verified:review.semantic_boundary_verified, gap:review.distance_css_px}));
  } catch (error) {
    stopped=/control|inactive|unassigned|Not attached|Inspected target navigated/i.test(error.message);
    if (stopped) throw error;
    await atomic(file,{venue,rule_id:'OV-009',measurement_status:'uncertain',skip_reason:`实时H5测量未完成：${error.name}`,
      screenshot_file:row.capture.screens[0].file,screenshot_sha256:row.capture.screens[0].sha256,evidence_bbox_px:[0,0,390,844],semantic_boundary_verified:false});
    console.log(JSON.stringify({stage:'spacing_error',record_id:venue.record_id,error_type:error.name}));
  } finally { if (!stopped) await page.close(); }
}
await Promise.all(Array.from({length:2},async()=>{
  while(cursor < selected.length) { const row=selected[cursor++]; await capture(row); }
}));
console.log(JSON.stringify({stage:'spacing_capture_finished',selected:selected.length}));
