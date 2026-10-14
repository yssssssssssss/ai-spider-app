/** Read only the explicitly selected DOM elements through an Ego Lite Page. */
export async function probeWebVisual(page, {targets, distances = []}) {
  if (!Array.isArray(targets) || !targets.length) throw new Error("targets must be a nonempty array");
  const ids = new Set();
  for (const target of targets) {
    if (!target || typeof target.id !== "string" || !target.id.trim() ||
        typeof target.selector !== "string" || !target.selector.trim() || ids.has(target.id)) {
      throw new Error("targets need unique nonempty ids and CSS selectors");
    }
    ids.add(target.id);
  }
  const distanceIds = new Set();
  if (!Array.isArray(distances)) throw new Error("distances must be an array");
  for (const distance of distances) {
    if (!distance || typeof distance.id !== "string" || !distance.id.trim() || distanceIds.has(distance.id) ||
        !ids.has(distance.first) || !ids.has(distance.second) ||
        !["vertical", "horizontal"].includes(distance.axis)) {
      throw new Error("distances need unique ids, existing targets, and a vertical/horizontal axis");
    }
    distanceIds.add(distance.id);
  }
  return page.evaluate(({targets, distances}) => {
    const rect = (box) => ({left: box.left, top: box.top, right: box.right, bottom: box.bottom,
                            width: box.width, height: box.height});
    const properties = ["color", "background-color", "background-image", "font-family", "font-size",
                        "font-weight", "line-height", "border-top-left-radius", "border-top-right-radius",
                        "border-bottom-left-radius", "border-bottom-right-radius", "margin-top", "margin-right",
                        "margin-bottom", "margin-left", "padding-top", "padding-right", "padding-bottom",
                        "padding-left", "row-gap", "column-gap", "box-shadow", "filter", "mix-blend-mode"];
    const elements = targets.map(({id, selector}) => {
      let matches;
      try { matches = document.querySelectorAll(selector); }
      catch { return {id, selector, status: "invalid_selector"}; }
      if (matches.length !== 1) return {id, selector, status: matches.length ? "ambiguous_selector" : "not_found", match_count: matches.length};
      const element = matches[0], box = element.getBoundingClientRect(), style = getComputedStyle(element);
      let opacity = 1, hidden = style.visibility !== "visible", hasTransform = false;
      for (let node = element; node; node = node.parentElement) {
        const computed = getComputedStyle(node);
        opacity *= Number(computed.opacity);
        hidden ||= computed.display === "none" || computed.contentVisibility === "hidden";
        hasTransform ||= computed.transform !== "none";
      }
      hidden ||= opacity === 0 || box.width <= 0 || box.height <= 0;
      const viewport = window.visualViewport;
      const left = viewport?.offsetLeft ?? 0, top = viewport?.offsetTop ?? 0;
      const right = left + (viewport?.width ?? innerWidth), bottom = top + (viewport?.height ?? innerHeight);
      const intersects = box.right > left && box.left < right && box.bottom > top && box.top < bottom;
      const inside = box.left >= left && box.right <= right && box.top >= top && box.bottom <= bottom;
      return {id, selector, status: hidden ? "hidden" : !intersects ? "outside_viewport" : inside ? "measured" : "partly_outside_viewport",
              element_tag: element.tagName.toLowerCase(), rect_css_px: rect(box),
              effective_opacity: opacity, ancestor_transform_present: hasTransform,
              computed_style: Object.fromEntries(properties.map(key => [key, style.getPropertyValue(key)])),
              occlusion_checked: false, rendered_pixel_color_verified: false};
    });
    const measured = new Map(elements.map(item => [item.id, item]));
    const gaps = distances.map(({id, first, second, axis}) => {
      const a = measured.get(first), b = measured.get(second);
      if (![a, b].every(item => item.status === "measured")) {
        return {id, first, second, axis, status: "needs_visible_targets"};
      }
      const x = a.rect_css_px, y = b.rect_css_px, vertical = axis === "vertical";
      if ((vertical ? y.top < x.top : y.left < x.left)) return {id, first, second, axis, status: "reversed_targets"};
      if ((vertical ? Math.min(x.right, y.right) - Math.max(x.left, y.left) :
                      Math.min(x.bottom, y.bottom) - Math.max(x.top, y.top)) <= 0) {
        return {id, first, second, axis, status: "no_perpendicular_overlap"};
      }
      const gap = vertical ? y.top - x.bottom : y.left - x.right;
      return {id, first, second, axis, status: "measured", distance_css_px: gap,
              relationship: gap > 0 ? "gap" : gap === 0 ? "touching" : "overlap",
              method: "rendered_dom_border_box_edges", semantic_boundary_verified: false};
    });
    return {schema_version: 1, mode: "web_computed_style_and_geometry", audit_verdict: "not_evaluated",
            source: {url_without_query: location.origin + location.pathname, title: document.title, measured_at: new Date().toISOString(),
                     viewport_css_px: {width: innerWidth, height: innerHeight}, device_pixel_ratio: devicePixelRatio,
                     visual_viewport: window.visualViewport ? {width: visualViewport.width, height: visualViewport.height,
                       scale: visualViewport.scale, offset_left: visualViewport.offsetLeft, offset_top: visualViewport.offsetTop} : null,
                     scroll_css_px: {x: scrollX, y: scrollY}},
            design_unit_calibration: "not_provided", elements, distances: gaps};
  }, {targets, distances});
}
