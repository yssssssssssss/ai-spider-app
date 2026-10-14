// Set globalThis.venueCapture = { VENUE_SPACE, VENUE_ROOT, ... } before loading in Ego Lite.
// VENUE_MODE=catalog collects QR pixels; the default captures verified entries.
const fs = await import("node:fs/promises");
const path = await import("node:path");
const crypto = await import("node:crypto");
const { execFileSync } = await import("node:child_process");
const options = globalThis.venueCapture || process.env;
if (!options.VENUE_SPACE || !options.VENUE_ROOT) {
  throw new Error("VENUE_SPACE and VENUE_ROOT are required");
}
const root = path.resolve(options.VENUE_ROOT);
const task = await taskSpace(Number(options.VENUE_SPACE));
const python = options.VENUE_PYTHON || "python3";
const verify = (repair = false) => {
  const args = [options.VENUE_HELPER || path.resolve("scripts/venue_identity.py"), "--root", root];
  if (repair) args.push("--repair-links");
  console.log(execFileSync(python, args, { encoding: "utf8" }).trim());
};
const atomic = async (file, value) => {
  await fs.writeFile(file + ".tmp", JSON.stringify(value, null, 2) + "\n");
  await fs.rename(file + ".tmp", file);
};
const read = async (file) => JSON.parse(await fs.readFile(file, "utf8"));
const exists = async (file) => {
  try { await fs.access(file); return true; } catch { return false; }
};
const entryIdentity = (url) => {
  const u = new URL(url), match = u.pathname.match(/^\/service\/preview\/mall\/active\/([^/]+)\/(\d+)$/);
  if (u.origin !== "https://babelserv.m.jd.com" || !match || !u.searchParams.get("pageId")) {
    throw new Error("Invalid preview navigation URL");
  }
  return [match[1], match[2], u.searchParams.get("pageId")].join("/");
};
const checkedNavigation = (url, expected) => {
  const u = new URL(url);
  const login = u.origin === "https://plogin.m.jd.com" && ["/login/login", "/login/nopassword"].includes(u.pathname);
  const target = login ? u.searchParams.get("returnurl") : url;
  const targetUrl = target ? new URL(target) : null;
  const publicMatch = targetUrl?.pathname.match(/^\/mall\/active\/([^/]+)\/index.html$/);
  const publicLogin = login && targetUrl?.origin === "https://pro.m.jd.com" && publicMatch;
  const matches = publicLogin ? publicMatch[1] === entryIdentity(expected).split("/")[0] : target && entryIdentity(target) === entryIdentity(expected);
  if (!matches) throw new Error("NavigationReachedAnotherVenue");
  // Location redirects can append account address data; retain only entry parameters.
  const allowed = new Set(["source", "endpoint", "pageId", "forward", "cms", "has_native", "insertDebugFloor", "migrateToMall", "preventPV", "forceCurrentView"]);
  for (const key of [...targetUrl.searchParams.keys()]) if (!allowed.has(key)) targetUrl.searchParams.delete(key);
  if (login) { u.search = ""; u.searchParams.set("returnurl", targetUrl.href); }
  return { url: login ? u.href : targetUrl.href, status: login ? "login_required" : "verified_entry" };
};

if (options.VENUE_MODE === "catalog") {
  if (await exists(path.join(root, "catalog.json"))) throw new Error("Choose a new catalog directory");
  const page = task.page("p1");
  await fs.mkdir(path.join(root, "qrcodes"), { recursive: true });
  const state = () => {
    const table = [...document.querySelectorAll("table")].find(t => t.innerText.includes("会场名称/ID/通天塔项目ID"));
    const rows = [...table.querySelectorAll("tr")].map(tr => {
      const cells = [...tr.querySelectorAll(":scope > td")], text = cells[0]?.innerText.trim();
      const id = text?.match(/\bRA\d+/)?.[0];
      if (!id) return null;
      return { venue_name: text.split("\n")[0].trim(), venue_id: id,
        project_id: text.match(/通天塔项目ID[:：]\s*(\d+)/)?.[1], identity_cell: text,
        official_url: cells[1]?.querySelector("a[href]")?.href || null,
        launch_period: cells[2]?.innerText.trim(), end_time: cells[3]?.innerText.trim(),
        whitelist_indicator: text.includes("已加白"), qr: cells[4]?.querySelector("canvas")?.toDataURL() };
    }).filter(Boolean);
    return { page: Number(document.querySelector(".ant-acore-pagination-item-active")?.innerText),
      next_disabled: document.querySelector(".ant-acore-pagination-next")?.getAttribute("aria-disabled") === "true",
      preview_time: [...document.querySelectorAll("a")].find(a => a.innerText.includes("预览时间："))?.innerText.trim(), rows };
  };
  const catalog = { schema_version: 1, source_url: await page.url(), started_at: new Date().toISOString(), pages: [], venues: [] };
  for (let turn = 0; turn < 100; turn++) {
    await page.waitForFunction(() => !document.querySelector(".ant-acore-spin-spinning"), undefined, { timeout: 15000 });
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const s = await page.evaluate(state);
    if (!s.preview_time || !s.rows.length || s.rows.some(r => !r.qr || !r.project_id)) throw new Error("QR or identity missing");
    if (catalog.pages.some(p => p.page === s.page)) throw new Error("Repeated catalog page");
    for (const [index, row] of s.rows.entries()) {
      const id = `p${String(s.page).padStart(2, "0")}-r${String(index + 1).padStart(2, "0")}-${row.venue_id}`;
      row.record_id = id; row.source_page = s.page; row.source_row = index + 1;
      row.preview_time = s.preview_time; row.collected_at = new Date().toISOString();
      row.qr_file = `qrcodes/${id}.png`;
      await fs.writeFile(path.join(root, row.qr_file), Buffer.from(row.qr.split(",")[1], "base64"));
      delete row.qr; catalog.venues.push(row);
    }
    catalog.pages.push({ page: s.page, row_count: s.rows.length });
    await atomic(path.join(root, "catalog.json"), catalog);
    if (s.next_disabled) break;
    const fingerprint = s.rows.map(r => r.venue_id).join(",");
    await page.click("li.ant-acore-pagination-next button");
    await page.waitForFunction(({ previous, next }) => {
      const table = [...document.querySelectorAll("table")].find(t => t.innerText.includes("会场名称/ID/通天塔项目ID"));
      const ids = [...table.querySelectorAll("tr")].map(tr => tr.querySelector("td")?.innerText.match(/\bRA\d+/)?.[0]).filter(Boolean).join(",");
      return Number(document.querySelector(".ant-acore-pagination-item-active")?.innerText) === next && ids && ids !== previous && !document.querySelector(".ant-acore-spin-spinning");
    }, { previous: fingerprint, next: s.page + 1 }, { timeout: 15000 });
    if (turn === 99) throw new Error("Catalog pagination did not finish");
  }
  verify(true); // URL comes from rendered QR pixels, never React Fiber internals.
} else {
  verify();
  const catalog = await read(path.join(root, "catalog.json"));
  const entries = new Map((await read(path.join(root, "identity-verification.json"))).entries.map(e => [e.record_id, e]));
  const selected = options.VENUE_RECORDS_FILE ? (await read(options.VENUE_RECORDS_FILE)).record_ids : catalog.venues.map(v => v.record_id);
  if (new Set(selected).size !== selected.length || selected.some(id => !entries.has(id))) throw new Error("Unknown or duplicate capture selection");
  const state = () => {
    const imgs = [...document.images].filter(i => { const r = i.getBoundingClientRect(); return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth; });
    return { width: innerWidth, height: innerHeight, scroll_y: scrollY, scroll_height: document.scrollingElement.scrollHeight,
      pending_visible_images: imgs.filter(i => !i.complete).length, broken_visible_images: imgs.filter(i => i.complete && !i.naturalWidth).length,
      page_text: document.body.innerText.slice(0, 1800) };
  };
  const settle = async (page) => {
    let timedOut = false;
    try {
      await page.waitForFunction(() => {
        const images = [...document.images].filter(i => { const r = i.getBoundingClientRect(); return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight; });
        return document.readyState === "complete" && (document.body.innerText.trim().length > 10 || images.some(i => i.naturalWidth > 0)) && images.every(i => i.complete);
      }, undefined, { timeout: 12000 });
    } catch { timedOut = true; }
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    return { ...(await page.evaluate(state)), load_wait_timed_out: timedOut };
  };
  for (const venue of catalog.venues.filter(v => selected.includes(v.record_id))) {
    const folder = path.join(root, "venues", venue.record_id);
    if (await exists(path.join(folder, "audit.json"))) throw new Error(`Archive old audit before recapture: ${venue.record_id}`);
    await fs.mkdir(folder, { recursive: true });
    const capture = { schema_version: 1, venue, capture_started_at: new Date().toISOString(),
      viewport: { width: 390, height: 844, device_scale_factor: 1 }, user_agent_mode: "desktop_browser_with_mobile_dimensions",
      identity_verification: entries.get(venue.record_id), screens: [], navigation_errors: [] };
    // Isolate documents inside the same task space; delayed redirects cannot affect the next venue.
    const page = await task.newPage();
    await page.cdp("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: false });
    try {
      try {
        await page.goto(venue.preview_url, { waitUntil: "domcontentloaded", timeout: 30000 });
      } catch (error) { capture.navigation_errors.push(error.message); }
      await settle(page);
      if (await page.evaluate(() => { const e = document.querySelector(".warning-close"); return !!e && e.getBoundingClientRect().width > 0; })) await page.click(".warning-close");
      let navigation = checkedNavigation(await page.url(), venue.preview_url);
      capture.navigation_url = navigation.url; capture.navigation_status = navigation.status;
      await page.evaluate(() => window.scrollTo(0, 0));
      for (const number of [1, 2]) {
        if (number === 2) await page.evaluate(() => window.scrollTo(0, Math.min(844, Math.max(0, document.scrollingElement.scrollHeight - innerHeight))));
        let current = await settle(page);
        for (let attempt = 0; number === 2 && attempt < 3; attempt++) {
          const target = Math.min(844, Math.max(0, current.scroll_height - 844));
          if (Math.abs(current.scroll_y - target) < 1) break;
          await page.evaluate(y => window.scrollTo(0, y), target); current = await settle(page);
        }
        if (current.width !== 390 || current.height !== 844) throw new Error("ViewportMismatch");
        checkedNavigation(await page.url(), venue.preview_url);
        const file = `venues/${venue.record_id}/screen-${number}.png`;
        await page.screenshot({ path: path.join(root, file) });
        navigation = checkedNavigation(await page.url(), venue.preview_url);
        capture.navigation_url = navigation.url; capture.navigation_status = navigation.status;
        const bytes = await fs.readFile(path.join(root, file));
        if (bytes.readUInt32BE(16) !== 390 || bytes.readUInt32BE(20) !== 844) throw new Error("ScreenshotDimensionsMismatch");
        capture.screens.push({ number, file, width: 390, height: 844, scroll_y: current.scroll_y,
          scroll_height: current.scroll_height, pending_visible_images: current.pending_visible_images,
          broken_visible_images: current.broken_visible_images, load_wait_timed_out: current.load_wait_timed_out,
          sha256: crypto.createHash("sha256").update(bytes).digest("hex"), captured_at: new Date().toISOString() });
        if (number === 1) { capture.page_title = await page.title(); capture.first_screen_text = current.page_text; }
      }
      capture.capture_status = capture.screens.some(s => s.load_wait_timed_out || s.pending_visible_images > 0) ? "partial" : "success";
      capture.two_screen_scroll_reached = capture.screens[1].scroll_y === 844;
    } catch (error) { capture.capture_status = "failed"; capture.error_type = error.message; }
    capture.capture_completed_at = new Date().toISOString();
    await atomic(path.join(folder, "capture.json"), capture);
    console.log(JSON.stringify({ stage: "captured", record_id: venue.record_id, status: capture.capture_status, title: capture.page_title, screens: capture.screens.length }));
    if (/Inspected target navigated|Not attached to an active page/.test(capture.error_type || "")) {
      throw new Error(`Page attachment changed; inspect ${page.label} in a new Ego round before retrying ${venue.record_id}`);
    }
    await page.close();
  }
}
