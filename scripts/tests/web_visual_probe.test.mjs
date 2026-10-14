import assert from "node:assert/strict";
import {probeWebVisual} from "../web_visual_probe.mjs";

/** Run in Ego Lite with an agent-owned Page; returns the facts used by the assertions. */
export async function validateWebVisual(page) {
  await page.goto(new URL("../../backend/tests/fixtures/visual_measurement.html", import.meta.url).href);
  await page.cdp("Emulation.setDeviceMetricsOverride", {width:390, height:844, deviceScaleFactor:1, mobile:false});
  const result = await probeWebVisual(page, {
    targets: [
      {id:"first", selector:"#first"}, {id:"second", selector:"#second"},
      {id:"hidden", selector:"#hidden"}, {id:"transparent", selector:"#transparent"},
      {id:"visibility-override", selector:"#visibility-override"}, {id:"transformed", selector:"#transformed"},
      {id:"offscreen", selector:"#offscreen"}, {id:"partial", selector:"#partial"},
      {id:"side", selector:"#side"}, {id:"many", selector:".card"},
      {id:"missing", selector:"#missing"}, {id:"invalid", selector:"["},
    ],
    distances: [
      {id:"gap", first:"first", second:"second", axis:"vertical"},
      {id:"reversed", first:"second", second:"first", axis:"vertical"},
      {id:"hidden-gap", first:"first", second:"hidden", axis:"vertical"},
      {id:"not-aligned", first:"first", second:"side", axis:"vertical"},
    ],
  });
  const elements = Object.fromEntries(result.elements.map(e => [e.id, e]));
  const distances = Object.fromEntries(result.distances.map(e => [e.id, e]));
  assert.equal(elements.first.computed_style.color, "rgb(17, 20, 26)");
  assert.equal(elements.first.computed_style["background-color"], "rgb(255, 255, 255)");
  assert.equal(elements.first.computed_style["border-top-left-radius"], "12px");
  assert.equal(distances.gap.distance_css_px, 24);
  assert.equal(result.design_unit_calibration, "not_provided");
  assert.equal(elements.hidden.status, "hidden");
  assert.equal(elements.transparent.status, "hidden");
  assert.equal(elements["visibility-override"].status, "measured");
  assert.equal(elements.transformed.ancestor_transform_present, true);
  assert.equal(elements.offscreen.status, "outside_viewport");
  assert.equal(elements.partial.status, "partly_outside_viewport");
  assert.equal(elements.many.status, "ambiguous_selector");
  assert.equal(elements.missing.status, "not_found");
  assert.equal(elements.invalid.status, "invalid_selector");
  assert.equal(distances.reversed.status, "reversed_targets");
  assert.equal(distances["hidden-gap"].status, "needs_visible_targets");
  assert.equal(distances["not-aligned"].status, "no_perpendicular_overlap");
  return {validation_mode:"known_css_fixture", verified_assertions:17, result};
}
