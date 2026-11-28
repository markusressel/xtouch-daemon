/*
 * The words of the configuration in their colors, as the GUI's help shows them (`help_text` in
 * src/xtouch_daemon/gui/quick/window/rich.py; keep the two in line): states and modes violet, channels and what else a
 * slot can show (pools, people, applications) teal, slots orange, `present` (presence) yellow, the controls of the
 * device (Select, Mute, the fader, ...) in the color of the text. Their sections and the pools in `code` too
 * (`[state.gaming]`, `channel.out`, `apps`); not `auto`, which is also the value of an override. Code blocks, links
 * and headings stay as they are. The colors are in stylesheets/extra.css.
 */

// lower case or capitalized, not any case: "Select" is a button, "select" a verb
const capitalized = (words) => words.map((word) => `[${word[0].toUpperCase()}${word[0]}]${word.slice(1)}`).join("|");
const ENTITY_WORDS = capitalized(["states?", "modes?", "channels?", "pools?", "slots?", "people", "persons?", "applications?"]);
const CONTROL_WORDS = `Select|Mute|Solo|Rec|${capitalized(["faders?", "encoders?"])}|LCDs?|LED rings?`;
const WORDS = new RegExp(`\\b(${ENTITY_WORDS})\\b|\\b(${CONTROL_WORDS})\\b`, "g");
const CODE = /^\[?(state|mode|channel|pool|people|person|apps|devices|present|slots?|controls)\b/;
const ENTITY = {
  state: "state",
  mode: "state",
  channel: "channel",
  pool: "channel",
  people: "channel",
  person: "channel",
  application: "channel",
  apps: "channel",
  devices: "channel",
  present: "presence",
  slot: "slot",
  controls: "slot",
};
const SKIP = "pre, a, h1, h2, h3, h4, h5, h6, code, .xt-entity, .xt-control";

function entity(word) {
  const lower = word.toLowerCase();
  return ENTITY[lower] ?? ENTITY[lower.replace(/s$/, "")];
}

function colorText(node) {
  const text = node.nodeValue;
  WORDS.lastIndex = 0;
  if (!WORDS.test(text)) return;
  WORDS.lastIndex = 0;
  const parts = document.createDocumentFragment();
  let last = 0;
  for (const match of text.matchAll(WORDS)) {
    parts.append(text.slice(last, match.index));
    const span = document.createElement("span");
    span.textContent = match[0];
    span.className = match[1] ? `xt-entity xt-${entity(match[1])}` : "xt-control";
    parts.append(span);
    last = match.index + match[0].length;
  }
  parts.append(text.slice(last));
  node.replaceWith(parts);
}

function colorPage() {
  const article = document.querySelector(".md-content article");
  if (!article) return;
  for (const code of article.querySelectorAll("code")) {
    if (code.closest("pre, a")) continue;
    const match = CODE.exec(code.textContent);
    if (match) code.classList.add("xt-entity", `xt-${entity(match[1])}`);
  }
  const walker = document.createTreeWalker(article, NodeFilter.SHOW_TEXT, {
    acceptNode: (node) =>
      node.parentElement.closest(SKIP) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
  });
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  nodes.forEach(colorText);
}

// with instant navigation the theme swaps the page in itself: `document$` tells each new one
if (typeof document$ !== "undefined") {
  document$.subscribe(colorPage);
} else {
  document.addEventListener("DOMContentLoaded", colorPage);
}
