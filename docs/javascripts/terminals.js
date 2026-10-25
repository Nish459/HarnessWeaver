/*
 * Play the docs' `console` code blocks as typed terminal sessions (ADR-0042).
 *
 * Material renders a ```console block as <div class="language-console highlight">
 * with the session's text in a <code> element. For each one, this builds a termynal
 * terminal in its place: a line that starts with "$ " is typed as a command, and
 * every other line appears as its output. Each terminal starts playing when it
 * scrolls into view, so a reader sees it from the beginning, and a "replay" link
 * plays it again.
 *
 * The original block stays in the page when JavaScript is off, and it is kept
 * (never animated) for readers who ask for reduced motion.
 */

(function () {
  "use strict";

  /*
   * One element per line of the session: a command to type, or output to show.
   * Termynal reads lines from its container's [data-ty] children. (Its lineData
   * option builds the attributes without spaces, so it isn't used.) Setting
   * textContent keeps the text as text: nothing in it is parsed as HTML.
   */
  function lineElements(text) {
    return text.replace(/\n$/, "").split("\n").map(function (line) {
      var span = document.createElement("span");
      if (line.startsWith("$ ")) {
        span.setAttribute("data-ty", "input");
        span.setAttribute("data-ty-delay", "500");
        span.textContent = line.slice(2);
      } else {
        span.setAttribute("data-ty", "");
        span.setAttribute("data-ty-delay", "60");
        span.textContent = line;
      }
      return span;
    });
  }

  /* Replace one code block with a terminal that plays once it is visible. */
  function makeTerminal(block) {
    var code = block.querySelector("code");
    if (!code) {
      return;
    }
    var text = code.textContent;
    var wrapper = document.createElement("div");
    wrapper.className = "hw-terminal";
    var screen = document.createElement("div");
    var replay = document.createElement("a");
    replay.className = "hw-terminal__replay";
    replay.href = "#";
    replay.textContent = "replay";
    wrapper.appendChild(screen);
    wrapper.appendChild(replay);
    block.replaceWith(wrapper);

    /* Each play gets a fresh screen: a replay while the last one is still typing
       leaves that one writing into a detached element nobody sees. */
    function play() {
      var fresh = document.createElement("div");
      lineElements(text).forEach(function (line) { fresh.appendChild(line); });
      wrapper.replaceChild(fresh, screen);
      screen = fresh;
      new Termynal(screen, { typeDelay: 35, lineDelay: 60, startDelay: 300 });
    }
    replay.addEventListener("click", function (event) {
      event.preventDefault();
      play();
    });

    var seen = new IntersectionObserver(function (entries) {
      if (entries.some(function (entry) { return entry.isIntersecting; })) {
        seen.disconnect();
        play();
      }
    });
    seen.observe(wrapper);
  }

  function setUp() {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      return;
    }
    document.querySelectorAll("div.language-console").forEach(makeTerminal);
  }

  /* Material's document$ fires on every page load, including instant navigation. */
  if (typeof document$ !== "undefined") {
    document$.subscribe(setUp);
  } else {
    document.addEventListener("DOMContentLoaded", setUp);
  }
})();
