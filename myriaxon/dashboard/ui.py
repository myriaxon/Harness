"""The dashboard's single-page UI, served from memory.

Kept as one string so the server needs no static-file routing, no build step, and cannot 404 its own
assets. No CDN links either: a local tool that reaches out to the network to render is both slower
and a privacy problem, and the machine may be offline.

Layout follows the harness conventions people already know: session sidebar, tabbed main pane
(chat / trajectory), composer with mode control and attachments.
"""

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Myriaxon</title>
<!-- The favicon is an inline data: URI rather than a file route. A separate /favicon.ico means a
     second request, a second route to keep unauthenticated, and a 404 in the log on every load
     when it is missing -- which is what happened before. A data: URI cannot 404 and keeps the
     page genuinely self-contained, the same reason there are no CDN links below. -->
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 200 200'%3E%3Crect width='200' height='200' rx='46' fill='%230A0C11'/%3E%3Cg fill='%23EDEFF5'%3E%3Cpolygon points='100,14 106,66 100,76 94,66'/%3E%3Cpolygon points='186,100 134,106 124,100 134,94'/%3E%3Cpolygon points='100,186 94,134 100,124 106,134'/%3E%3Cpolygon points='14,100 66,94 76,100 66,106'/%3E%3Cpolygon points='100,38 104,68 100,78 96,68' transform='rotate(45 100 100)'/%3E%3Cpolygon points='100,38 104,68 100,78 96,68' transform='rotate(135 100 100)'/%3E%3Cpolygon points='100,38 104,68 100,78 96,68' transform='rotate(225 100 100)'/%3E%3Cpolygon points='100,38 104,68 100,78 96,68' transform='rotate(315 100 100)'/%3E%3Ccircle cx='100' cy='100' r='15'/%3E%3C/g%3E%3Ccircle cx='100' cy='100' r='10.5' fill='%230A0C11'/%3E%3Ccircle cx='100' cy='100' r='5.5' fill='%237CF5C8'/%3E%3C/svg%3E">
<meta name="theme-color" content="#0A0C11">
<meta name="description" content="Myriaxon — an advanced agentic harness. Ten thousand paths. One mind.">
<style>
  /* Myriaxon brand tokens. `myriaxon/brand/__init__.py` is the single source of truth for these
     values; they are mirrored here because the page is one self-contained string with no build
     step (see the module docstring), and `scripts/check_ui_markup.py` asserts the two agree.

     Both themes are declared up front and switched by a data-theme attribute on <html>, so every
     colour is one variable and nothing is hard-coded to a single appearance. The light theme is
     not the dark theme inverted -- signal green on white fails contrast, so the light accent is a
     deep teal-green from the same family. */
  :root, html[data-theme="dark"] {
    /* Tells the browser to render its own chrome -- scrollbars, and the popup list of a <select> --
       with dark defaults. Without it Windows draws that popup on a white system surface no matter
       what the page's CSS says, so dark-theme options appear as pale rows. Measured from a user's
       screenshot of the vendor dropdown: a white panel of green text. */
    color-scheme: dark;
    --ink: #0A0C11; --ink-2: #10131A; --ink-3: #171B24;
    --line: #232835; --line-2: #2E3444;
    --text: #EDEFF5; --text-2: #A3ABBD; --text-3: #7C8599;
    --signal: #7CF5C8; --signal-ink: #062A1E;
    --blue: #8FB4FF; --amber: #FFB86B; --violet: #C9A2FF; --red: #FF8A8A;
    --display: "Unbounded", "Arial Black", "Segoe UI Variable Display", system-ui, sans-serif;
    --ui: "Instrument Sans", "Inter", "Geist", "Segoe UI Variable Text", "Segoe UI", -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif;
    --mono: "JetBrains Mono", "Geist Mono", "Cascadia Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
    --wordmark-tracking: .14em;

    /* Legacy aliases. The markup and script below reference these older names in hundreds of
       places; aliasing them here means the palette can change in one block without a risky
       rewrite of every rule, and a stale name can never resolve to nothing -- which is exactly
       the bug that shipped before (an undefined --mono silently fell back to the sans font). */
    --bg: var(--ink); --panel: var(--ink-2); --panel-2: var(--ink-3); --border: var(--line);
    --muted: var(--text-2); --faint: var(--text-3);
    --accent: var(--signal); --accent-2: var(--blue);
    --accent-dim: color-mix(in srgb, var(--signal) 26%, transparent);
    --ok: var(--signal); --warn: var(--amber); --err: var(--red);
    --user: var(--ink-3); --assistant: color-mix(in srgb, var(--signal) 10%, var(--ink-2));
    --code-bg: color-mix(in srgb, var(--ink) 70%, var(--ink-2));
    --shadow: 0 8px 26px rgba(0,0,0,.5);
    --hover: var(--ink-3);
    --ok-bg: color-mix(in srgb, var(--signal) 12%, var(--ink-2));
    --ok-border: color-mix(in srgb, var(--signal) 32%, var(--line));
    --add-bg: color-mix(in srgb, var(--signal) 13%, var(--ink-2));
    --del-bg: color-mix(in srgb, var(--red) 13%, var(--ink-2));
  }
  html[data-theme="light"] {
    color-scheme: light;
    --ink: #F4F5F8; --ink-2: #FFFFFF; --ink-3: #EEF0F4;
    --line: #DDE0E7; --line-2: #C9CED9;
    --text: #0A0C11; --text-2: #3F4658; --text-3: #5A6275;
    --signal: #0B8F63; --signal-ink: #FFFFFF;
    --blue: #2F5FD0; --amber: #B25E00; --violet: #7A45D6; --red: #C62828;
  }
  * { box-sizing: border-box; }

  /* Loci's transition timings, and the asymmetry between them is the point.
     The face changes in 240ms; the lantern takes 600ms to warm up. That difference is what makes the light feel
     like it is responding to the mood rather than being switched, and it is a named requirement in the character
     spec. Declared here in the shared scope rather than inside the `.loci` rules, because `test_brand_consistency`
     resolves every `var()` against the theme blocks -- a variable defined only inside a component is invisible to
     that check, and the check is right to treat that as undefined. */
  :root, html[data-theme="dark"], html[data-theme="light"] {
    --t-face: 240ms;
    --t-lantern: 600ms;
  }
  html, body { height: 100%; margin: 0; }
  body {
    background: var(--ink); color: var(--text); font: 14px/1.55 var(--ui);
    display: flex; overflow: hidden; transition: background .15s, color .15s;
    -webkit-font-smoothing: antialiased;
  }
  :focus-visible { outline: 2px solid var(--signal); outline-offset: 2px; border-radius: 6px; }
  @media (prefers-reduced-motion: reduce) {
    * { animation: none !important; transition: none !important; }
  }
  /* ---------- Loci, the character ----------
     The mood variables come from the SVG's own manifest, so the colours are defined in one place and this stylesheet
     only decides how to use them. `.loci[data-mood=...]` is the hook: the mood rides on an attribute rather than on a
     class list, which means a face cannot be styled without naming its mood.

     The two transitions are deliberately asymmetric and the asymmetry is the spec's, not a taste call: the FACE
     changes in 240ms so it feels responsive, while the LANTERN takes 600ms so the light appears to settle rather than
     snap. A reader notices the second one without being able to say why. */
  .loci {
    --t-face: 240ms;
    --t-lantern: 600ms;
    --loci-accent: #7f9cc4;
    --loci-glow: #a9c0dd;
  }
  .loci[data-mood="calm"] { --loci-accent: #7f9cc4; --loci-glow: #a9c0dd; }
  .loci[data-mood="warm"] { --loci-accent: #e0a86b; --loci-glow: #f0c79a; }
  .loci[data-mood="bright"] { --loci-accent: #f2c14e; --loci-glow: #ffe08a; }
  .loci[data-mood="dim"] { --loci-accent: #6b7280; --loci-glow: #9aa2ae; }
  .loci[data-mood="care"] { --loci-accent: #e79ab0; --loci-glow: #f5c3d1; }
  .loci[data-mood="alert"] { --loci-accent: #7fd1c1; --loci-glow: #a9e6da; }
  .loci[data-mood="serious"] { --loci-accent: #b48ead; --loci-glow: #d4b3d0; }
  /* The fallback values are repeated in every `var()` on purpose. The declaration alone is not enough: `var(--t-face)`
     resolves to nothing at all if the declaration is ever moved, scoped, or overridden by a host page, and an empty
     duration makes the transition instantaneous rather than defaulting to something sensible. `var(--t-face, 240ms)`
     degrades to the intended value instead of to no animation. */
  .loci .loci-part { transition: transform var(--t-face, 240ms) ease, opacity var(--t-face, 240ms) ease; }
  .loci .loci-lantern, .loci [data-part="lantern"] {
    transition: opacity var(--t-lantern, 600ms) ease, transform var(--t-lantern, 600ms) ease;
  }
  /* THE RULE. A bouncing crisis face is the single rendering this project must never ship, and it is one careless
     selector away. Stated here, in the SVG's own <style>, and asserted by two verifiers, because redundancy on this
     one rule is cheaper than the failure. */
  .loci[data-expression="crisis"] * { animation: none !important; }
  .loci[data-expression="crisis"] { animation: none !important; }
  #lociAvatar { display: inline-flex; align-items: center; gap: 8px; }
  #lociAvatar svg { width: 34px; height: 34px; display: block; }
  #lociMood { color: var(--muted); font-size: 12px; }
  @media (prefers-reduced-motion: reduce) {
    .loci *, .loci { animation: none !important; transition: none !important; }
  }
  /* ---------- sidebar ---------- */
  #sidebar {
    width: 272px; flex: 0 0 272px; background: var(--panel); border-right: 1px solid var(--border);
    display: flex; flex-direction: column; height: 100vh;
  }
  .brand { padding: 13px 14px 10px; display: flex; align-items: center; gap: 10px; font-weight: 650; letter-spacing: .2px; }
  .brand .mark { flex: 0 0 auto; display: block; }
  .brand .name { font-size: 15px; }
  .brand small { color: var(--muted); font-weight: 500; font-size: 10.5px; border: 1px solid var(--border); padding: 1px 6px; border-radius: 20px; margin-left: auto; }
  .newbtn {
    margin: 6px 12px 10px; padding: 9px 12px; border-radius: 9px; border: 1px solid var(--border);
    background: var(--panel-2); color: var(--text); cursor: pointer; font-size: 13px; text-align: left;
  }
  .newbtn:hover { border-color: var(--accent); }
  .sect { padding: 8px 16px 4px; font-size: 11px; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); display: flex; align-items: center; }
  .sect .proj { margin-left: auto; text-transform: none; letter-spacing: 0; font-size: 11px; cursor: pointer; color: var(--accent); }
  #sessions { overflow-y: auto; flex: 1; padding: 0 8px 12px; }
  .sess {
    padding: 8px 10px; border-radius: 8px; cursor: pointer; color: var(--muted); font-size: 13px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: flex; align-items: center; gap: 7px;
  }
  .sess:hover { background: var(--panel-2); color: var(--text); }
  .sess.active { background: var(--user); color: var(--text); }
  .sess .busy { width: 6px; height: 6px; border-radius: 50%; background: var(--warn); flex: 0 0 6px; }
  .sess .label { flex: 1; overflow: hidden; text-overflow: ellipsis; }
  .sess .del {
    flex: 0 0 auto; opacity: 0; border: 0; background: none; color: var(--muted); cursor: pointer;
    font-size: 15px; line-height: 1; padding: 0 2px; border-radius: 5px;
  }
  .sess:hover .del { opacity: 1; }
  .sess .del:hover { color: var(--err); background: var(--panel); }
  /* A menu, not a row of buttons. Measured in a browser: seven action buttons in a row overflowed the
     sidebar and clipped the later ones (including the theme toggle) so they could not be clicked at
     all. A single burger keeps the footer one line whatever is added to it, and gives each action a
     label and a section instead of a cryptic abbreviation. */
  .sidefoot { border-top: 1px solid var(--border); padding: 8px 10px; font-size: 11px; color: var(--muted);
    position: relative; }
  .sidefoot #conn { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    margin-bottom: 6px; }
  .menubar { display: flex; align-items: center; gap: 8px; }
  .menubtn { border: 1px solid var(--border); background: var(--panel-2); color: var(--text);
    border-radius: 8px; width: 32px; height: 28px; cursor: pointer; font-size: 14px; line-height: 1;
    font-family: inherit; flex: none; }
  .menubtn:hover, .menubtn[aria-expanded="true"] { border-color: var(--accent); color: var(--accent); }
  #menulabel { flex: 1; }
  /* The menu's own header. `#menulabel` had a rule and no element from the start -- the markup never
     carried it -- so the rule styled nothing and `scripts/check_ui_js.py` had been failing on it.
     Rather than delete the check, the element now exists and earns its place: the menu is the one
     panel with no title, and a wordmark at the top says which product and which workspace the
     entries below belong to. */
  .menuhead {
    display: flex; align-items: center; gap: 8px;
    padding: 8px 10px 6px; border-bottom: 1px solid var(--line); margin-bottom: 4px;
  }
  .menuhead .wordmark { font-family: var(--display); font-size: 12px; letter-spacing: .04em; }
  .sidefoot .themebtn { border: 1px solid var(--border); background: var(--panel-2); color: var(--muted);
    border-radius: 8px; padding: 4px 8px; cursor: pointer; font-size: 11px; font-family: inherit;
    white-space: nowrap; flex: none; }
  .sidefoot .themebtn:hover { color: var(--text); border-color: var(--accent); }
  .menupop { position: absolute; bottom: calc(100% + 4px); left: 8px; right: 8px; z-index: 40;
    background: var(--panel); border: 1px solid var(--border); border-radius: 11px;
    box-shadow: var(--shadow); padding: 6px; display: flex; flex-direction: column; gap: 1px; }
  .menupop[hidden] { display: none; }
  .menusect { font-size: 10px; text-transform: uppercase; letter-spacing: .07em; color: var(--muted);
    padding: 7px 8px 3px; }
  .menuitem { display: flex; align-items: center; gap: 9px; width: 100%; text-align: left; border: none;
    background: none; color: var(--text); font: inherit; font-size: 12.5px; padding: 7px 9px;
    border-radius: 7px; cursor: pointer; }
  .menuitem:hover { background: var(--hover); }
  .menuitem .mi-ico { width: 16px; text-align: center; flex: none; }
  .menuitem kbd { margin-left: auto; font-size: 10px; color: var(--muted); background: var(--panel-2);
    border: 1px solid var(--border); border-radius: 5px; padding: 1px 5px; font-family: inherit; }
  .menuitem .badge { margin-left: auto; font-size: 10px; color: var(--accent); }
  .menuitem .badge:empty { display: none; }
  /* ---------- main ---------- */
  #main { flex: 1; display: flex; flex-direction: column; height: 100vh; min-width: 0; }
  header {
    display: flex; align-items: center; gap: 12px; padding: 10px 16px; border-bottom: 1px solid var(--border);
    background: var(--panel);
  }
  /* The header carries the mark as well as the sidebar. The sidebar is the first thing to be
     hidden on a narrow viewport, so without this the product loses its identity on exactly the
     screens where the browser tab title is the only other cue. */
  .headmark { display: flex; align-items: center; gap: 8px; }
  .headmark .wordmark {
    font-family: var(--display); font-weight: 600; font-size: 13px;
    letter-spacing: var(--wordmark-tracking); text-transform: uppercase; color: var(--text);
  }
  .headmark .mark { color: var(--text); flex: 0 0 auto; }
  .tabs { display: flex; gap: 2px; }
  .tab {
    padding: 5px 12px; border-radius: 7px; cursor: pointer; color: var(--muted); font-size: 13px; border: 1px solid transparent;
  }
  .tab.active { color: var(--text); background: var(--panel-2); border-color: var(--border); }
  .spacer { flex: 1; }
  .pill {
    font-size: 12px; color: var(--muted); border: 1px solid var(--border); padding: 3px 9px; border-radius: 20px;
    background: var(--panel-2); font-family: var(--mono); max-width: 42ch; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  /* ---------- panes ---------- */
  #chat, #trajectory { flex: 1; overflow-y: auto; padding: 20px 22px 8px; }
  #trajectory { display: none; }
  .msg { margin-bottom: 18px; display: flex; gap: 12px; }
  .msg .who { flex: 0 0 26px; height: 26px; border-radius: 50%; display: grid; place-items: center; font-size: 11px; font-weight: 700; overflow: hidden; }
  .msg.user .who { background: var(--user); color: var(--accent); border: 1px solid var(--border); }
  /* The assistant's avatar is the brand mark, not the word "Myriaxon" -- the name is already on the
     line beside it, so repeating it in the circle wastes the one place a face belongs. The mark is
     cloned into a .markslot by stampMarks(), which is why this needs no artwork of its own. */
  .msg.assistant .who { background: var(--ok-bg); border: 1px solid var(--ok-border); }
  .msg.assistant .who .markslot { display: grid; place-items: center; line-height: 0; }
  .msg.assistant .who .markslot svg { display: block; }
  .msg .body { min-width: 0; flex: 1; }
  .msg .role { font-size: 11px; color: var(--muted); margin-bottom: 3px; text-transform: uppercase; letter-spacing: .06em; }
  /* ---------- rendered markdown ---------- */
  .content { overflow-wrap: anywhere; }
  .content > *:first-child { margin-top: 0; }
  .content > *:last-child { margin-bottom: 0; }
  .content p { margin: 0 0 10px; }
  .content h1, .content h2, .content h3, .content h4, .content h5, .content h6 { margin: 16px 0 8px; line-height: 1.3; }
  .content h1 { font-size: 1.45em; }
  .content h2 { font-size: 1.25em; }
  .content h3 { font-size: 1.1em; color: var(--accent-2); }
  .content h4, .content h5, .content h6 { font-size: 1em; color: var(--muted); }
  .content strong { font-weight: 680; }
  .content em { font-style: italic; }
  .content del { opacity: .65; }
  .content a { color: var(--accent); }
  .content ul, .content ol { margin: 0 0 10px; padding-left: 22px; }
  .content li { margin: 3px 0; }
  .content hr { border: 0; border-top: 1px solid var(--border); margin: 16px 0; }
  .content blockquote {
    margin: 10px 0; padding: 4px 0 4px 12px; border-left: 3px solid var(--accent-dim); color: var(--muted);
  }
  .content table { border-collapse: collapse; margin: 10px 0; width: 100%; font-size: 13px; display: block; overflow-x: auto; }
  .content th, .content td { border: 1px solid var(--border); padding: 6px 10px; text-align: left; vertical-align: top; }
  .content th { background: var(--panel-2); font-weight: 650; white-space: nowrap; }
  .content tbody tr:nth-child(even) { background: color-mix(in srgb, var(--panel-2) 55%, transparent); }
  .content pre {
    background: var(--code-bg); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px;
    overflow-x: auto; font-family: var(--mono); font-size: 12.5px; margin: 10px 0;
  }
  .content code { font-family: var(--mono); font-size: 12.5px; background: var(--code-bg); padding: 1px 5px; border-radius: 4px; border: 1px solid var(--border); }
  .content pre code { background: none; padding: 0; border: 0; }
  .notice { color: var(--muted); font-size: 12.5px; margin: 6px 0; font-family: var(--mono); }
  .notice.warning { color: var(--warn); }
  .notice.error { color: var(--err); }
  .notice.success { color: var(--ok); }
  .thinking {
    color: var(--muted); font-style: italic; font-size: 12.5px; border-left: 2px solid var(--border);
    padding-left: 10px; margin: 6px 0; white-space: pre-wrap; overflow-wrap: anywhere;
  }
  details.think { margin: 6px 0; }
  details.think > summary { color: var(--muted); font-size: 12px; cursor: pointer; }
  /* ---------- buffering / thinking indicator ----------
     CSS-only animation: the wait before a model's first token is 35s+ on a cold Vertex instance, and
     a JS-driven ticker would need timers running for the whole wait. The element exists only while
     waiting, so the browser animates it without any script involvement. */
  .buffering { display: flex; align-items: center; gap: 9px; color: var(--signal); font-size: 13px; padding: 2px 0; }
  .buffering .dots { display: inline-flex; gap: 4px; }
  .buffering .dots span {
    width: 7px; height: 7px; border-radius: 50%; background: var(--signal); display: block;
    animation: myriaxon-pulse 1.2s ease-in-out infinite;
  }
  .buffering .dots span:nth-child(2) { animation-delay: .18s; }
  .buffering .dots span:nth-child(3) { animation-delay: .36s; }
  .buffering .label { color: var(--signal); opacity: .9; }
  .buffering .elapsed { color: var(--muted); font-family: var(--mono); font-size: 11.5px; margin-left: 2px; }
  @keyframes myriaxon-pulse {
    0%, 100% { transform: translateY(0) scale(.75); opacity: .45; }
    40%      { transform: translateY(-3px) scale(1); opacity: 1; }
  }
  @media (prefers-reduced-motion: reduce) {
    .buffering .dots span { animation: none; opacity: .85; }
  }
  .msg.assistant .who.streaming { animation: myriaxon-glow 1.6s ease-in-out infinite; }
  @keyframes myriaxon-glow {
    0%, 100% { box-shadow: 0 0 0 0 rgba(255,196,0,0); }
    50%      { box-shadow: 0 0 0 4px rgba(255,196,0,.18); }
  }
  /* tool cards */
  .tool {
    border: 1px solid var(--border); border-left: 3px solid var(--accent-dim); border-radius: 8px;
    background: var(--panel-2); margin: 8px 0; overflow: hidden;
  }
  .tool.err { border-left-color: var(--err); }
  .tool > summary { padding: 8px 11px; cursor: pointer; display: flex; gap: 9px; align-items: center; font-family: var(--mono); font-size: 12.5px; }
  .tool .name { color: var(--accent); }
  .tool .meta { color: var(--muted); margin-left: auto; font-size: 11.5px; }
  .tool pre { margin: 0; border: 0; border-top: 1px solid var(--border); border-radius: 0; max-height: 340px; }
  #trajwrap { font-family: var(--mono); font-size: 12.5px; }
  .trajrow { border: 1px solid var(--border); border-radius: 8px; margin-bottom: 8px; background: var(--panel-2); }
  .trajrow > summary { padding: 9px 12px; cursor: pointer; display: flex; gap: 10px; align-items: center; }
  .trajrow .idx { color: var(--muted); }
  .trajrow .name { color: var(--accent); }
  .trajrow .dur { color: var(--muted); margin-left: auto; }
  /* ---------- composer ---------- */
  #composer { border-top: 1px solid var(--border); background: var(--panel); padding: 10px 16px 14px; }
  #chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 7px; }
  .chip {
    display: flex; align-items: center; gap: 6px; background: var(--panel-2); border: 1px solid var(--border);
    border-radius: 7px; padding: 3px 8px; font-size: 12px; font-family: var(--mono); color: var(--muted);
  }
  .chip img { width: 22px; height: 22px; object-fit: cover; border-radius: 4px; }
  .chip button { background: none; border: 0; color: var(--muted); cursor: pointer; font-size: 14px; line-height: 1; padding: 0; }
  .chip button:hover { color: var(--err); }
  #inputrow { display: flex; gap: 9px; align-items: flex-end; background: var(--panel-2); border: 1px solid var(--border); border-radius: 12px; padding: 8px 9px; }
  #inputrow.drag { border-color: var(--accent); background: var(--panel-2); }
  #prompt {
    flex: 1; background: none; border: 0; color: var(--text); font: inherit; resize: none; outline: none;
    max-height: 200px; min-height: 24px; padding: 5px 2px;
  }
  .iconbtn { background: none; border: 0; color: var(--muted); cursor: pointer; font-size: 17px; padding: 4px 6px; border-radius: 7px; }
  .iconbtn:hover { color: var(--text); background: var(--hover); }
  #send { background: var(--accent); color: var(--signal-ink); border: 0; border-radius: 9px; padding: 7px 15px; cursor: pointer; font-weight: 600; }
  #send:disabled { opacity: .45; cursor: default; }
  /* ---------- status bar ----------
     Restructured from a flat row of parts into labelled groups, because the old one read as one
     sentence: "mode [auto edit] vendor [netra] + model [x] · 3.7s · 7 tok/s · 4.9k tok · 1 req".
     Nothing was wrong with the data; there was no hierarchy, so the eye had no entry point and the
     stats looked like an afterthought trailing off the end. Now each control is a captioned field
     and the numbers are their own right-aligned cluster of label/value pairs. */
  #statusbar {
    display: flex; align-items: stretch; gap: 0; margin-top: 8px;
    font-size: 11.5px; color: var(--muted);
    background: var(--panel); border: 1px solid var(--border); border-radius: 11px;
    padding: 7px 10px; flex-wrap: wrap;
  }
  .sgroup { display: flex; align-items: center; gap: 7px; padding: 0 12px; min-width: 0; }
  .sgroup:first-child { padding-left: 2px; }
  /* A hairline between groups rather than a gap: it separates without fragmenting the bar into
     unrelated islands, so it still reads as one strip of settings. */
  .sgroup + .sgroup { border-left: 1px solid var(--line); }
  .slabel {
    font-size: 9.5px; letter-spacing: .09em; text-transform: uppercase; color: var(--faint);
    font-weight: 600; white-space: nowrap;
  }
  .svalue {
    font-family: var(--mono); font-size: 11.5px; color: var(--text);
    background: none; border: 0; padding: 0; max-width: 22ch; text-overflow: ellipsis;
    appearance: none; -webkit-appearance: none; cursor: pointer;
  }
  .svalue:hover { color: var(--signal); }
  .svalue:focus-visible { outline: 2px solid var(--signal); outline-offset: 3px; border-radius: 4px; }
  /* The chevron is drawn rather than a native arrow, which no two platforms render alike and which
     silently disappears the moment `appearance: none` is set above. */
  .spick { position: relative; display: inline-flex; align-items: center; }
  .spick::after {
    content: ""; width: 0; height: 0; margin-left: 6px; pointer-events: none;
    border-left: 3.5px solid transparent; border-right: 3.5px solid transparent;
    border-top: 4px solid var(--faint);
  }
  .sadd {
    background: none; border: 1px dashed var(--border); color: var(--faint); border-radius: 6px;
    width: 19px; height: 19px; line-height: 1; font-size: 12px; cursor: pointer; padding: 0;
    display: grid; place-items: center;
  }
  .sadd:hover { color: var(--signal); border-color: var(--signal); border-style: solid; }

  /* The stat cluster sits at the far end, so the settings stay left and the measurements read as a
     separate register -- which is what they are. */
  #turninfo {
    display: flex; align-items: center; gap: 0; margin-left: auto; padding-left: 12px;
    border-left: 1px solid var(--line); flex-wrap: wrap;
  }
  .stat { display: flex; flex-direction: column; gap: 1px; padding: 0 11px; text-align: right; }
  .stat:first-child { padding-left: 2px; }
  .stat + .stat { border-left: 1px solid var(--line); }
  .stat .k {
    font-size: 8.5px; letter-spacing: .1em; text-transform: uppercase; color: var(--faint);
    font-weight: 600; line-height: 1;
  }
  .stat .v {
    font-family: var(--mono); font-size: 12px; color: var(--text); line-height: 1.25;
    font-variant-numeric: tabular-nums;
  }
  /* Signal colour is reserved for the one number that means "this is going well" -- a high cache
     hit rate. Colouring every value would make none of them stand out. */
  .stat .v.good { color: var(--signal); }
  .stat .v.warn { color: var(--warn); }
  #turninfo:empty { display: none; }
  @media (max-width: 900px) {
    /* Below this width the two registers cannot sit side by side without one being clipped, so the
       stats wrap onto their own line and keep their left rule off. */
    #turninfo { margin-left: 0; padding-left: 0; border-left: 0; border-top: 1px solid var(--line);
      width: 100%; padding-top: 7px; margin-top: 7px; justify-content: flex-end; }
  }
  select {
    background: var(--panel-2); color: var(--text); border: 1px solid var(--border); border-radius: 7px;
    padding: 3px 7px; font-size: 12px; outline: none;
  }
  /* The popup list is NOT styled by the `select` rule. An `option` inherits neither background nor
     colour from its parent on Windows, so the list fell back to the OS light theme: near-white rows
     carrying the inherited signal-green text, which is close to unreadable. Measured from the user's
     screenshot of the vendor dropdown. Both properties must be set on `option` itself.

     This matters most for `.svalue`, which sets `background: none` to sit flush in the status bar --
     that removes the select's own background, and with nothing behind the popup it rendered white. */
  select option {
    background: var(--panel-2);
    color: var(--text);
  }
  select option:checked,
  select option:hover {
    background: var(--signal);
    color: var(--signal-ink);
  }
  .hint { color: var(--muted); text-align: center; padding: 30px 10px; font-size: 13px; line-height: 1.8; }
  .hint kbd { background: var(--panel-2); border: 1px solid var(--border); border-radius: 5px; padding: 1px 6px; font-family: var(--mono); font-size: 12px; }
  /* ---------- modal (project picker) ---------- */
  .modal {
    position: fixed; inset: 0; background: rgba(0,0,0,.5); display: none; place-items: center; z-index: 40;
    backdrop-filter: blur(2px);
  }
  .modal.open { display: grid; }
  .dialog {
    background: var(--panel); border: 1px solid var(--border); border-radius: 14px; padding: 20px;
    width: min(560px, 92vw); box-shadow: var(--shadow);
    /* A dialog taller than the window had nowhere to scroll: the modal centres its child and
       nothing capped the height, so the Loci panel simply grew past the viewport and the lower
       rows were unreachable -- the buttons at the foot of the panel could not be clicked at all.
       Capping the dialog and letting *it* scroll is the fix, and the nested activity logs keep
       their own shorter cap so a single long log cannot push everything else out of reach. */
    max-height: 88vh; overflow-y: auto; overscroll-behavior: contain;
  }
  .dialog h3 { margin: 0 0 6px; font-size: 16px; }
  .dialog .dim { color: var(--muted); font-size: 12.5px; margin: 0 0 14px; }
  .dialog input {
    width: 100%; background: var(--panel-2); border: 1px solid var(--border); border-radius: 9px;
    color: var(--text); padding: 10px 12px; font-family: var(--mono); font-size: 12.5px; outline: none;
  }
  .dialog input:focus { border-color: var(--accent); }
  .dialog select {
    width: 100%; background: var(--panel-2); border: 1px solid var(--border); border-radius: 9px;
    color: var(--text); padding: 9px 10px; font-size: 12.5px; outline: none;
  }
  .dialog select:focus { border-color: var(--accent); }

  /* Form field: the label owns the layout, so a field is one block however its contents wrap.
     Declared here rather than per-dialog because "a labelled control" is a component, and the
     three dialogs that each invented their own version of it are how they drifted apart. */
  .field { display: block; margin-bottom: 12px; }
  .field > .flabel { display: block; font-size: 12px; color: var(--muted); margin-bottom: 5px; }
  .field > .flabel .fhint { font-weight: 400; opacity: .85; }
  .field > input, .field > select, .field > textarea { width: 100%; }

  /* A checkbox and its caption on one line. Referenced by three dialogs and defined by none --
     which is why the messaging dialog's checkboxes floated under their own rows, disconnected
     from the text they belonged to. */
  .chk {
    display: flex; align-items: center; gap: 9px; margin: 10px 0; font-size: 13px;
    color: var(--text); cursor: pointer; user-select: none;
  }
  .chk input[type="checkbox"] {
    width: 16px; height: 16px; flex: none; margin: 0; padding: 0;
    accent-color: var(--accent); cursor: pointer; font-family: inherit;
  }
  .chk .fhint { color: var(--muted); font-weight: 400; font-size: 12px; }

  /* A titled group of related controls, so a long form reads as sections rather than a column. */
  .fieldset { border: 1px solid var(--border); border-radius: 11px; padding: 12px 13px; margin: 12px 0; background: var(--panel-2); }
  .fieldset > .fshead {
    font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted);
    margin-bottom: 10px;
  }
  .fieldset > .field:last-child { margin-bottom: 0; }

  /* A single status line under a form: what state this integration or agent is in. */
  .statusline {
    display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--muted);
    border-top: 1px solid var(--border); margin-top: 12px; padding-top: 10px;
  }
  .statusline .dotmark { width: 7px; height: 7px; border-radius: 50%; background: var(--muted); flex: none; }
  .statusline.on .dotmark { background: var(--ok); }
  .statusline.off .dotmark { background: var(--line-2); }
  .statusline.warn .dotmark { background: var(--warn); }
  .statusline.err .dotmark { background: var(--err); }

  /* ---------- rail navigation ----------
     The sidebar carries a navigation spine as well as the session list, so the dashboard is a
     place with rooms rather than one page with a drawer of dialogs. Entries that open a dialog are
     marked as such in the markup (data-ui), which is what keeps this list honest: the surface
     either exists in this page or it does not exist at all. */
  .nav { display: flex; flex-direction: column; gap: 1px; padding: 0 6px; }
  .navgroup {
    font-size: 10px; text-transform: uppercase; letter-spacing: .07em; color: var(--muted);
    padding: 12px 10px 5px;
  }
  .nav button {
    all: unset; box-sizing: border-box; display: flex; align-items: center; gap: 10px;
    padding: 7px 10px; border-radius: 8px; color: var(--muted); cursor: pointer; font-size: 13px;
  }
  .nav button:hover { background: var(--hover); color: var(--text); }
  .nav button[aria-current="page"] {
    background: var(--panel-2); color: var(--text); box-shadow: inset 2px 0 0 var(--accent);
  }
  .nav button:focus-visible { outline: 2px solid var(--accent); }
  .nav .ni { width: 16px; text-align: center; flex: none; font-size: 13px; }
  .nav .ncount { margin-left: auto; font-family: var(--mono); font-size: 10.5px; color: var(--muted); }
  .nav .ncount:empty { display: none; }

  /* ---------- mission control ----------
     A full-width operational view over the same session state as the chat. It is hidden rather
     than removed, so switching views never discards the transcript or the agent. */
  #mc { flex: 1; overflow-y: auto; display: none; padding: 20px 22px 24px; }
  #mc.on { display: block; }
  .mchead { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 16px; }
  .mchead h1 {
    margin: 0; font-family: var(--display); font-weight: 600; font-size: 20px;
    letter-spacing: .01em;
  }
  .mchead .msub { color: var(--muted); font-size: 12.5px; }
  .mchead .mspacer { flex: 1; }
  .mggrid { display: grid; grid-template-columns: minmax(0,1.35fr) minmax(0,1fr); gap: 16px; align-items: start; }
  .mgcol { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
  .mgwide { grid-column: 1 / -1; }
  @media (max-width: 1080px) { .mggrid { grid-template-columns: minmax(0,1fr); } }
  .mcard {
    background: var(--panel); border: 1px solid var(--border); border-radius: 14px;
    padding: 16px 17px; min-width: 0;
  }
  .mcard > h2 {
    margin: 0 0 3px; font-size: 13.5px; font-weight: 600; display: flex; align-items: center; gap: 9px;
  }
  .mcard > .mnote { color: var(--muted); font-size: 11.5px; margin: 0 0 13px; line-height: 1.5; }
  .mcard .mhead { display: flex; align-items: flex-start; gap: 10px; justify-content: space-between; }

  /* Health: one row per connection, coloured by state. The locus is the whole signal, so the
     states are distinguished by position and colour rather than by reading text. */
  .healthgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 8px; }
  .hitem {
    display: flex; align-items: flex-start; gap: 9px; padding: 9px 11px; border-radius: 9px;
    border: 1px solid var(--border); background: var(--panel-2); min-width: 0;
  }
  .hitem .hdot { width: 8px; height: 8px; border-radius: 50%; flex: none; background: var(--line-2);
    margin-top: 5px; }
  .hitem.ok .hdot { background: var(--ok); }
  .hitem.warn .hdot { background: var(--warn); }
  .hitem.error .hdot { background: var(--err); }
  .hitem .hmain { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 2px; }
  /* These are spans in the markup, and an inline span next to another inline span runs on to the
     same line: the label and its detail rendered as "MCP servers none configured". block restores
     the two-line reading the design intends. The detail wraps rather than truncating, because on a
     status panel the reason a connection is down is the part that matters, and an ellipsis hides
     exactly that. */
  .hitem .hlabel { display: block; font-size: 12.5px; color: var(--text); line-height: 1.35; }
  .hitem .hdetail {
    display: block; font-size: 10.5px; color: var(--muted); font-family: var(--mono);
    line-height: 1.45; overflow-wrap: anywhere;
  }

  /* Meters: the number is the point, so it is set in mono at a size that reads at a glance. */
  .meters { display: grid; grid-template-columns: repeat(auto-fit, minmax(124px, 1fr)); gap: 14px 16px; }
  .meter .mlabel { font-size: 11.5px; color: var(--muted); margin-bottom: 3px; }
  .meter .mvalue { font-family: var(--mono); font-size: 20px; line-height: 1.15; letter-spacing: -.01em; }
  .meter .msub { font-size: 10.5px; color: var(--muted); font-family: var(--mono); }
  .bar { height: 5px; border-radius: 3px; background: var(--line); overflow: hidden; margin-top: 7px; }
  .bar > i { display: block; height: 100%; background: var(--signal); border-radius: 3px; }

  /* Runs: a row per session, with the progress bar only when progress is actually known. */
  .runrow { padding: 11px 0; border-top: 1px solid var(--border); }
  .runrow:first-of-type { border-top: 0; padding-top: 2px; }
  .runrow .rtitle { display: flex; align-items: center; gap: 8px; font-size: 13px; min-width: 0; }
  .runrow .rtitle span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .runrow .rmeta {
    display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 11px; color: var(--muted);
    font-family: var(--mono); padding-top: 4px;
  }
  .runrow .ractions { display: flex; gap: 6px; padding-top: 8px; }
  .mtag {
    font-family: var(--mono); font-size: 10px; padding: 1px 6px; border-radius: 5px;
    background: var(--panel-2); color: var(--muted); border: 1px solid var(--border);
  }
  .mtag.live { color: var(--signal); border-color: var(--signal); }
  .mtag.dot { color: var(--violet); border-color: var(--violet); }
  .mtag.bad { color: var(--err); border-color: var(--err); }

  /* Approvals: a decision card, so the action is a button rather than a sentence. */
  .approval { border: 1px solid var(--border); border-radius: 10px; padding: 12px; margin-bottom: 9px; background: var(--panel-2); }
  .approval p { margin: 0; font-size: 13px; }
  .approval .ameta { font-size: 11px; color: var(--muted); padding-top: 3px; }
  .approval .arow { display: flex; gap: 7px; margin-top: 10px; }

  /* Live trace: fixed-width columns so timestamps and sources line up and the eye can skim. */
  .tracelist {
    list-style: none; margin: 0; padding: 0; max-height: 320px; overflow-y: auto;
    font-family: var(--mono); font-size: 11.5px; line-height: 1.6;
  }
  .tracelist li {
    display: grid; grid-template-columns: 58px 92px minmax(0,1fr); gap: 9px;
    padding: 3px 0; border-bottom: 1px dashed var(--border);
  }
  .tracelist .tw { color: var(--muted); }
  .tracelist .ts { color: var(--blue); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .tracelist .ts.ok { color: var(--ok); }
  .tracelist .ts.warn { color: var(--warn); }
  .tracelist .ts.error { color: var(--err); }
  .tracelist .ts.mem { color: var(--violet); }
  /* Untrusted text is marked, not merely stored as such: a reader should be able to tell at a glance that a
     line came from a model or a file rather than from the harness. */
  .tracelist .tm.untrusted { font-style: italic; }

  /* The transparency dial. The layer list is the point of the panel -- a slider with no legend tells you the
     number changed but not what you are now seeing, which is the whole question. */
  .transdial { display: flex; flex-direction: column; gap: 10px; }
  .transdial .transhead { font-size: 13px; }
  .transdial input[type="range"] { width: 100%; accent-color: var(--blue); }
  .translayers { display: flex; flex-direction: column; gap: 3px; margin-top: 4px; }
  .translayer { display: grid; grid-template-columns: 18px 92px 1fr; gap: 8px; align-items: baseline;
                font-size: 12px; opacity: .42; transition: opacity .12s ease; }
  .translayer.on { opacity: 1; }
  .translayer .tln { color: var(--muted); text-align: right; font-variant-numeric: tabular-nums; }
  .translayer .tlb { color: var(--text); }
  .translayer.on .tlb { color: var(--blue); }
  .translayer .tld { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .transdial .transfoot { font-size: 11px; }

  /* ---------------------------------------------------------------- the pane wall
     A grid of equal panes rather than a list with a detail view. `minmax(0, 1fr)` on the columns is the
     load-bearing part: a grid track defaults to `auto`, which refuses to shrink below its content, so one
     long unbroken line in a transcript would push the whole row wider than the dialog and the other panes
     out of view. `minmax(0, ...)` lets a track shrink and pushes the overflow into the pane, where the
     transcript already scrolls. */
  .wall-dialog { width: min(1500px, 96vw); max-height: 94vh; display: flex; flex-direction: column; }
  .wall-bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin: 10px 0 12px; }
  .wall-spacer { flex: 1 1 auto; }
  .wall-layouts { display: flex; align-items: center; gap: 6px; }
  .wall-layouts button[aria-pressed="true"] { border-color: var(--blue); color: var(--blue); }
  .wall-toggle { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted); }
  .wall-grid {
    display: grid; gap: 10px; overflow: auto; flex: 1 1 auto; min-height: 220px;
    align-content: start; padding-right: 2px;
  }
  .wall-grid[data-cols="1"] { grid-template-columns: minmax(0, 1fr); }
  .wall-grid[data-cols="2"] { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .wall-grid[data-cols="3"] { grid-template-columns: repeat(3, minmax(0, 1fr)); }

  .pane {
    display: flex; flex-direction: column; min-width: 0; min-height: 240px;
    border: 1px solid var(--line-2); border-radius: 10px; background: var(--panel-2); overflow: hidden;
  }
  /* The pane being dragged is faded rather than hidden: it is the reference for where it will land. */
  .pane.dragging { opacity: .45; }
  /* A drop target says so BEFORE the drop, because a drag with no visible target is a guess. */
  .pane.drop-target, .pane.empty.drop-target { border-color: var(--blue); box-shadow: inset 0 0 0 1px var(--blue); }
  .pane.empty { border-style: dashed; align-items: center; justify-content: center; color: var(--muted); }
  .pane.empty .pane-hint { font-size: 12px; text-align: center; padding: 12px; line-height: 1.5; }

  .pane-bar {
    display: flex; align-items: center; gap: 8px; padding: 6px 8px;
    border-bottom: 1px solid var(--line); background: var(--panel);
    cursor: grab; user-select: none; flex: none;
  }
  .pane-bar:active { cursor: grabbing; }
  .pane-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); flex: none; }
  /* Working, waiting and idle are three different states and a colour alone does not carry them, so the
     label beside the dot always says which. The colour is the fast read, the word is the reliable one. */
  .pane-dot.working { background: var(--ok); box-shadow: 0 0 0 3px color-mix(in srgb, var(--ok) 22%, transparent); }
  .pane-dot.waiting { background: var(--warn); }
  .pane-name { font-size: 12px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .pane-what { font-size: 11px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .pane-bar .pane-actions { margin-left: auto; display: flex; gap: 4px; flex: none; }
  .pane-bar button { padding: 1px 6px; font-size: 11px; }

  .pane-body { flex: 1 1 auto; overflow-y: auto; padding: 8px; display: flex; flex-direction: column; gap: 8px; }
  .pane-turn { display: flex; flex-direction: column; gap: 3px; }
  .pane-who { font-size: 10px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); }
  .pane-bubble { font-size: 12px; line-height: 1.5; white-space: pre-wrap; overflow-wrap: anywhere; }
  .pane-turn.you .pane-bubble { color: var(--blue); }
  /* Tool lines are shown because a locus's turns are mostly tool calls, and a wall that showed only prose
     would be blank exactly while the agents were working. */
  .pane-tool { font-size: 11px; color: var(--muted); border-left: 2px solid var(--line-2); padding-left: 6px; }
  /* A cross-agent line. Marked, not merely coloured: this is the whole reason the wall exists. */
  .pane-link {
    font-size: 11px; padding: 4px 6px; border-radius: 6px;
    background: color-mix(in srgb, var(--violet) 14%, transparent);
    border-left: 2px solid var(--violet); color: var(--text-2);
  }
  .pane-composer { display: flex; gap: 6px; padding: 6px; border-top: 1px solid var(--line); flex: none; }
  .pane-composer textarea {
    flex: 1 1 auto; min-width: 0; resize: none; font-size: 12px; max-height: 80px;
  }

  .wall-foot { margin-top: 10px; flex: none; }

  /* The failure report. Deliberately loud: it uses the error colour and says outright that this is a bug,
     because the alternative reading -- "the room is empty" -- sends the reader looking at their own setup. */
  .wall-errors {
    margin-top: 10px; padding: 8px 10px; border-radius: 8px; flex: none;
    border: 1px solid var(--err); background: color-mix(in srgb, var(--err) 12%, transparent);
    font-size: 12px;
  }
  .wall-error-head { color: var(--err); font-weight: 600; margin-bottom: 4px; }
  .wall-error-row { font-family: var(--mono, monospace); font-size: 11px; color: var(--text-2);
                    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .wall-roster .wall-roster-list { display: flex; flex-wrap: wrap; gap: 6px; }
  .wall-chip {
    display: flex; align-items: center; gap: 6px; padding: 4px 8px; cursor: grab;
    border: 1px solid var(--line-2); border-radius: 999px; font-size: 12px; background: var(--panel-2);
  }
  .wall-chip:active { cursor: grabbing; }
  .wall-chip.on { border-color: var(--blue); color: var(--blue); }
  .wall-chip .dim { font-size: 11px; }

  /* The core: a small live status diagram, drawn from the same health data as the list. */
  .coreslot { display: flex; align-items: center; gap: 14px; }
  .coremap { position: relative; width: 132px; height: 132px; flex: none; }
  .coremap svg { width: 100%; height: 100%; display: block; }
  .coremap .cring { fill: none; stroke: var(--line); stroke-dasharray: 2 6; }
  .coremap .cspoke { stroke: var(--line-2); stroke-width: 1.2; }
  .coremap .cnode { fill: var(--panel-2); stroke: var(--line-2); stroke-width: 1.4; }
  .coremap .cnode.ok { stroke: var(--ok); }
  .coremap .cnode.warn { stroke: var(--warn); }
  .coremap .cnode.error { stroke: var(--err); }
  .coremark { color: var(--text); }
  .coremark .core-locus { fill: var(--signal); }

  /* Routing: a single stacked bar, because the question is "what share", not "how many". */
  .routebar { display: flex; height: 12px; border-radius: 6px; overflow: hidden; gap: 2px; margin: 4px 0 12px; }
  .routebar i { display: block; height: 100%; background: var(--signal); }
  .legend { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 7px; font-size: 12.5px; }
  .legend li { display: grid; grid-template-columns: 10px minmax(0,1fr) auto auto; align-items: center; gap: 9px; }
  .legend .sw { width: 10px; height: 10px; border-radius: 3px; background: var(--signal); }
  .legend .pct { font-family: var(--mono); color: var(--muted); min-width: 42px; text-align: right; }

  .memlist, .schedlist { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; font-size: 12.5px; }
  .memlist li { padding-left: 11px; border-left: 2px solid var(--violet); }
  .memlist small, .schedlist small { display: block; color: var(--muted); font-size: 11px; }
  .schedlist li { display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 2px 10px; align-items: center; }
  .skillchips { display: flex; flex-wrap: wrap; gap: 7px; }
  .skillchip { font-size: 12px; border: 1px solid var(--border); border-radius: 8px; padding: 5px 9px; background: var(--panel-2); }
  .skillchip b { font-weight: 500; }
  .mempty { font-size: 12.5px; color: var(--muted); padding: 6px 0; line-height: 1.55; }
  .mgfoot { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding-top: 4px; }
  /* A segmented filter. Referenced by the trace filter and defined nowhere, so the buttons sat
     flush against each other with no indication of which was active. */
  .seg { display: inline-flex; border: 1px solid var(--border); border-radius: 8px; padding: 2px; gap: 2px; }
  .seg button {
    all: unset; box-sizing: border-box; border-radius: 6px; padding: 4px 10px;
    font-size: 11.5px; color: var(--muted); cursor: pointer; min-height: 26px;
  }
  .seg button:hover { background: var(--hover); color: var(--text); }
  .seg button[aria-pressed="true"] { background: var(--panel-2); color: var(--text); }
  .seg button:focus-visible { outline: 2px solid var(--accent); }
  .mspacer { flex: 1; }
  .recents { margin: 10px 0 4px; display: flex; flex-direction: column; gap: 4px; max-height: 180px; overflow-y: auto; }
  .recents .recent {
    padding: 7px 10px; border-radius: 8px; border: 1px solid transparent; cursor: pointer;
    font-family: var(--mono); font-size: 12px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .recents .recent:hover { background: var(--panel-2); color: var(--text); border-color: var(--border); }
  /* ---------- settings form ----------
     The form scrolls vertically only. It used to be able to scroll sideways, which is the one
     direction a settings list should never move: a horizontal bar at the foot of a form means the
     controls are wider than the dialog, and in the reported screenshot it had cut the left edge off
     the labels and clipped the switches on the right. */
  #setform { display: flex; flex-direction: column; gap: 2px; max-height: 58vh; overflow-y: auto;
    overflow-x: hidden; padding-right: 4px; }
  .setrow {
    display: flex; align-items: center; gap: 14px; padding: 10px 2px;
    border-bottom: 1px solid var(--border); min-width: 0;
  }
  .setrow:last-child { border-bottom: 0; }
  /* flex-basis 0, not auto: with `auto` the label's basis is its longest word, so a long hint
     starved the text column and wrapped "Multi enables sub-agent delegation tools" one word per
     line -- which is what the screenshot shows. A zero basis plus min-width:0 lets it take the
     space that is actually left over. */
  .setrow .info { flex: 1 1 0; min-width: 0; }
  .setrow .lbl { font-size: 13px; line-height: 1.35; }
  .setrow .hint { font-size: 11.5px; color: var(--muted); margin-top: 3px; line-height: 1.45; }
  /* The control column keeps its intrinsic size but may never push the row wider than the dialog:
     `flex-shrink: 0` on a 150px-minimum select was enough to overflow a narrow panel. */
  .setrow .ctl { flex: 0 1 auto; min-width: 0; max-width: 52%; display: flex; align-items: center;
    justify-content: flex-end; }
  .setrow select, .setrow input[type="number"] {
    background: var(--panel-2); color: var(--text); border: 1px solid var(--border); border-radius: 8px;
    padding: 6px 9px; font-size: 12.5px; outline: none;
    min-width: 0; width: 100%; max-width: 340px;
  }
  .setrow input[type="number"] { max-width: 120px; }
  .setrow select:focus, .setrow input:focus { border-color: var(--accent); }
  /* switch */
  .switch { position: relative; width: 42px; height: 24px; flex: 0 0 auto; }
  .switch input { opacity: 0; width: 0; height: 0; }
  .slider {
    position: absolute; inset: 0; background: var(--border); border-radius: 24px; cursor: pointer;
    transition: background .15s;
  }
  .slider::before {
    content: ""; position: absolute; height: 18px; width: 18px; left: 3px; top: 3px; background: var(--signal-ink);
    border-radius: 50%; transition: transform .15s;
  }
  .switch input:checked + .slider { background: var(--accent); }
  .switch input:checked + .slider::before { transform: translateX(18px); }
  .saved { color: var(--ok); font-size: 11.5px; margin-left: 6px; opacity: 0; transition: opacity .2s; }
  .saved.show { opacity: 1; }
  /* compact density */
  html[data-density="compact"] .msg { margin-bottom: 10px; }
  html[data-density="compact"] #chat, html[data-density="compact"] #trajectory { padding: 12px 14px 4px; }
  html[data-density="compact"] .notice { margin: 3px 0; }
  html[data-density="compact"] .content p { margin-bottom: 6px; }
  /* ---------- vendor / endpoint manager ---------- */
  .vendform { display: flex; flex-direction: column; gap: 9px; margin-top: 12px; }
  .vendform label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--muted); }
  .vendform input {
    background: var(--panel-2); border: 1px solid var(--border); border-radius: 8px; color: var(--text);
    padding: 8px 10px; font-family: var(--mono); font-size: 12.5px; outline: none;
  }
  .vendform input:focus { border-color: var(--accent); }
  .vendactions { display: flex; gap: 8px; margin-top: 2px; }
  .vendactions button { border-radius: 8px; padding: 7px 13px; cursor: pointer; font-size: 12.5px; border: 1px solid var(--border); }
  .vendactions .ghost { background: var(--panel-2); color: var(--text); }
  .vendactions .primary { background: var(--accent); color: var(--signal-ink); border-color: var(--accent); font-weight: 600; }
  #vstatus { min-height: 16px; font-size: 12px; }
  .plugin-doc { font-size: 11.5px; line-height: 1.5; }

  /* file explorer + diff review */
  .dialog.wide { width: min(1040px, 94vw); }
  .tabs { display: flex; gap: 6px; padding: 4px 0 10px; border-bottom: 1px solid var(--border); margin-bottom: 10px; }
  .tabs .tab { background: none; border: none; color: var(--muted); font: inherit; font-size: 12.5px;
    padding: 5px 10px; border-radius: 7px; cursor: pointer; }
  .tabs .tab:hover { background: var(--hover); color: var(--text); }
  .tabs .tab.active { background: var(--accent); color: var(--signal-ink); }
  .filelist { max-height: 46vh; overflow: auto; }
  .filerow { display: flex; align-items: center; gap: 9px; padding: 5px 8px; border-radius: 7px;
    cursor: pointer; font-family: var(--mono); font-size: 12.5px; }
  .filerow:hover { background: var(--hover); }
  .filerow .fname { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .filerow .fmeta { color: var(--muted); font-size: 11px; }
  .filerow .fcode { font-weight: 700; width: 15px; text-align: center; }
  .fcode.add, .fcode.untracked { color: var(--ok); }
  .fcode.del { color: var(--err); }
  .fcode.mod { color: var(--warn); }
  .codehead { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding-bottom: 6px; }
  .codebody { max-height: 52vh; overflow: auto; background: var(--code-bg); border: 1px solid var(--border);
    border-radius: 8px; font-family: var(--mono); font-size: 12px; line-height: 1.55; }
  .codebody .cl { display: flex; white-space: pre; }
  .codebody .cl .ln { width: 46px; flex: none; text-align: right; padding-right: 10px; color: var(--muted);
    user-select: none; }
  .codebody .cl .tx { flex: 1; padding-right: 10px; }
  .codebody .cl.add { background: var(--add-bg); }
  .codebody .cl.add .tx::before { content: "+"; color: var(--ok); margin-right: 4px; }
  .codebody .cl.del { background: var(--del-bg); }
  .codebody .cl.del .tx::before { content: "-"; color: var(--err); margin-right: 4px; }
  .codebody .cl.meta { color: var(--muted); font-style: italic; }
  .codebody .cl.hunk { background: var(--hover); color: var(--muted); }
  .ghost.small { font-size: 11px; padding: 2px 8px; }

  /* MCP catalog: a row per known server with a toggle, so enabling one is a click rather than a
     research task. */
  .catalog { max-height: 46vh; overflow: auto; display: flex; flex-direction: column; gap: 4px; }
  .catrow { display: flex; align-items: flex-start; gap: 10px; padding: 8px 10px; border-radius: 9px;
    border: 1px solid var(--border); background: var(--panel-2); }
  .catrow.on { border-color: var(--ok); }
  .catrow .catmain { flex: 1; min-width: 0; }
  .catrow .cattitle { font-size: 13px; color: var(--text); display: flex; align-items: center; gap: 7px; }
  .catrow .catnote { font-size: 11.5px; color: var(--muted); padding-top: 2px; line-height: 1.45; }
  .catrow .catneeds { font-size: 11px; color: var(--warn); padding-top: 3px; }
  .cattag { font-size: 9.5px; text-transform: uppercase; letter-spacing: .05em; color: var(--muted);
    border: 1px solid var(--border); border-radius: 5px; padding: 1px 5px; }
  .switch { flex: none; width: 38px; height: 21px; border-radius: 11px; border: 1px solid var(--border);
    background: var(--panel); position: relative; cursor: pointer; padding: 0; }
  .switch::after { content: ""; position: absolute; top: 2px; left: 2px; width: 15px; height: 15px;
    border-radius: 50%; background: var(--muted); transition: left .12s ease, background .12s ease; }
  .switch.on { background: var(--ok-bg); border-color: var(--ok); }
  .switch.on::after { left: 19px; background: var(--ok); }
  .warnbox { border: 1px solid var(--warn); border-radius: 9px; padding: 8px 10px; margin-bottom: 8px;
    font-size: 12px; color: var(--warn); background: var(--panel-2); }
  .catfield { display: flex; gap: 6px; align-items: center; padding-top: 6px; }
  .catfield input { flex: 1; font-family: var(--mono); font-size: 11.5px; }
  #vstatus.ok { color: var(--ok); }
  #vstatus.err { color: var(--err); }

  /* File explorer panes. Both classes were referenced in the markup and defined nowhere, so the
     panes were sized by their contents alone and grew the dialog instead of scrolling inside it.
     Visibility is toggled by script, so these carry layout only. */
  .codepane { max-height: 52vh; overflow-y: auto; }
  .codeviewer { max-height: 52vh; overflow: auto; border-top: 1px solid var(--border); margin-top: 8px; }

  /* ---------- persistent agents (loci) ----------
     A locus is a durable identity, so the panel answers three questions in order: which loci exist,
     what each is working on, and what it has actually done. The activity log is given real space
     rather than hidden behind a disclosure -- autonomy without visibility is a black box that
     spends money. */
  .locusrow { border: 1px solid var(--border); border-radius: 11px; background: var(--panel-2);
    padding: 11px 12px; margin-bottom: 8px; }
  .locusrow.due { border-color: var(--accent); }
  .locushead { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .locushead .locusname { font-weight: 600; font-size: 14px; }
  .locushead .locusrole { font-size: 11.5px; color: var(--muted); }
  .locushead .locusspacer { flex: 1; }
  .locushead .mark-mini { width: 13px; height: 13px; flex: none; color: var(--accent); }
  .locustag { font-size: 9.5px; text-transform: uppercase; letter-spacing: .05em; border-radius: 5px;
    padding: 1px 5px; border: 1px solid var(--border); color: var(--muted); }
  .locustag.on { color: var(--ok); border-color: var(--ok); }
  .locustag.off { color: var(--muted); }
  .locustag.live { color: var(--accent); border-color: var(--accent); }
  .locusmeta { font-size: 11px; color: var(--muted); font-family: var(--mono); padding-top: 5px; line-height: 1.5; }
  .locusinstr { font-size: 11.5px; color: var(--muted); padding-top: 5px; line-height: 1.45;
    border-left: 2px solid var(--line-2); padding-left: 8px; margin-top: 5px; }
  .goals { list-style: none; margin: 8px 0 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
  .goals li { display: flex; align-items: center; gap: 8px; font-size: 12.5px; padding: 4px 6px;
    border-radius: 7px; background: var(--panel); border: 1px solid transparent; }
  .goals li:hover { border-color: var(--border); }
  .goals .gtitle { flex: 1; min-width: 0; }
  .goals .gid { font-family: var(--mono); font-size: 10px; color: var(--muted); }
  .gstatus { font-size: 9.5px; text-transform: uppercase; letter-spacing: .05em; border-radius: 5px;
    padding: 1px 5px; border: 1px solid var(--border); color: var(--muted); flex: none; }
  .gstatus.pending { color: var(--text-2); }
  .gstatus.active { color: var(--accent); border-color: var(--accent); }
  .gstatus.blocked { color: var(--warn); border-color: var(--warn); }
  .gstatus.done { color: var(--ok); border-color: var(--ok); }
  .goals .gbtns { display: flex; gap: 4px; flex: none; }
  .locuslog { list-style: none; margin: 8px 0 0; padding: 0; max-height: 132px; overflow-y: auto;
    font-family: var(--mono); font-size: 11px; line-height: 1.55; }
  .locuslog li { display: grid; grid-template-columns: 84px 58px minmax(0,1fr); gap: 8px;
    padding: 2px 0; border-bottom: 1px dashed var(--border); }
  .locuslog .lwhen { color: var(--muted); }
  .locuslog .lkind { color: var(--blue); }
  .locuslog .lkind.error { color: var(--err); }
  .locuslog .lkind.goal { color: var(--violet); }
  .locuslog .lkind.turn { color: var(--ok); }
  .locusbtns { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 9px; }
  .locusform { border: 1px dashed var(--border); border-radius: 11px; padding: 11px 12px; margin-bottom: 10px; }
  .locusform label { display: block; font-size: 11.5px; color: var(--muted); margin: 7px 0 3px; }
  .locusform input, .locusform textarea { width: 100%; background: var(--panel); border: 1px solid var(--border);
    border-radius: 8px; color: var(--text); padding: 7px 9px; font-size: 12.5px; outline: none; }
  .locusform textarea { font-family: var(--mono); font-size: 11.5px; min-height: 54px; resize: vertical; }
  .locusform input:focus, .locusform textarea:focus { border-color: var(--accent); }
  .locusform .row2 { display: flex; gap: 8px; }
  .locusform .row2 > * { flex: 1; }
  .locusform .checkline { display: flex; align-items: center; gap: 8px; margin-top: 9px; font-size: 12.5px; color: var(--text); }
  .locusempty { font-size: 12.5px; color: var(--muted); padding: 10px 2px; line-height: 1.55; }

  /* ---------- the Loci page ----------
     Loci get their own page rather than borrowing the main chat. Before this, running a locus called
     `attach()`, which switched the Myriaxon session to the locus's session: the roster closed, the
     main transcript was replaced by the locus's, and every `[tool.name]…` line the locus's console
     emitted landed in the conversation the user was having with Myriaxon. Two agents, one
     transcript, and no way to tell which was speaking.

     So this is a two-column page: the roster on the left, and on the right the *selected* locus with
     its own transcript and its own composer. Height is bounded here (not by the content) so a locus
     with a long conversation scrolls inside its pane instead of stretching the dialog past the
     viewport. */
  .dialog.widest { width: min(1180px, 96vw); }
  .locilayout { display: grid; grid-template-columns: minmax(240px, 320px) minmax(0, 1fr);
                gap: 14px; align-items: stretch; min-height: 0; margin-top: 4px; }
  .locifleet { min-width: 0; max-height: min(72vh, 660px); overflow-y: auto; overscroll-behavior: contain;
               padding-right: 4px; }
  /* Rows in the roster are compact summaries now that the detail lives on the right. */
  .locilist .locusrow { cursor: pointer; }
  .locilist .locusrow:hover { border-color: color-mix(in srgb, var(--accent) 45%, var(--border)); }
  .locilist .locusrow.selected {
    border-color: var(--accent);
    box-shadow: inset 3px 0 0 var(--signal);
  }
  .locilist .locusrow .locusbtns { display: none; }
  .locilist .locusrow .goals, .locilist .locusrow .locuslog, .locilist .locusrow .locusinstr { display: none; }
  .locilist .locusrow .locusmeta { margin-top: 2px; }

  .locichat { display: flex; flex-direction: column; min-width: 0; min-height: 0;
              height: min(72vh, 660px); border: 1px solid var(--border); border-radius: 12px;
              background: var(--panel); overflow: hidden; }
  .lc-head { display: flex; align-items: center; gap: 10px; padding: 9px 12px;
             border-bottom: 1px solid var(--line); background: var(--panel-2); }
  .lc-avatar { width: 30px; height: 30px; flex: 0 0 auto; }
  .lc-avatar svg { width: 30px; height: 30px; display: block; }
  .lc-who { min-width: 0; flex: 1 1 auto; }
  .lc-name { font-family: var(--display); font-size: 13.5px; color: var(--text);
             overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .lc-sub { font-size: 11px; color: var(--text-3); overflow: hidden; text-overflow: ellipsis;
            white-space: nowrap; }
  .lc-state { font-size: 10.5px; color: var(--text-3); white-space: nowrap; }
  .lc-state.running { color: var(--signal); }
  /* The outcome of the last run. Present so a run that FAILED and a run that never started are
     distinguishable from one that worked -- before this, all three rendered as "N open objective(s)". */
  .locusoutcome {
    display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
    margin-top: 6px; font-size: 11.5px; line-height: 1.35; color: var(--muted);
  }
  .locusoutcome.good { color: var(--muted); }
  /* `--err`, not a literal or a made-up name: `tests/test_brand_consistency.py` fails the build on any CSS
     variable that is referenced but never declared, and it caught exactly that here. The theme already
     maps --err to --red per colour scheme, so the failure colour also follows light/dark for free. */
  .locusoutcome.bad { color: var(--err); }
  .lc-out-dot {
    width: 6px; height: 6px; border-radius: 50%; flex: none;
    background: currentColor; opacity: 0.75;
  }
  .locusoutcome.bad .lc-out-dot { opacity: 1; }
  /* A failure message can be long and comes from a model or a file, so it is data: wrapped, clamped, and
     never allowed to stretch the card. */
  .lc-out-err {
    flex-basis: 100%; opacity: 0.85; font-size: 11px;
    overflow-wrap: anywhere; white-space: pre-wrap; max-height: 3.6em; overflow: hidden;
  }
  .lc-state.paused { color: var(--amber); }

  .lc-controls { display: flex; flex-wrap: wrap; gap: 6px; padding: 8px 12px;
                 border-bottom: 1px solid var(--line); }
  .lc-controls[hidden] { display: none; }
  .lc-controls .danger { color: var(--warn); border-color: color-mix(in srgb, var(--warn) 40%, var(--border)); }
  /* Self-directed reads as an active capability, not a warning: the owner asked for it. The amber is
     reserved for the confinement notice below, which is the part that must stay noticeable. */
  .lc-controls #lc-autonomy.on { color: var(--accent); border-color: var(--accent); }
  .lc-bound { font-size: 10.5px; color: var(--amber); padding: 5px 12px;
              border-bottom: 1px solid var(--line); white-space: nowrap; overflow: hidden;
              text-overflow: ellipsis; }
  .lc-bound[hidden] { display: none; }

  /* The transcript scrolls inside the pane. `min-height: 0` is what allows a flex child to shrink
     below its content height -- without it the pane grows and the composer is pushed out of view. */
  .lc-transcript { flex: 1 1 auto; min-height: 0; overflow-y: auto; overscroll-behavior: contain;
                   padding: 10px 12px; display: flex; flex-direction: column; gap: 9px; }
  .lc-empty { font-size: 12px; color: var(--text-3); line-height: 1.6; margin: auto 0; text-align: center;
              padding: 0 18px; }
  .lc-turn { display: flex; flex-direction: column; gap: 3px; }
  .lc-who-label { font-size: 9.5px; letter-spacing: .09em; text-transform: uppercase; color: var(--faint);
                  font-weight: 600; }
  .lc-bubble { font-size: 12.5px; line-height: 1.55; color: var(--text); white-space: pre-wrap;
               word-break: break-word; padding: 7px 10px; border-radius: 9px;
               background: var(--panel-2); border: 1px solid var(--line); }
  .lc-turn.you .lc-bubble { background: color-mix(in srgb, var(--signal) 10%, var(--panel-2));
                            border-color: color-mix(in srgb, var(--signal) 28%, var(--line)); }
  .lc-meta { font-size: 10px; color: var(--text-3); }

  .lc-composer { display: flex; gap: 8px; align-items: flex-end; padding: 9px 12px;
                 border-top: 1px solid var(--line); background: var(--panel-2); }
  .lc-composer textarea { flex: 1 1 auto; resize: none; min-height: 34px; max-height: 120px;
                          background: var(--panel); border: 1px solid var(--border); border-radius: 9px;
                          color: var(--text); padding: 8px 10px; font-size: 12.5px; font-family: inherit;
                          outline: none; }
  .lc-composer textarea:focus { border-color: var(--accent); }
  .lc-composer button[disabled] { opacity: .55; cursor: default; }

  .lc-detail { border-top: 1px solid var(--line); max-height: 190px; overflow-y: auto;
               overscroll-behavior: contain; padding: 9px 12px; font-size: 11.5px; color: var(--muted); }
  .lc-detail .lc-goals { margin: 4px 0 0; }
  .lc-detail .locusform { margin-top: 8px; }
  .lc-detail .locuslog { max-height: 120px; overflow-y: auto; }

  @media (max-width: 940px) {
    /* One column below this width: two panes side by side would each be too narrow to read, so the
       roster goes on top and the chat keeps a workable height under it. */
    .locilayout { grid-template-columns: minmax(0, 1fr); }
    .locifleet { max-height: 30vh; }
    .locichat { height: min(60vh, 520px); }
  }

  /* ---------- composer command suggestions ----------
     The terminal has had completions since the beginning; the browser had only a placeholder
     telling you to type "/". This is the same catalogue, rendered where the typing happens. */
  #inputrow { position: relative; }
  /* ---------- locus banner ----------
     Shown only when the open session belongs to a locus. Until this existed there was nothing on
     screen saying who was answering: the transcript said "myriaxon" even while the reply was coming
     from "analyst", and the only way to stop talking to a locus was a command the user had to already
     know. The banner answers both -- who is speaking, and how to stop. */
  #locusbanner {
    display: flex; align-items: center; gap: 10px; margin: 0 0 10px;
    background: linear-gradient(90deg, color-mix(in srgb, var(--signal) 14%, transparent), transparent);
    border: 1px solid color-mix(in srgb, var(--signal) 34%, var(--border));
    border-left: 3px solid var(--signal);
    border-radius: 10px; padding: 8px 12px; font-size: 12px; color: var(--text-2);
  }
  #locusbanner[hidden] { display: none; }
  #locusbanner b { color: var(--text); }
  #dotbanner .dotmark {
    width: 9px; height: 9px; border-radius: 50%; background: var(--signal); flex: 0 0 auto;
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--signal) 22%, transparent);
  }
  #locusbanner .locustext { flex: 1 1 auto; min-width: 0; }
  #locusbanner .locusacts { flex: 0 0 auto; }
  /* The card Mission control just sent you to. Without a visible mark the scroll lands on one card
     among several identical ones and the user cannot tell which was meant. */
  .locusrow.aimed {
    border-color: var(--signal);
    box-shadow: 0 0 0 2px color-mix(in srgb, var(--signal) 35%, transparent);
    transition: box-shadow .25s ease, border-color .25s ease;
  }
  /* The stop control. It exists only while a turn is running, and it is the button that makes
     `/api/cancel` reachable -- the route had been implemented and tested while no part of the page
     ever called it, so cancelling was possible from the API and impossible from the product. */
  .stop { color: var(--err); border-color: var(--err); }
  .stop:hover { background: var(--err); color: var(--ink); }
  .suggest {
    position: absolute; bottom: calc(100% + 6px); left: 0; right: 0; z-index: 40;
    background: var(--panel); border: 1px solid var(--line-2); border-radius: 11px;
    box-shadow: 0 12px 32px rgba(0,0,0,.34); overflow: hidden;
    max-height: 320px; overflow-y: auto; display: none;
  }
  .suggest.on { display: block; }
  .suggest .shead {
    font-size: 10px; text-transform: uppercase; letter-spacing: .07em; color: var(--muted);
    padding: 8px 12px 5px; border-bottom: 1px solid var(--border);
  }
  .suggest .sitem {
    /* Three columns: the command, what it does, and the insert affordance. The affordance exists
       because these rows always accepted a click and nothing said so -- a grid of text reads as a
       read-only hint, so the one-click insert was invisible until someone happened to try it. */
    display: grid; grid-template-columns: 152px minmax(0,1fr) 18px; gap: 12px;
    align-items: baseline; padding: 7px 12px; cursor: pointer;
    border-left: 2px solid transparent;
  }
  .suggest .sitem:hover { background: var(--hover); }
  .suggest .sitem:hover .sgo { opacity: 1; color: var(--signal); }
  .suggest .sitem.sel { background: var(--panel-2); border-left-color: var(--accent); }
  .suggest .sitem.sel .sgo { opacity: .7; }
  .suggest .scmd { font-family: var(--mono); font-size: 12.5px; color: var(--accent); }
  .suggest .sdesc { font-size: 11.5px; color: var(--muted); line-height: 1.45; }
  /* Faint until hovered, so the list stays calm while still looking like something you can press. */
  .suggest .sgo {
    font-size: 12px; color: var(--faint); opacity: .35; text-align: right;
    transition: opacity .12s ease, color .12s ease;
  }
  .suggest .sitem.na .scmd { color: var(--faint); }
  .suggest .sitem.na .sdesc { color: var(--faint); }
  .suggest .sitem.na .sgo { display: none; }
  .suggest .sempty { padding: 10px 12px; font-size: 12px; color: var(--muted); }

  /* The bot gallery. One card per template, because the choice being made is "what should this
     agent be", and a card states the answer in a way a list of names cannot. */
  .botgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(228px, 1fr)); gap: 9px; }
  .botcard {
    border: 1px solid var(--border); border-radius: 11px; padding: 11px 12px;
    background: var(--panel-2); display: flex; flex-direction: column; gap: 5px; min-width: 0;
  }
  .botcard.done { opacity: .62; }
  .botcard .bctop { display: flex; align-items: center; gap: 8px; }
  .botcard .bcicon { font-size: 15px; color: var(--accent); flex: none; }
  .botcard .bcname { font-size: 13px; font-weight: 600; }
  .botcard .bcrole { font-size: 10.5px; font-family: var(--mono); color: var(--muted); }
  .botcard .bctag { font-size: 11.5px; color: var(--muted); line-height: 1.5; flex: 1; }
  .botcard .bcgo {
    all: unset; box-sizing: border-box; margin-top: 3px; text-align: center; cursor: pointer;
    border: 1px solid var(--border); border-radius: 8px; padding: 5px 9px; font-size: 11.5px;
    color: var(--text); min-height: 28px;
  }
  .botcard .bcgo:hover { border-color: var(--accent); color: var(--accent); }
  .botcard .bcgo:focus-visible { outline: 2px solid var(--accent); }
  .botcard .bcgo[aria-disabled="true"] { cursor: default; color: var(--muted); border-color: transparent; }
  .vendrow {
    display: flex; align-items: center; gap: 8px; padding: 7px 10px; border: 1px solid var(--border);
    border-radius: 8px; margin-bottom: 5px; font-size: 12.5px;
  }
  .vendrow .vname { font-family: var(--mono); color: var(--accent); }

  /* ---------- the startup vendor picker ----------
     Two choices, side by side, each saying whether it can be used right now. A vendor with no key is
     shown as selectable rather than hidden, because choosing it is how the user gets to the field
     that asks for the key -- hiding it would leave no path to the thing that is missing. */
  .vendpick { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 12px 0 4px; }
  .vendcard {
    text-align: left; border: 1px solid var(--border); border-radius: 11px; padding: 11px 13px;
    background: var(--panel-2); cursor: pointer; font: inherit; color: var(--text);
  }
  .vendcard:hover { border-color: var(--accent); }
  .vendcard[aria-pressed="true"] { border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent); }
  .vendcard .vcname { font-family: var(--display); font-size: 13px; display: block; }
  .vendcard .vcsub { font-size: 11px; color: var(--text-3); display: block; margin-top: 2px; }
  .vendcard .vcstate { font-size: 10.5px; margin-top: 6px; display: block; }
  .vendcard .vcstate.ready { color: var(--accent); }
  .vendcard .vcstate.needs { color: var(--amber); }
  #vendkeyfield[hidden] { display: none; }
  .vendrow .vurl { color: var(--muted); font-family: var(--mono); font-size: 11.5px; overflow: hidden;
                   text-overflow: ellipsis; white-space: nowrap; }
  .vendrow .vdel { margin-left: auto; border: 0; background: none; color: var(--muted); cursor: pointer; font-size: 15px; }
  .vendrow .vdel:hover { color: var(--err); }
  .vendrow.builtin .vname { color: var(--accent-2); }
  .vendrow .tag { font-size: 10.5px; border: 1px solid var(--border); border-radius: 20px; padding: 0 6px; color: var(--muted); }
  .actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px; }
  .actions button { border-radius: 9px; padding: 8px 16px; cursor: pointer; font-size: 13px; border: 1px solid var(--border); }
  .actions .ghost { background: var(--panel-2); color: var(--text); }
  .actions .primary { background: var(--accent); color: var(--signal-ink); border-color: var(--accent); font-weight: 600; }
  /* The mark inherits its colour from the surrounding text (fill="currentColor"), so unlike the
     four-circle logogram it replaces there is exactly one drawing rather than a per-theme pair,
     and it cannot fall out of sync with the theme it is rendered in. */
  .mark { color: var(--text); }
  .mark .core-ring { fill: var(--panel); }
  .mark .core-locus { fill: var(--signal); }
  /* the wordmark's tracking is what carries the brand when the display face is absent */
  .brand .name { font-family: var(--display); font-weight: 600; letter-spacing: var(--wordmark-tracking); text-transform: uppercase; }
  ::-webkit-scrollbar { width: 9px; height: 9px; }
  ::-webkit-scrollbar-thumb { background: var(--line-2); border-radius: 5px; }
  ::-webkit-scrollbar-track { background: transparent; }

  /* ---- local models (Ollama) --------------------------------------------------------------
     A compact list, not a card per model. Two full-page screenshots shaped this: the first version
     gave every model a bordered card with wrapped metadata and a chip row, and the second was a wide
     panel whose rows sat beside the usage statistics, squeezing the model names out of the visible
     column. So:

       * two columns only -- name, then context -- with the size right-aligned and everything else
         demoted to a tooltip;
       * no per-model border; a hairline separator and a hover background carry the grouping;
       * the name is `min-width: 0` + ellipsis so a HuggingFace path degrades by truncating rather
         than by pushing the numbers off the edge. */
  .ocard { margin-top: 6px; border: 1px solid var(--line); border-radius: 8px;
           background: var(--panel); padding: 6px 8px; max-width: 420px; }
  .ohead { display: flex; align-items: center; gap: 6px; }
  .otitle { font-family: var(--display); font-size: 10px; letter-spacing: .09em;
            text-transform: uppercase; color: var(--text-3); }
  .ostate { font-size: 10.5px; color: var(--text-3); flex: 1; min-width: 0;
            overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .orefresh { padding: 0 5px !important; font-size: 11px !important; line-height: 1.5 !important; }

  /* The list SCROLLS rather than growing. This is the whole reason the card has a bounded height:
     four local models used to stretch the status strip -- and with it the composer -- to roughly
     150px, because the strip stretches its children and the card was as tall as its rows. A panel
     about local models must not cost vertical space in the composer at a provider that is not
     local, and must not cost it here either once there are a dozen models. The faint top rule on
     each row after the first is the scroll affordance, so a cut-off list reads as "more below"
     instead of as a rendering bug. */
  .olist { display: flex; flex-direction: column; margin-top: 4px; max-height: 92px; overflow-y: auto;
           overscroll-behavior: contain; scrollbar-width: thin; }
  .orow { display: flex; align-items: baseline; gap: 8px; width: 100%;
          padding: 2px 5px; border: 0; border-radius: 5px; background: none;
          cursor: pointer; text-align: left; font: inherit; }
  .orow + .orow { box-shadow: inset 0 1px 0 var(--line); }
  .orow:hover { background: var(--panel-2); }
  .orow[aria-current="true"] { background: var(--panel-2); box-shadow: inset 2px 0 0 var(--signal); }
  .oname { flex: 1 1 auto; min-width: 0; font-family: var(--mono); font-size: 11px; color: var(--text);
           overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ometa { flex: 0 0 auto; font-size: 10.5px; color: var(--text-3);
           font-variant-numeric: tabular-nums; white-space: nowrap; }
  .ctx b { color: var(--signal); font-weight: 600; }
  .ctx s { color: var(--text-3); text-decoration: line-through; opacity: .65; }
  .owarn { flex: 0 0 auto; color: var(--amber); font-size: 11px; cursor: help; }
  /* The sentence stays in the DOM for a reader that wants it, but the card no longer gives it a
     line of its own: the title already says "Local models" and its state text already says which
     host is answering, so a third line restating both was height for nothing. */
  .onote { display: none; }
  .oempty { font-size: 11px; color: var(--text-3); padding: 3px 5px; }
  .ocard[hidden] { display: none; }

  /* ------------------------------------------------------------------------------------
     Loci, the character.
     ------------------------------------------------------------------------------------
     The SVG is generated in Python from the same manifest the CLI renders, so the two
     surfaces cannot drift -- see myriaxon/loci_svg.py. Only the mood variables live here,
     because a CSS custom property is the one thing that can change a colour in 600ms
     without redrawing anything.

     The 600ms lantern transition against a 240ms face change is deliberate and comes from
     the design spec: the lantern "warms up" slower than the face, which is what makes the
     light feel like it is responding to the mood rather than being switched.
     ------------------------------------------------------------------------------------ */
  .loci { display: inline-block; vertical-align: middle; line-height: 0; }
  .loci svg { width: 100%; height: 100%; overflow: visible; }
  .loci[data-mood="calm"]   { --lantern: #A8D8EA; --lantern-line: #6FA9C2; }
  .loci[data-mood="listen"] { --lantern: #B9A6E8; --lantern-line: #8C77C9; }
  .loci[data-mood="think"]  { --lantern: #CFE8C9; --lantern-line: #8DBF84; }
  .loci[data-mood="cheer"]  { --lantern: #FFD166; --lantern-line: #E0A93B; }
  .loci[data-mood="care"]   { --lantern: #F7A8B8; --lantern-line: #D97E92; }
  .loci[data-mood="sleep"]  { --lantern: #6E6A8F; --lantern-line: #4B4766; }
  .loci[data-mood="sorry"]  { --lantern: #E6C3A5; --lantern-line: #B98F6C; }
  .loci [data-part="lantern"] circle.lantern-body {
    transition: fill var(--t-lantern, 600ms) cubic-bezier(.4,0,.2,1),
                stroke var(--t-lantern, 600ms) cubic-bezier(.4,0,.2,1);
  }
  .loci [data-part="eyes"], .loci [data-part="mouth"], .loci [data-part="cheeks"] {
    transition: opacity var(--t-face, 240ms) cubic-bezier(.4,0,.2,1);
  }
  /* Motion. Named to match the spec so a reader can find the keyframe for any expression. */
  @keyframes loci-bob   { 0%,100% { transform: translateY(0) } 50% { transform: translateY(-3px) } }
  @keyframes loci-hop   { 0%,100% { transform: translateY(0) } 45% { transform: translateY(-12px) } }
  @keyframes loci-sway  { 0%,100% { transform: rotate(-1.5deg) } 50% { transform: rotate(1.5deg) } }
  @keyframes loci-breathe { 0%,100% { transform: scale(1) } 50% { transform: scale(1.02) } }
  @keyframes loci-tilt  { 0%,100% { transform: rotate(0) } 40% { transform: rotate(-8deg) } }
  @keyframes loci-lean  { 0%,100% { transform: rotate(0) } 50% { transform: rotate(4deg) } }
  @keyframes loci-star-wiggle { 0%,100% { transform: rotate(-8deg) } 50% { transform: rotate(8deg) } }
  @keyframes loci-window-pulse { 0%,100% { opacity: .6 } 50% { opacity: 1 } }
  .loci[data-expression="idle"] svg,
  .loci[data-expression="happy"] svg,
  .loci[data-expression="listening"] svg,
  .loci[data-expression="cheering"] svg,
  .loci[data-expression="celebrate"] svg,
  .loci[data-expression="caring"] svg,
  .loci[data-expression="sleepy"] svg { animation: loci-bob 3.2s ease-in-out infinite; }
  .loci[data-expression="happy"] svg,
  .loci[data-expression="cheering"] svg,
  .loci[data-expression="celebrate"] svg { animation: loci-hop 420ms ease-out 2; }
  .loci[data-expression="caring"] svg { animation: loci-sway 6s ease-in-out infinite; }
  .loci[data-expression="sleepy"] svg { animation: loci-breathe 4s ease-in-out infinite; }
  .loci[data-expression="confused"] svg { animation: loci-tilt 300ms ease-out forwards; }
  .loci[data-expression="listening"] svg { animation: loci-lean 400ms ease-out forwards; }
  .loci[data-expression="thinking"] [data-part="star"] { animation: loci-star-wiggle 300ms ease-in-out infinite;
                                                          transform-origin: 120px 15px; }
  .loci[data-expression="remembering"] [data-part="window"] { animation: loci-window-pulse 1.4s ease-in-out 2; }
  /* Crisis is never animated, and this rule is why it cannot be: it wins over every rule above by specificity of
     intent, not by order. A bouncing crisis face is the one rendering this project must never ship. */
  .loci[data-expression="crisis"] svg,
  .loci[data-expression="crisis"] * { animation: none !important; }
  @media (prefers-reduced-motion: reduce) {
    .loci svg, .loci * { animation: none !important; transition-duration: 1ms !important; }
  }
</style>
</head>
<body>
<template id="marktemplate">
  <!-- Myriaxon mark: eight rays converging on one ring and a signal-green core -- the myriad
       paths and the one mind. Inline SVG so it needs no network request, and drawn with
       fill="currentColor" plus var() fills so a single instance serves both themes.

       Declared once as a <template> and cloned into each placement by script(), so the sidebar
       and the header cannot drift into two slightly different drawings of the same logo. -->
  <svg class="mark" viewBox="0 0 200 200" role="img" aria-label="Myriaxon" focusable="false">
    <title>Myriaxon</title>
    <g fill="currentColor">
      <polygon points="100,6 104.5,68 100,80 95.5,68"/>
      <polygon points="100,6 104.5,68 100,80 95.5,68" transform="rotate(90 100 100)"/>
      <polygon points="100,6 104.5,68 100,80 95.5,68" transform="rotate(180 100 100)"/>
      <polygon points="100,6 104.5,68 100,80 95.5,68" transform="rotate(270 100 100)"/>
      <polygon points="100,36 103,70 100,80 97,70" transform="rotate(45 100 100)"/>
      <polygon points="100,36 103,70 100,80 97,70" transform="rotate(135 100 100)"/>
      <polygon points="100,36 103,70 100,80 97,70" transform="rotate(225 100 100)"/>
      <polygon points="100,36 103,70 100,80 97,70" transform="rotate(315 100 100)"/>
      <circle cx="100" cy="100" r="12"/>
    </g>
    <circle class="core-ring" cx="100" cy="100" r="8.5"/>
    <circle class="core-locus" cx="100" cy="100" r="4"/>
  </svg>
</template>
<aside id="sidebar">
  <div class="brand">
    <span class="markslot" data-marksize="28"></span>
    <span class="name">Myriaxon</span>
    <small>local</small>
  </div>

  <!-- Navigation. Every entry either switches the main view or opens a dialog that already exists;
       `data-ui` names which, and `refreshBadges` fills the counters from real state. Nothing here
       is a placeholder -- an entry that does nothing is worse than no entry. -->
  <div class="nav" id="nav">
    <button data-view="mission" aria-current="page"><span class="ni">◈</span><span>Mission control</span></button>
    <button data-view="chat"><span class="ni">💬</span><span>Chat</span><span class="ncount" id="navSessions"></span></button>

    <div class="navgroup">Operate</div>
    <button data-view="approvals"><span class="ni">✓</span><span>Approvals</span><span class="ncount" id="navApprovals"></span></button>
    <button data-ui="loci"><span class="ni">✳</span><span>Loci</span><span class="ncount" id="navLocuss"></span></button>
    <button data-ui="wall"><span class="ni">▦</span><span>The wall</span><span class="ncount" id="navWall"></span></button>

    <div class="navgroup">Build</div>
    <button data-ui="code"><span class="ni">🗂</span><span>Files &amp; changes</span></button>
    <button data-ui="mcp"><span class="ni">🔌</span><span>MCP servers</span><span class="ncount" id="navMcp"></span></button>
    <button data-ui="plugins"><span class="ni">🧩</span><span>Plugins</span><span class="ncount" id="navPlug"></span></button>

    <div class="navgroup">Govern</div>
    <button data-ui="rules"><span class="ni">🛡</span><span>Policies</span><span class="ncount" id="navRules"></span></button>
    <button data-ui="messaging"><span class="ni">💬</span><span>Messaging</span><span class="ncount" id="navMsg"></span></button>
    <button data-ui="settings"><span class="ni">⚙</span><span>Settings</span></button>
  </div>

  <div class="sect">Sessions<span class="proj" id="projbtn" title="Open a different project">open project…</span></div>
  <div id="sessions"></div>
  <div class="sidefoot">
    <span id="conn">connecting…</span>
    <div class="menubar">
      <button class="newbtn" id="newbtn" style="flex:1">＋ New session</button>
      <button class="themebtn" id="themebtn" title="Switch light/dark">☾ dark</button>
      <button class="menubtn" id="menubtn" title="Menu" aria-label="Menu" aria-expanded="false">☰</button>
    </div>
    <div id="menupop" class="menupop" hidden>
      <div class="menuhead"><span class="wordmark" id="menulabel">Myriaxon</span></div>
      <div class="menusect">Workspace</div>
      <button class="menuitem" id="codebtn"><span class="mi-ico">🗂</span><span>Files &amp; changes</span><kbd>changes</kbd></button>
      <button class="menuitem" id="settingsbtn"><span class="mi-ico">⚙</span><span>Settings</span></button>
      <div class="menusect">Agents</div>
      <button class="menuitem" id="locisbtn"><span class="mi-ico">✳</span><span>Loci</span><span id="locisbadge" class="badge"></span></button>
      <button class="menuitem" id="wallbtn" title="Several loci side by side, for watching a swarm work"><span class="mi-ico">▦</span><span>The wall</span><span id="wallbadge" class="badge"></span></button>
      <div class="menusect">Extensions</div>
      <button class="menuitem" id="mcpbtn"><span class="mi-ico">🔌</span><span>MCP servers</span><span id="mcpbadge" class="badge"></span></button>
      <button class="menuitem" id="plugbtn"><span class="mi-ico">🧩</span><span>Plugins</span><span id="plugbadge" class="badge"></span></button>
      <button class="menuitem" id="rulesbtn"><span class="mi-ico">🛡</span><span>Permission rules</span><span id="rulesbadge" class="badge"></span></button>
      <button class="menuitem" id="msgbtn"><span class="mi-ico">💬</span><span>Messaging</span><span id="msgbadge" class="badge"></span></button>
    </div>
  </div>
</aside>

<main id="main">
  <header>
      <!-- The character. The label is TEXT beside the avatar rather than a colour or a title
           attribute, because a mood carried only by colour is invisible to a colourblind reader and
           one carried only by an attribute is invisible to a screen reader. Three channels, one
           manifest: the same rule the terminal renderer follows. -->
      <div id="lociAvatar" class="loci" data-expression="happy" data-mood="warm" role="img"
           aria-label="Loci, hello">
        <span id="lociMood">Here</span>
      </div>
    <span class="headmark">
      <span class="markslot" data-marksize="20"></span>
      <span class="wordmark">Myriaxon</span>
    </span>
    <div class="tabs">
      <div class="tab active" data-pane="chat">Chat</div>
      <div class="tab" data-pane="trajectory">Trajectory</div>
    </div>
    <div class="spacer"></div>
    <span class="pill" id="ws">—</span>
    <span class="pill" id="provider">—</span>
  </header>

  <div id="locusbanner" hidden></div>

  <div id="chat">
    <div class="hint" id="hint">
      Myriaxon drives the same agent as <code>myriaxon</code> in your terminal.<br>
      <kbd>Enter</kbd> to send · <kbd>Shift</kbd>+<kbd>Enter</kbd> for a newline · drop or paste files to attach.
    </div>
  </div>
  <div id="trajectory"><div id="trajwrap"><div class="hint">No tool calls yet in this session.</div></div></div>

  <!-- Mission control. Every number here is read from the machine through /api/mission-control;
       nothing on this view is illustrative. Panels with nothing to report say so rather than
       showing an invented row, which is the difference between a control surface and a mockup. -->
  <div id="mc">
    <div class="mchead">
      <h1>Mission control</h1>
      <span class="msub" id="mc-summary">reading state…</span>
      <span class="mspacer"></span>
      <button class="ghost small" id="mc-refresh">Refresh</button>
      <span class="msub" id="mc-updated"></span>
    </div>

    <div class="mggrid">
      <!-- left column: what is alive -->
      <div class="mgcol">
        <section class="mcard">
          <div class="mhead">
            <div>
              <h2>Core</h2>
              <p class="mnote">Every engine routes through one agent loop. The rings show what is
                connected right now, from the same checks as the list below.</p>
            </div>
          </div>
          <div class="coreslot">
            <div class="coremap" id="mc-core" role="img" aria-label="Connection diagram"></div>
            <div style="min-width:0;flex:1">
              <div class="meters" id="mc-meters"></div>
            </div>
          </div>
        </section>

        <section class="mcard">
          <div class="mhead">
            <h2>Waiting on you <span class="mtag" id="mc-approval-count">0</span></h2>
          </div>
          <p class="mnote">A locus marks an objective blocked when it needs a decision only a person can
            make. Nothing here is guessed — an empty list means nothing is waiting.</p>
          <div id="mc-approvals"></div>
        </section>

        <section class="mcard">
          <div class="mhead">
            <h2>Runs</h2>
            <span class="msub" id="mc-runs-note"></span>
          </div>
          <div id="mc-runs"></div>
        </section>
      </div>

      <!-- right column: what is known and what was scheduled -->
      <div class="mgcol">
        <section class="mcard">
          <div class="mhead">
            <h2>Connections</h2>
            <span class="msub" id="mc-health-note"></span>
          </div>
          <div class="healthgrid" id="mc-health"></div>
        </section>

        <section class="mcard">
          <h2>Scheduled work</h2>
          <p class="mnote">Loci with open objectives. A proactive locus wakes on its interval while a
            Myriaxon process is running — its file writes still obey your permission mode.</p>
          <ul class="schedlist" id="mc-schedules"></ul>
          <div class="mgfoot">
            <button class="ghost small" id="mc-opendots">Manage loci</button>
          </div>
        </section>

        <section class="mcard">
          <h2>Model routing</h2>
          <p class="mnote">Share of requests by model in this process.</p>
          <div class="routebar" id="mc-routebar" aria-hidden="true"></div>
          <ul class="legend" id="mc-routing"></ul>
        </section>
      </div>

      <!-- full width: the live feed, then the lower three -->
      <section class="mcard mgwide">
        <div class="mhead">
          <h2>Live trace</h2>
          <div class="seg" id="mc-tracefilter" role="group" aria-label="Filter trace">
            <button aria-pressed="true" data-f="all">All</button>
            <button aria-pressed="false" data-f="tool">Tools</button>
            <button aria-pressed="false" data-f="warn">Warnings</button>
            <button aria-pressed="false" data-f="mem">Memory</button>
          </div>
        </div>
        <ul class="tracelist" id="mc-trace"></ul>
      </section>

      <section class="mcard">
        <h2>Transparency</h2>
        <p class="mnote">How much of what the machine does is shown. Each level includes everything below it,
          so the dial never hides something a lower setting would have shown.</p>
        <div id="trans-dial" class="transdial"></div>
      </section>

      <section class="mcard mgcol" style="grid-column:1/-1">
        <div class="mggrid" style="gap:16px">
          <section class="mcard" style="border:0;padding:0;background:none">
            <h2>Memory</h2>
            <p class="mnote" id="mc-mem-note"></p>
            <ul class="memlist" id="mc-memory"></ul>
          </section>
          <section class="mcard" style="border:0;padding:0;background:none">
            <h2>Skills</h2>
            <p class="mnote" id="mc-skills-note"></p>
            <div class="skillchips" id="mc-skills"></div>
          </section>
        </div>
      </section>
    </div>
  </div>

  <div id="composer">
    <div id="chips"></div>
    <div id="inputrow">
      <button class="iconbtn" id="attach" title="Attach files">📎</button>
      <textarea id="prompt" rows="1" placeholder="Message Myriaxon…  (or type / for commands)"></textarea>
      <button id="send">Send</button>
      <button id="stop" class="stop" title="Stop this turn" aria-label="Stop this turn" hidden>■</button>
      <div class="suggest" id="suggest" role="listbox" aria-label="Command suggestions"></div>
    </div>
    <div id="statusbar">
      <div class="sgroup">
        <span class="slabel">Mode</span>
        <span class="spick"><select id="mode" class="svalue" title="What the agent may do without asking"></select></span>
      </div>
      <div class="sgroup">
        <span class="slabel">Vendor</span>
        <span class="spick"><select id="provider-sel" class="svalue" title="Switch vendor; the conversation is kept"></select></span>
        <button class="sadd" id="vendormanage" title="Add or edit an endpoint" aria-label="Add or edit an endpoint">＋</button>
      </div>
      <div class="sgroup">
        <span class="slabel">Model</span>
        <span class="spick"><select id="model" class="svalue" title="Model for this session"></select></span>
      </div>
      <div id="turninfo" aria-live="polite"></div>
      <!-- Local models. Ollama is the only provider with no key and no account, so this shows what is
           actually on this machine rather than asking for credentials. It is collapsed by default
           because a user without Ollama should not have a panel about it taking up room. -->
      <div id="ollamapanel" class="ocard" hidden>
        <div class="ohead">
          <span class="otitle">Local models</span>
          <span class="ostate" id="ollamastate">checking…</span>
          <button class="ghost orefresh" id="ollamarefresh" title="Scan again">↻</button>
        </div>
        <div id="ollamalist" class="olist"></div>
        <div class="onote" id="ollamanote"></div>
      </div>
    </div>
    <input type="file" id="file" multiple hidden>
  </div>
</main>

<div id="projmodal" class="modal">
  <div class="dialog">
    <h3>Open a project</h3>
    <p class="dim">The dashboard reads, writes and uploads only inside the chosen directory.</p>
    <input id="projpath" placeholder="C:\path\to\your\project" spellcheck="false">
    <div class="recents" id="projrecents"></div>
    <div class="actions">
      <button class="ghost" id="projcancel">Cancel</button>
      <button class="primary" id="projopen">Open</button>
    </div>
  </div>
</div>

<div id="vendormodal" class="modal">
  <div class="dialog">
    <h3>Which gateway?</h3>
    <p class="dim">Both serve DeepSeek models. Pick one to start with; you can switch at any time from the
      Vendor dropdown under the composer.</p>
    <div class="vendpick" id="vendpick"></div>
    <label class="field" id="vendkeyfield" hidden>
      <span class="flabel" id="vendkeylabel">API key</span>
      <input id="vendkey" type="password" autocomplete="off" spellcheck="false" placeholder="paste the key here">
      <span class="fhint" id="vendkeyhint"></span>
    </label>
    <p class="dim" id="vendnote"></p>
    <div class="actions">
      <button class="ghost" id="vendlater">Later</button>
      <button class="primary" id="vendsave">Use this</button>
    </div>
  </div>
</div>

<div id="setmodal" class="modal">
  <div class="dialog">
    <h3>Settings</h3>
    <p class="dim">Applied to every session. Changing how the agent is built reloads it, keeping the conversation.</p>
    <div id="setform"></div>
    <div class="actions">
      <button class="ghost" id="setcancel">Close</button>
      <button class="primary" id="setreset">Reset to defaults</button>
    </div>
  </div>
</div>

<div id="vendmodal" class="modal">
  <div class="dialog">
    <h3>Vendors &amp; endpoints</h3>
    <p class="dim">Built-in vendors work out of the box. Add any OpenAI-compatible endpoint —
      a company gateway, a self-hosted runner, another provider — and it becomes selectable in the
      vendor list and from <code>/provider</code>.</p>

    <div class="recents" id="vendlist"></div>

    <div class="vendform">
      <label>Name <input id="vname" placeholder="my-gateway" spellcheck="false"></label>
      <label>Base URL <input id="vurl" placeholder="https://gateway.example.com/v1" spellcheck="false"></label>
      <label>API key <input id="vkey" type="password" placeholder="sk-… (leave blank to keep an existing key)"></label>
      <label>Models <input id="vmodels" placeholder="comma separated, or press Fetch" spellcheck="false"></label>
      <label>Model <input id="vmodel" placeholder="default model id" spellcheck="false"></label>
      <div class="vendactions">
        <button class="ghost" id="vfetch">Fetch models</button>
        <button class="ghost" id="vtest">Test</button>
        <button class="primary" id="vsave">Save</button>
      </div>
      <div id="vstatus" class="dim"></div>
    </div>

    <div class="actions">
      <button class="ghost" id="vendclose">Close</button>
    </div>
  </div>
</div>

<div id="mcpmodal" class="modal">
  <div class="dialog wide">
    <h3>MCP servers</h3>
    <p class="dim">Model Context Protocol servers give the agent extra tools. Everything below comes
      preconfigured from each server's own documentation &mdash; switch one on and it works on the next
      message. Configured servers are shared with the terminal CLI.</p>

    <div id="mcptransportwarn" class="warnbox" style="display:none"></div>
    <div class="tabs" id="mcptabs"></div>
    <div id="mcpcatalog" class="catalog"></div>

    <details style="padding-top:10px">
      <summary class="dim" style="cursor:pointer">Add a server manually</summary>
      <div class="vendform" style="padding-top:8px">
        <label>Name <input id="mname" placeholder="filesystem" spellcheck="false"></label>
        <label>Type
          <select id="mkind">
            <option value="url">Remote (HTTP URL)</option>
            <option value="stdio">Local command (stdio)</option>
          </select>
        </label>
        <label id="murlrow">URL <input id="murl" placeholder="https://mcp.figma.com/mcp" spellcheck="false"></label>
        <label id="mtokenrow">Access token <span class="dim" style="font-weight:400">optional &mdash; most hosted servers need one (Figma PAT, GitHub PAT, OAuth bearer)</span>
          <input id="mtoken" type="password" placeholder="paste the token; it is stored server-side and never returned" spellcheck="false"></label>
        <label id="mcmdrow" style="display:none">Command <input id="mcmd" placeholder="npx -y @modelcontextprotocol/server-filesystem ." spellcheck="false"></label>
        <div class="vendactions">
          <button class="primary" id="madd">Add server</button>
        </div>
        <div id="mstatus" class="dim"></div>
      </div>
    </details>

    <details class="mcpblock" id="vblock">
      <summary>Vertex context cache <span class="dim" id="vcsummary">&mdash;</span></summary>
      <p class="dim">A cache stores a repeated prefix — the system prompt and the tool catalogue — so
        later turns are billed at the cache rate instead of the full input rate. It is a
        <strong>billing resource with a lifetime</strong>: it costs money per hour while it exists, so
        it is off until you switch it on, and everything here is live from Google rather than a local
        record. Vertex will not cache a prefix below <span id="vcmin">4096</span> tokens.</p>
      <div class="vendactions">
        <button class="primary" id="vctoggle">Enable</button>
        <button class="ghost" id="vccreate">Create from this session</button>
        <button class="ghost" id="vcpurge">Delete all caches</button>
      </div>
      <div id="vcstatus" class="dim">loading…</div>
      <div class="recents" id="vclist"></div>
    </details>

    <details style="padding-top:8px">
      <summary class="dim" style="cursor:pointer">Search the public MCP registry</summary>
      <div class="vendform" style="padding-top:8px">
        <label>Search <input id="mquery" placeholder="filesystem, github, sqlite&hellip;" spellcheck="false"></label>
        <div class="vendactions">
          <button class="ghost" id="msearch">Search</button>
        </div>
        <div class="recents" id="mresults"></div>
      </div>
    </details>

    <div class="sect" style="padding-top:12px">already configured</div>
    <div class="recents" id="mcplist"></div>

    <div class="actions">
      <button class="ghost" id="mcpclose">Close</button>
    </div>
  </div>
</div>

<div id="rulesmodal" class="modal">
  <div class="dialog">
    <h3>Permission rules</h3>
    <p class="dim">Decide what the agent may do without asking. Rules are written to your user
      settings file; a project or system file still outranks them, so a rule here can never weaken
      an administrative policy.</p>

    <div id="ruleslist"></div>

    <div class="vendform">
      <label>Tool <input id="rtool" placeholder="run_bash  ·  write_file  ·  *" spellcheck="false"></label>
      <label>Argument pattern <span class="dim" style="font-weight:400">optional — e.g. <code>git *</code>, <code>*.md</code></span>
        <input id="rpattern" placeholder="leave empty to match every call of that tool" spellcheck="false"></label>
      <label>Decision
        <select id="rdecision">
          <option value="allow">allow — run without asking</option>
          <option value="ask">ask — always confirm, even with auto-approval on</option>
          <option value="deny">deny — never run, cannot be overridden</option>
        </select>
      </label>
      <div class="vendactions">
        <button class="primary" id="radd">Add rule</button>
      </div>
      <div id="rstatus" class="dim"></div>
    </div>

    <div class="sect" style="padding:14px 0 4px">examples</div>
    <div class="recents" id="rexamples"></div>

    <div class="actions">
      <button class="ghost" id="rulesclose">Close</button>
    </div>
  </div>
</div>

<div id="codemodal" class="modal">
  <div class="dialog wide">
    <h3>Files &amp; changes <span id="codebranch" class="dim" style="font-weight:400;font-size:12px"></span></h3>

    <div class="tabs">
      <button class="tab active" data-codetab="files">Files</button>
      <button class="tab" data-codetab="changes">Changes <span id="codecount"></span></button>
    </div>

    <div id="codepane-files" class="codepane">
      <div id="codepath" class="dim" style="font-family:var(--mono);font-size:11.5px;padding-bottom:6px"></div>
      <div id="codelist" class="filelist"></div>
    </div>

    <div id="codepane-changes" class="codepane" style="display:none">
      <div id="codechanges" class="filelist"></div>
    </div>

    <div id="codeviewer" class="codeviewer" style="display:none">
      <div class="codehead">
        <span id="codetitle" class="dim" style="font-family:var(--mono);font-size:11.5px"></span>
        <span>
          <button class="ghost small" id="codestagedtoggle" style="display:none">staged</button>
          <button class="ghost small" id="codeback">back</button>
        </span>
      </div>
      <div id="codebody" class="codebody"></div>
    </div>

    <div class="actions">
      <button class="ghost" id="coderefresh">Refresh</button>
      <button class="ghost" id="codeclose">Close</button>
    </div>
  </div>
</div>

<div id="msgmodal" class="modal">
  <div class="dialog wide">
    <h3>Messaging</h3>
    <p class="dim">Drive this harness from a chat app, and get a summary when a turn finishes.
      Messages arrive at the webhook path <code>/api/inbound</code>. Nothing is accepted until a number
      is listed under Access below — an agent that runs shell commands, reachable by anyone who finds
      the number, is a remote code execution service.</p>

    <div class="fieldset">
      <div class="fshead">Service</div>
      <label class="field">
        <span class="flabel">Provider</span>
        <select id="msgprovider">
          <option value="twilio">Twilio (WhatsApp)</option>
          <option value="meta">Meta WhatsApp Cloud API</option>
          <option value="generic">Generic webhook / bridge</option>
        </select>
      </label>
    </div>

    <div class="fieldset">
      <div class="fshead">Access</div>
      <label class="chk">
        <input type="checkbox" id="msgenabled">
        <span>Accept inbound messages</span>
      </label>
      <label class="field">
        <span class="flabel">Allowed numbers <span class="fhint">— comma separated</span></span>
        <input id="msgallow" placeholder="+15551234567, +15559876543" spellcheck="false">
      </label>
      <div class="statusline" id="msgaccess-note">
        <span class="dotmark"></span>
        <span id="msgaccess-text">Nobody may drive the agent — no numbers listed.</span>
      </div>
    </div>

    <div class="fieldset">
      <div class="fshead">Notifications</div>
      <label class="field">
        <span class="flabel">Send a summary to <span class="fhint">— optional</span></span>
        <input id="msgnotify" placeholder="+15551234567" spellcheck="false">
      </label>
    </div>

    <div class="fieldset">
      <div class="fshead">Webhook authentication</div>
      <label class="field">
        <span class="flabel">Shared secret <span class="fhint">— optional; required in the <code>X-Ioh-Secret</code> header when set</span></span>
        <input id="msgsecret" type="password" placeholder="leave blank to keep the current value" spellcheck="false">
      </label>
      <label class="chk">
        <input type="checkbox" id="msgclearsecret">
        <span>Remove the stored shared secret</span>
      </label>
    </div>

    <div class="fieldset" id="msgtwilio">
      <div class="fshead">Twilio credentials</div>
      <label class="field">
        <span class="flabel">Account SID</span>
        <input id="msgsid" placeholder="ACxxxxxxxx" spellcheck="false">
      </label>
      <label class="field">
        <span class="flabel">Auth token</span>
        <input id="msgtoken" type="password" placeholder="leave blank to keep the current value" spellcheck="false">
      </label>
      <label class="field">
        <span class="flabel">Send from</span>
        <input id="msgfrom" placeholder="whatsapp:+14155238886" spellcheck="false">
      </label>
    </div>

    <div class="fieldset" id="msgmeta">
      <div class="fshead">Meta Cloud API credentials</div>
      <label class="field">
        <span class="flabel">Phone number ID</span>
        <input id="msgpnid" placeholder="1234567890" spellcheck="false">
      </label>
      <label class="field">
        <span class="flabel">Access token</span>
        <input id="msgacctoken" type="password" placeholder="leave blank to keep the current value" spellcheck="false">
      </label>
    </div>

    <div class="fieldset" id="msggeneric">
      <div class="fshead">Bridge credentials</div>
      <label class="field">
        <span class="flabel">Send URL</span>
        <input id="msgsendurl" placeholder="https://your-bridge.example.com/send" spellcheck="false">
      </label>
    </div>

    <div class="statusline" id="msgstats">
      <span class="dotmark"></span>
      <span id="msgstats-text">No messages yet.</span>
    </div>
    <div id="msgstatus"></div>

    <div class="actions">
      <button class="ghost" id="msgclose">Close</button>
      <button class="primary" id="msgsave">Save</button>
    </div>
  </div>
</div>

<div id="plugmodal" class="modal">
  <div class="dialog">
    <h3>Plugins</h3>
    <p class="dim">A plugin is a Python file in a <code>plugins/</code> directory that adds tools or
      observes hooks. Drop a file in and press Reload — nothing is downloaded or installed for you.</p>

    <div id="plugdirs" class="dim" style="font-family:var(--mono);font-size:11.5px;margin-bottom:8px"></div>
    <div id="pluglist"></div>

    <div class="sect" style="padding:14px 0 4px">writing one</div>
    <pre class="plugin-doc"><code>PLUGIN = {"name": "acme", "version": "1.0"}

def register(api):
    api.add_tool("acme_echo", "Echo text",
                 {"type": "object", "properties": {"text": {"type": "string"}}},
                 lambda tool_input, ctx: tool_input.get("text", ""),
                 mutating=False)
    api.on("pre_tool_use", my_gate)   # return a string to block the call</code></pre>

    <div class="actions">
      <button class="ghost" id="plugclose">Close</button>
      <button class="primary" id="plugreload">Reload plugins</button>
    </div>
  </div>
</div>

<div id="locismodal" class="modal">
  <div class="dialog widest" id="locisdialog">
    <h3 id="locistitle">Loci</h3>
    <p class="dim" id="locisintro">Persistent agents with their own role, standing instructions and objectives.
      <b>This page is theirs alone</b> — opening a locus here does not take over the Myriaxon chat, and a locus
      turn never appears in it. Run, pause, wake or delete any of them from the roster on the left.</p>

    <div class="locilayout" id="locilayout">

      <!-- ---------------------------------------------------------------- the roster -->
      <div class="locifleet">
        <div class="fieldset">
          <div class="fshead">Your loci <span id="lociscount" class="fhint"></span>
            <span class="fhint" style="margin-left:auto; display:flex; gap:6px; align-items:center">
              <button class="ghost small" id="locistoggletemplates">Templates</button>
              <button class="ghost small" id="locisnew">New locus</button>
              <button class="ghost small" id="locisrefresh2" title="Re-read loci.json">↻</button>
            </span>
          </div>
          <div id="locislist" class="locilist"></div>
        </div>

        <div class="fieldset" id="locistemplates" hidden>
          <div class="fshead">Start from a template
            <span class="fhint">— each is a working agent with instructions written for the job</span></div>
          <div class="botgrid" id="bottemplates"></div>
        </div>

        <div class="fieldset" id="locisform" hidden>
          <div class="fshead">New locus</div>
          <div class="locusform">
            <div class="row2">
              <label class="field">
                <span class="flabel">Name</span>
                <input id="locusname" placeholder="release-notes" autocomplete="off">
              </label>
              <label class="field">
                <span class="flabel">Role <span class="fhint">— what kind of worker it is</span></span>
                <input id="locusrole" placeholder="release manager" autocomplete="off">
              </label>
            </div>
            <label class="field">
              <span class="flabel">Objectives <span class="fhint">— one per line; it works through these in order</span></span>
              <textarea id="locusgoals" placeholder="Keep CHANGELOG.md current after every merge"></textarea>
            </label>
            <label class="field">
              <span class="flabel">Standing instructions <span class="fhint">— standards and constraints it must keep to</span></span>
              <textarea id="locusinstr" placeholder="Never invent an entry; describe only changes present in git log."></textarea>
            </label>
            <label class="chk">
              <input type="checkbox" id="locusproactive">
              <span>Work on its own interval, without being asked</span>
            </label>
            <div class="row2">
              <label class="field">
                <span class="flabel">Wake every <span class="fhint">— seconds, minimum 30</span></span>
                <input id="locusevery" type="number" min="30" value="900">
              </label>
              <div style="display:flex;align-items:flex-end">
                <button class="primary" id="locuscreate" style="width:100%">Create locus</button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- ------------------------------------------------------------ its own chat -->
      <div class="locichat" id="locichatpane">
        <div class="lc-head">
          <span class="lc-avatar loci" id="locusavatar" data-expression="idle" data-mood="calm"
                role="img" aria-label="Locus"></span>
          <div class="lc-who">
            <div class="lc-name" id="locuschatname">No locus selected</div>
            <div class="lc-sub" id="locuschatsub">Pick one on the left to see its conversation.</div>
          </div>
          <span class="lc-state" id="locuschatstate"></span>
        </div>

        <div class="lc-controls" id="locusctrls" hidden>
          <button class="ghost small" id="lc-enable" title="Allow or refuse runs of this locus">Enable</button>
          <button class="ghost small" id="lc-proactive" title="Let it wake on its own interval">Wake on interval</button>
          <button class="ghost small" id="lc-autonomy" title="Whether it may decide its own work">Works your objectives</button>
          <button class="ghost small" id="lc-run" title="Advance its next objective now">Run objective</button>
          <button class="ghost small" id="lc-stop" title="Stop the turn this locus is running" hidden>Stop</button>
          <button class="ghost small" id="lc-refresh" title="Reload its conversation and state">Refresh</button>
          <button class="ghost small danger" id="lc-delete" title="Remove this locus and its file">Delete</button>
        </div>
        <!-- Shown only while the locus is self-directed. It exists so "autonomous" cannot be read as
             "unrestricted": the limit is on screen next to the control that grants the freedom. -->
        <div class="lc-bound" id="lc-bound" hidden></div>

        <div class="lc-transcript" id="locustranscript">
          <div class="lc-empty">A locus keeps one conversation across runs, shown here. Nothing it does is
            written into the Myriaxon chat.</div>
        </div>

        <form class="lc-composer" id="locuscomposer">
          <textarea id="locusmessage" rows="1" placeholder="Message this locus…  (Enter sends, Shift+Enter for a new line)"></textarea>
          <button class="primary" id="locusend" type="submit">Send</button>
        </form>

        <div class="lc-detail" id="locusdetail"></div>
      </div>
    </div>

    <div class="statusline" id="locistatusline">
      <span class="dotmark"></span>
      <span id="locisstatus">Ready.</span>
    </div>

    <div class="actions">
      <button class="ghost" id="locirefresh">Refresh roster</button>
      <button class="ghost" id="lociclose">Close</button>
    </div>
  </div>
</div>

<!-- ============================================================ the pane wall -->
<!--
  Several loci side by side, so a multi-agent run can be WATCHED rather than inferred. The single-pane view
  answers "what did this one do"; this answers "what are they doing to each other", which is the question a
  swarm actually raises and the one a one-at-a-time roster cannot show.

  A separate modal rather than a mode inside the roster, because the two have different shapes: the roster is
  a list with a detail pane, and this is a grid of equals. Forcing them into one dialog would make the roster
  pay for the grid's layout, and the roster is the view people use most.
-->
<div id="wallmodal" class="modal">
  <div class="dialog wall-dialog">
    <h3>The wall <span class="dim" style="font-weight:400" id="wallhint"></span></h3>
    <p class="dim">Up to nine agents at once. <b>Drag a pane by its title bar</b> to move or swap it, or drag a
      name in from the roster on the right. Every pane polls on one shared timer, so watching more of them does
      not ask the server more often.</p>

    <div class="wall-bar">
      <div class="wall-layouts" role="group" aria-label="Grid size">
        <span class="dim">Grid</span>
        <button class="ghost small" data-wall-cols="1" title="One pane">1</button>
        <button class="ghost small" data-wall-cols="2" title="Two across">2</button>
        <button class="ghost small" data-wall-cols="3" title="Three across">3</button>
      </div>
      <span class="wall-spacer"></span>
      <label class="wall-toggle"><input type="checkbox" id="wall-links"> Show who is talking to whom</label>
      <button class="ghost small" id="wall-live">Pause</button>
      <button class="ghost small" id="wallclear" title="Empty every pane">Clear</button>
    </div>

    <div class="wall-grid" id="wallgrid" data-cols="2"></div>

    <!-- Sits directly under the grid and is hidden until something actually fails. Above the roster rather
         than at the bottom of the dialog, because a message about the thing you are looking at has to be
         where you are looking. -->
    <div class="wall-errors" id="wall-errors" role="alert" hidden></div>

    <div class="wall-foot">
      <div class="fieldset wall-roster">
        <div class="fshead">Drag one in <span class="fhint" id="wallrosterhint"></span></div>
        <div id="wallroster" class="wall-roster-list"></div>
      </div>
    </div>

    <div class="statusline" id="wallstatusline">
      <span class="dotmark"></span>
      <span id="wallstatus">Ready.</span>
    </div>

    <div class="actions">
      <button class="ghost" id="wallrefresh">Refresh now</button>
      <button class="ghost" id="wallclose">Close</button>
    </div>
  </div>
</div>

<script>

/* ---------- Loci, the character ----------
   The three rules in this block are the ones that were defects when written the obvious way.

   LOCI_CACHE exists because the avatar is an SVG fetched from the server, and without a cache every keystroke that
   changed the mood would be a round trip. The images are immutable for a session -- one per expression -- so the
   cache can never go stale within a page life.

   The `dataset.expression === expression` guard exists because responses can arrive out of order: type fast enough
   and "thinking" can land after "cheering", leaving the header showing a mood the session is no longer in. Only the
   LATEST request is allowed to draw.

   The mood labels are duplicated here from the manifest because the dashboard has no server-rendered mood for a
   state it has not fetched yet. `setLoci` is the only writer, which is what keeps the two in step. */
const LOCI_CACHE = new Map();
// The labels are loci.md section 4's "Label shown to user" column VERBATIM. They used to be paraphrases -- "Hello"
// for Happy, "Nicely done" for Proud of you, "Something is wrong" for Checking in -- so the dashboard showed a user
// different words than the specification published for the same face. Two surfaces disagreeing about what to call a
// face is worse than either being wrong, because neither can be corrected.
const LOCI_LABELS = {
  idle: "Here", happy: "Happy", listening: "Listening", thinking: "Thinking",
  remembering: "Remembering", cheering: "Proud of you", caring: "With you",
  concerned: "Checking in", crisis: "Here with you", confused: "Hmm?",
  sleepy: "Resting", sorry: "Oops", focus: "Focus mode", celebrate: "Yay!",
  // "Go on", not "Listening": the two faces are the same art, and the label is what distinguishes "you are
  // typing" from "keep going, I am still here".
  listening_back: "Go on",
};

async function setLoci(expression) {
  const box = document.getElementById("lociAvatar");
  const label = document.getElementById("lociMood");
  if (!box) return;
  // Recorded BEFORE the fetch, so a slow response for an old expression cannot win the race below.
  box.dataset.expression = expression;
  if (label) label.textContent = LOCI_LABELS[expression] || "Here";
  if (LOCI_CACHE.has(expression)) {
    drawLoci(box, LOCI_CACHE.get(expression), expression);
    return;
  }
  try {
    const response = await fetch(`/api/avatar?expression=${encodeURIComponent(expression)}&size=34`);
    if (!response.ok) return;
    const svg = await response.text();
    LOCI_CACHE.set(expression, svg);
    drawLoci(box, svg, expression);
  } catch (err) {
    // A character that cannot be drawn must never break the page it lives on.
    console.debug("loci: could not draw", expression, err);
  }
}

function drawLoci(box, svg, expression) {
  // The guard. A response for an expression the session has already left is discarded rather than drawn.
  if (box.dataset.expression !== expression) return;
  const old = box.querySelector("svg");
  if (old) old.remove();
  box.insertAdjacentHTML("afterbegin", svg);
}

// Drawn on load, so the header is never an empty box before the first turn.
setLoci("happy");

(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const state = { session: null, config: null, streaming: false, attachments: [], source: null,
                  traj: [], assistantEl: null, thinkEl: null, recovering: false, dotName: "",
                  checkedAt: 0, wallTranscripts: {}, wallLinks: [], wallLinkWired: false };
  const NAMES = { manual: "manual", auto_edit: "auto edit", plan: "plan", auto: "auto" };

  // ---------- brand mark ----------
  // The mark lives in a <template> and is cloned into every .markslot on the page. One drawing,
  // many placements: duplicating the SVG per location is how a logo ends up subtly different in
  // the sidebar and the header. `data-marksize` sets the rendered size so the same artwork serves
  // a 28px sidebar mark and a 20px header mark.
  function stampMarks() {
    const tpl = $("marktemplate");
    if (!tpl) return;
    document.querySelectorAll(".markslot").forEach((slot) => {
      if (slot.firstElementChild) return;   // already stamped
      const node = tpl.content.cloneNode(true);
      const svg = node.querySelector("svg");
      const size = slot.dataset.marksize || "28";
      if (svg) { svg.setAttribute("width", size); svg.setAttribute("height", size); }
      slot.appendChild(node);
    });
  }
  stampMarks();

  // Messages are built after the initial stamp, so their mark slots need stamping too. A constant
  // rather than a literal in three places: the assistant's avatar, the buffering indicator and the
  // streaming state all have to be the same artwork at the same size. `stampMarks()` skips slots
  // that already hold artwork, so calling it after each append cannot double-draw.
  const ASSISTANT_AVATAR = `<span class="markslot" data-marksize="17"></span>`;

  // ---------- markdown ----------
  // A small block-then-inline renderer. The previous version did ordered string replacement, which
  // left raw `**bold**`, `### headings`, `---` rules and pipe tables visible in the transcript --
  // measured directly in the UI. Rendering block-by-block first, then handling inline spans only
  // inside text runs, is what makes tables and multi-paragraph answers come out right.
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function inline(text) {
    // Protect inline code spans from every other rule by swapping them out first.
    const codes = [];
    let out = text.replace(/`([^`]+)`/g, (_, code) => {
      codes.push(`<code>${esc(code)}</code>`);
      return `\u0001${codes.length - 1}\u0001`;
    });
    out = esc(out)
      .replace(/\*\*\*(.+?)\*\*\*/g, "<strong><em>$1</em></strong>")
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s).,]|$)/g, "$1<em>$2</em>")
      .replace(/(^|[\s(])_([^_\n]+)_(?=[\s).,]|$)/g, "$1<em>$2</em>")
      .replace(/~~(.+?)~~/g, "<del>$1</del>")
      // Markdown links must be handled BEFORE bare URLs, or the URL inside the parentheses is
      // linkified first and the surrounding [text](...) survives as literal characters.
      .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
      .replace(/(https?:\/\/[^\s<)]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');
    return out.replace(/\u0001(\d+)\u0001/g, (_, i) => codes[+i]);
  }

  function splitRow(line) {
    return line.replace(/^\s*\|/, "").replace(/\|\s*$/, "").split("|").map((c) => c.trim());
  }

  function md(src) {
    if (!src) return "";
    const lines = String(src).replace(/\r\n?/g, "\n").split("\n");
    const html = [];
    let i = 0;

    while (i < lines.length) {
      const line = lines[i];

      // fenced code
      const fence = line.match(/^\s*```(\w*)\s*$/);
      if (fence) {
        const body = [];
        i++;
        while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) body.push(lines[i++]);
        i++;
        html.push(`<pre><code>${esc(body.join("\n"))}</code></pre>`);
        continue;
      }

      // table: a pipe header followed by a separator row of dashes
      if (/\|/.test(line) && i + 1 < lines.length && /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(lines[i + 1]) && /-/.test(lines[i + 1])) {
        const header = splitRow(line);
        i += 2;
        const rows = [];
        while (i < lines.length && /\|/.test(lines[i]) && lines[i].trim()) rows.push(splitRow(lines[i++]));
        let table = "<table><thead><tr>" + header.map((c) => `<th>${inline(c)}</th>`).join("") + "</tr></thead><tbody>";
        rows.forEach((row) => {
          table += "<tr>" + header.map((_, idx) => `<td>${inline(row[idx] === undefined ? "" : row[idx])}</td>`).join("") + "</tr>";
        });
        html.push(table + "</tbody></table>");
        continue;
      }

      // horizontal rule
      if (/^\s*([-*_])\s*\1\s*\1[\s\-*_]*$/.test(line)) {
        html.push("<hr>");
        i++;
        continue;
      }

      // headings
      const heading = line.match(/^\s{0,3}(#{1,6})\s+(.*)$/);
      if (heading) {
        const level = heading[1].length;
        html.push(`<h${level}>${inline(heading[2].replace(/\s*#+\s*$/, ""))}</h${level}>`);
        i++;
        continue;
      }

      // blockquote
      if (/^\s*>\s?/.test(line)) {
        const body = [];
        while (i < lines.length && /^\s*>\s?/.test(lines[i])) body.push(lines[i++].replace(/^\s*>\s?/, ""));
        html.push(`<blockquote>${md(body.join("\n"))}</blockquote>`);
        continue;
      }

      // lists: group consecutive items, allowing continuation lines
      const bullet = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;
      if (bullet.test(line)) {
        const ordered = /^\s*\d/.test(line);
        const items = [];
        while (i < lines.length && bullet.test(lines[i])) {
          const match = lines[i].match(bullet);
          let text = match[3];
          i++;
          // a nested list or an indented continuation belongs to this item
          while (i < lines.length && lines[i].trim() && !bullet.test(lines[i]) && /^\s{2,}\S/.test(lines[i])) {
            text += "\n" + lines[i].trim();
            i++;
          }
          items.push(`<li>${inline(text)}</li>`);
        }
        html.push(ordered ? `<ol>${items.join("")}</ol>` : `<ul>${items.join("")}</ul>`);
        continue;
      }

      // blank line
      if (!line.trim()) {
        i++;
        continue;
      }

      // paragraph: consume until a blank line or the start of another block
      const para = [];
      while (
        i < lines.length &&
        lines[i].trim() &&
        !/^\s*```/.test(lines[i]) &&
        !/^\s{0,3}#{1,6}\s/.test(lines[i]) &&
        !bullet.test(lines[i]) &&
        !/^\s*>\s?/.test(lines[i]) &&
        !/^\s*([-*_])\s*\1\s*\1[\s\-*_]*$/.test(lines[i])
      ) {
        para.push(lines[i++]);
      }
      if (para.length) html.push(`<p>${inline(para.join("\n")).replace(/\n/g, "<br>")}</p>`);
    }
    return html.join("\n");
  }

  // ---------- api ----------
  async function api(path, options) {
    const res = await fetch(path, options);
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch { data = { raw: text }; }
    if (!res.ok) throw new Error((data && (data.error || data.kind)) || res.statusText);
    return data;
  }
  const post = (p, body) => api(p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  // The file explorer and diff viewer read through this. It is a thin alias for api() so those call
  // sites read like the request they make, rather than repeating the fetch contract each time.
  const get = (p) => api(p, { method: "GET" });

  // ---------- rendering ----------
  function atBottom() { const c = $("chat"); return c.scrollHeight - c.scrollTop - c.clientHeight < 140; }
  function scroll(force) { const c = $("chat"); if (force || atBottom()) c.scrollTop = c.scrollHeight; }
  function clearHint() { const h = $("hint"); if (h) h.remove(); }

  // Who is speaking. An ordinary session is "myriaxon"; a session owned by a locus speaks as that locus,
  // so the transcript matches the agent's own identity -- it was answering as "analyst" in the text
  // while the label above it still said myriaxon, which made the reply look like it came from the
  // wrong agent.
  function speakerName() {
    return (state.locusName || "myriaxon");
  }

  // Whether you are talking to Myriaxon or to one of your loci.
  //
  // A locus keeps its own persistent conversation, so this view can be showing "analyst" while the
  // header says Myriaxon -- and the way to stop talking to the locus is `/loci disable <name>`, which
  // was not discoverable from here at all. The banner states who is answering and how to get back.
  function showLocusBanner(name) {
    const host = $("locusbanner");
    if (!host) return;
    if (!name) {
      host.hidden = true;
      host.innerHTML = "";
      return;
    }
    host.hidden = false;
    host.innerHTML = `<span class="dotmark" aria-hidden="true"></span>
      <span class="locustext">Speaking as <b>${esc(name)}</b> — its own persistent conversation.</span>
      <span class="locusacts">
        <button class="ghost small" id="locusdisable">Stop being ${esc(name)}</button>
      </span>`;
    const button = $("locusdisable");
    if (button) {
      button.onclick = async () => {
        try {
          // The API action is `toggle` with the desired state, and the field is `locus` -- not `name`.
          // Verified against the route: `{action, name, enabled}` returns 404 "no locus named None"
          // because the server reads `body["locus"]`, so the banner's button reported a failure while
          // the locus carried on answering. The action name was right and the field name was not.
          await post("/api/loci", { action: "toggle", locus: name, enabled: false });
          addNotice(`${name} disabled — this conversation stays, but it will not answer as ${name}.`,
                    "success");
          showLocusBanner("");
        } catch (err) {
          addNotice("could not disable " + name + ": " + err.message, "error");
        }
      };
    }
  }

  function addMessage(role, text) {
    clearHint();
    const wrap = document.createElement("div");
    wrap.className = "msg " + role;
    // The assistant gets the brand mark as its avatar; the user gets their initial, because a
    // person has no logo and a circle with "You" in it says nothing the layout does not.
    const who = role === "user" ? "You" : speakerName();
    wrap.innerHTML = `<div class="who">${role === "user" ? "You" : ASSISTANT_AVATAR}</div>
      <div class="body"><div class="role">${role === "user" ? "you" : esc(who)}</div>
      <div class="content"></div></div>`;
    wrap.querySelector(".content").innerHTML = md(text || "");
    $("chat").appendChild(wrap);
    stampMarks();
    scroll(true);
    return wrap.querySelector(".content");
  }

  // Yellow buffering indicator shown from turn start until the first token arrives. Gemini reports
  // 0 streamed thought parts (verified: thinking arrives only as a token count), so there is no
  // reasoning text to display while it works -- this shows that work is happening instead.
  function showBuffering() {
    clearHint();
    const wrap = document.createElement("div");
    wrap.className = "msg assistant";
    wrap.id = "buffering-msg";
    wrap.innerHTML = `<div class="who streaming">${ASSISTANT_AVATAR}</div>
      <div class="body"><div class="role">${esc(speakerName())}</div>
      <div class="buffering"><span class="loci"><span></span><span></span><span></span></span>
      <span class="label">thinking</span><span class="elapsed" id="buffering-elapsed"></span></div></div>`;
    $("chat").appendChild(wrap);
    stampMarks();
    // Elapsed seconds are the one thing CSS cannot do, and they matter here: a cold start is long
    // enough that "is this stuck?" is a real question. 1s interval keeps the cost negligible.
    const started = Date.now();
    state.bufferTimer = setInterval(() => {
      const el = $("buffering-elapsed");
      if (el) el.textContent = ((Date.now() - started) / 1000).toFixed(0) + "s";
    }, 1000);
    scroll(true);
  }

  function clearBuffering() {
    if (state.bufferTimer) { clearInterval(state.bufferTimer); state.bufferTimer = null; }
    const el = $("buffering-msg");
    if (el) el.remove();
  }

  function addNotice(text, severity) {
    clearHint();
    const el = document.createElement("div");
    el.className = "notice" + (severity && severity !== "normal" ? " " + severity : "");
    el.textContent = text.trim();
    $("chat").appendChild(el);
    scroll();
  }

  function addThinking(text) {
    clearHint();
    if (!state.thinkEl) {
      const d = document.createElement("details");
      d.className = "think";
      d.innerHTML = `<summary>reasoning</summary><div class="thinking"></div>`;
      $("chat").appendChild(d);
      state.thinkEl = d.querySelector(".thinking");
    }
    state.thinkEl.textContent += text;
    scroll();
  }

  function addTool(tool, args, isError, result, durationMs) {
    clearHint();
    const d = document.createElement("details");
    d.className = "tool" + (isError ? " err" : "");
    let pretty = "";
    try { pretty = JSON.stringify(args, null, 2); } catch { pretty = String(args); }
    d.innerHTML = `<summary><span class="name">${esc(tool)}</span>
        <span class="meta">${durationMs != null ? Math.round(durationMs) + " ms" : ""}${isError ? " · failed" : ""}</span></summary>
      <pre><code>${esc(pretty)}</code></pre>${result ? `<pre><code>${esc(result)}</code></pre>` : ""}`;
    $("chat").appendChild(d);
    state.traj.push({ tool, args, is_error: isError, result, duration_ms: durationMs });
    renderTrajectory();
    scroll();
  }

  function renderTrajectory() {
    const wrap = $("trajwrap");
    if (!state.traj.length) { wrap.innerHTML = `<div class="hint">No tool calls yet in this session.</div>`; return; }
    wrap.innerHTML = "";
    state.traj.forEach((ev, i) => {
      const d = document.createElement("details");
      d.className = "trajrow";
      let pretty = ""; try { pretty = JSON.stringify(ev.args, null, 2); } catch { pretty = String(ev.args); }
      d.innerHTML = `<summary><span class="idx">#${i + 1}</span><span class="name">${esc(ev.tool)}</span>
          ${ev.is_error ? '<span style="color:var(--err)">failed</span>' : ""}
          <span class="dur">${ev.duration_ms != null ? Math.round(ev.duration_ms) + " ms" : ""}</span></summary>
        <pre><code>${esc(pretty)}</code></pre>${ev.result ? `<pre><code>${esc(ev.result)}</code></pre>` : ""}`;
      wrap.appendChild(d);
    });
  }

  // ---------- sessions ----------
  async function loadSessions() {
    const data = await api("/api/sessions");
    const box = $("sessions");
    box.innerHTML = "";
    data.sessions.forEach((s) => {
      const el = document.createElement("div");
      el.className = "sess" + (state.session === s.id ? " active" : "");
      el.title = `${s.provider}:${s.model} · ${s.mode}`;
      el.innerHTML = `${s.busy ? '<span class="busy"></span>' : ""}<span class="label">${esc(s.title || "New session")}</span><button class="del" title="Delete this session">×</button>`;
      el.onclick = () => attach(s.id);
      el.querySelector(".del").onclick = async (ev) => {
        // Stop the click from also selecting the session being deleted.
        ev.stopPropagation();
        if (!confirm(`Delete session "${s.title || "New session"}"?`)) return;
        try {
          await api("/api/sessions/" + encodeURIComponent(s.id), { method: "DELETE" });
          if (state.session === s.id) {
            state.session = null; state.traj = []; renderTrajectory();
            $("chat").innerHTML = `<div class="hint" id="hint">Session deleted. Send a message to start a new one.</div>`;
          }
          await loadSessions();
        } catch (err) { addNotice("could not delete session: " + err.message, "error"); }
      };
      box.appendChild(el);
    });
  }

  async function newSession() {
    const data = await post("/api/sessions", { mode: $("mode").value });
    state.session = data.session.id;
    state.traj = []; renderTrajectory();
    $("chat").innerHTML = `<div class="hint" id="hint">New session. Send a message to begin.</div>`;
    state.assistantEl = null; state.thinkEl = null;
    await loadSessions();
    connect();
  }

  // Session ids are held in server memory, not on disk, so any restart invalidates every id a
  // browser is still holding -- and so does opening a second tab against a different workspace.
  // "unknown session" is therefore an ordinary event, not an error the user should have to
  // understand: the honest response is to move to a session that does exist and say so once.
  function isUnknownSession(err) {
    const text = String((err && err.message) || err || "").toLowerCase();
    return text.includes("unknown session") || text.includes("404");
  }

  async function attach(sessionId, options) {
    const quiet = !!(options && options.quiet);
    state.session = sessionId;
    state.traj = [];
    $("chat").innerHTML = "";
    let loaded = true;
    try {
      const data = await api("/api/messages?session=" + encodeURIComponent(sessionId));
      (data.messages || []).forEach((m) => {
        if (m.role === "user") addMessage("user", m.text || "");
        else if (m.text) addMessage("assistant", m.text);
      });
      state.traj = (data.trajectory || []).map((t) => ({ tool: t.tool, args: t.args, is_error: t.is_error, result: t.result, duration_ms: t.duration_ms }));
      renderTrajectory();
      // Which locus owns this session, so the transcript is labelled with the agent that actually
      // answers rather than always saying "myriaxon".
      const sessionState = data.state || {};
      state.locusName = sessionState.locus || "";
      showLocusBanner(state.locusName);
      // The usage line is filled from the transcript's own payload. It used to be written only on
      // `turn_end`, so opening a session -- or reloading the page -- showed an empty status line for
      // a conversation that had plainly cost something.
      if (data.usage && Object.keys(data.usage).length) {
        const seconds = data.state && data.state.updated_at && data.state.created_at
          ? Math.max(0, data.state.updated_at - data.state.created_at) : 0;
        renderTurnInfo(data.usage, seconds);
      } else {
        // `innerHTML`, not `textContent`: the line is now a row of stat cells, and setting
        // textContent on a node that has element children leaves them in place.
        $("turninfo").innerHTML = "";
        $("turninfo").title = "";
      }
    } catch (err) {
      loaded = false;
      if (!isUnknownSession(err)) {
        addNotice("could not load session: " + err.message, "error");
      }
    }
    await loadSessions();
    connect();
    return loaded;
  }

  // Called when a session turns out not to exist. Tries the newest session that does, and only
  // creates one if there are none -- creating a fresh session on every stale id would quietly
  // abandon a transcript that is still there.
  async function recoverSession(reason) {
    let list = { sessions: [] };
    try {
      list = await api("/api/sessions");
    } catch (err) {
      addNotice("could not reach the Myriaxon server: " + err.message, "error");
      return;
    }
    const candidate = (list.sessions || []).find((s) => s.id !== state.session);
    if (candidate) {
      addNotice(`${reason} — switched to ${candidate.title || candidate.id}`, "warning");
      await attach(candidate.id, { quiet: true });
      return;
    }
    addNotice(reason + " — started a new one", "warning");
    await newSession();
  }

  // ---------- transparency: the live feed and the dial ----------
  //
  // A SECOND EventSource, separate from the session stream below, because the two answer different questions.
  // The session stream carries one conversation; this carries what the MACHINE is doing -- files read and
  // written, commands run, gates refused, loci coordinating -- including the work of loci that belong to no
  // session at all. Folding them together would leave a locus run with no session open nowhere to appear.
  //
  // The level arrives FIRST and again whenever the dial moves, so the client always knows which layers are
  // being withheld. Without that a quiet feed and a low dial look identical, and a reader concludes nothing is
  // happening when the truth is that nothing is being shown.

  const LAYERS = { 1: "pulse", 2: "intent", 3: "actions", 4: "files", 5: "system", 6: "agents", 7: "decisions", 8: "memory" };
  const LAYER_TONE = { 1: "ok", 4: "mem", 5: "warn", 6: "mem", 7: "error", 8: "mem" };

  function fmtClock(seconds) {
    const d = new Date((seconds || 0) * 1000);
    const pad = (n) => String(n).padStart(2, "0");
    return pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds());
  }

  function transparencyRow(event) {
    const li = document.createElement("li");
    const who = document.createElement("span");
    who.className = "tw";
    // The locus if there is one, else the layer: a file write from a locus is that locus's work, while a
    // decision with no locus is the harness's own.
    who.textContent = event.locus || LAYERS[event.layer] || ("L" + event.layer);
    const when = document.createElement("span");
    when.className = "ts " + (LAYER_TONE[event.layer] || "");
    when.textContent = fmtClock(event.at);
    const what = document.createElement("span");
    what.className = "tm";
    what.textContent = event.summary || event.kind || "";
    // Untrusted text stays TEXT. A tool argument or a file body came from a model or from disk, and a feed that
    // rendered it as markup would let a file's contents act on the page reading it.
    if (event.trusted === false) {
      what.title = "untrusted: from a model or a file";
      what.classList.add("untrusted");
    }
    li.append(who, when, what);
    return li;
  }

  function appendTransparency(event) {
    const list = $("mc-trace");
    if (!list) return;
    list.prepend(transparencyRow(event));
    while (list.children.length > 200) list.removeChild(list.lastChild);
  }

  function wireTransparency() {
    if (state.transparencySource) return;
    const es = new EventSource("/api/transparency/stream");
    state.transparencySource = es;
    es.onmessage = (ev) => {
      let payload; try { payload = JSON.parse(ev.data); } catch { return; }
      if (payload.type === "dial") { renderTransparencyDial(payload); return; }
      appendTransparency(payload);
    };
    // No onerror recovery: EventSource reconnects on its own, and this stream is informational. Touching
    // `#conn` here would make the session status report the wrong thing.
  }

  function renderTransparencyDial(info) {
    state.transparency = info;
    const host = $("trans-dial");
    if (!host) return;
    const max = info.max == null ? 8 : info.max;
    const level = info.level == null ? 0 : info.level;
    host.innerHTML = "";

    const head = document.createElement("div");
    head.className = "transhead";
    head.innerHTML = "<b>" + (info.name || "silent") + "</b> <span class='tm'>level " + level +
      " of " + max + "</span>";
    host.append(head);

    const range = document.createElement("input");
    range.type = "range";
    range.min = "0";
    range.max = String(max);
    range.step = "1";
    range.value = String(level);
    range.id = "trans-range";
    // `input` updates the label as it moves; `change` sends the request, so dragging does not send one PUT per
    // pixel.
    range.oninput = () => {
      const shown = (info.layers || []).find((l) => l.level === Number(range.value));
      if (shown) {
        head.innerHTML = "<b>" + shown.name + "</b> <span class='tm'>" + shown.description + "</span>";
      }
    };
    range.onchange = async () => {
      try {
        const res = await fetch("/api/transparency", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ level: Number(range.value) }),
        });
        renderTransparencyDial(await res.json());
      } catch (err) { /* the label shows the intent; the next load reconciles */ }
    };
    host.append(range);

    const list = document.createElement("div");
    list.className = "translayers";
    (info.layers || []).forEach((layer) => {
      if (!layer.level) return;
      const row = document.createElement("div");
      row.className = "translayer" + (layer.level <= level ? " on" : "");
      row.innerHTML = "<span class='tln'>" + layer.level + "</span><span class='tlb'>" + layer.name +
        "</span><span class='tld tm'>" + layer.description + "</span>";
      list.append(row);
    });
    host.append(list);

    const counts = info.counts || {};
    const seen = Object.keys(counts).filter((k) => counts[k])
      .sort((a, b) => Number(a) - Number(b))
      .map((k) => (LAYERS[k] || k) + " " + counts[k]).join(" · ");
    const foot = document.createElement("div");
    foot.className = "tm transfoot";
    foot.textContent = (info.buffered || 0) + " buffered" + (seen ? " · " + seen : "");
    host.append(foot);
  }

  async function loadTransparency() {
    try {
      const info = await api("/api/transparency");
      renderTransparencyDial(info);
      const list = $("mc-trace");
      const feed = (info.feed || []).slice().reverse();
      if (list && feed.length) {
        list.innerHTML = "";
        feed.forEach(appendTransparency);
      }
    } catch (err) { /* the panel is optional; the rest of the view must still render */ }
  }

  // ---------- SSE ----------
  function connect() {
    if (state.source) { state.source.close(); state.source = null; }
    if (!state.session) return;
    const es = new EventSource("/api/events?session=" + encodeURIComponent(state.session));
    state.source = es;
    es.onopen = () => { $("conn").textContent = "connected"; };
    es.onerror = () => {
      $("conn").textContent = "reconnecting…";
      // A closed stream on a session the server no longer knows is not a network blip: retrying
      // forever would leave a dead composer and a "reconnecting…" label that never resolves. Ask the
      // server which sessions exist and move to one, once.
      //
      // Gated on a timestamp, NOT on `es.readyState === CLOSED`. An EventSource that is retrying sits
      // in CONNECTING, not CLOSED -- CLOSED only happens after `close()` or a fatal response -- so the
      // old guard meant this recovery almost never ran: a deleted session left the page saying
      // "reconnecting…" forever. The throttle is what keeps a genuinely flaky network from asking on
      // every retry, which is what the flag was really for.
      const now = Date.now();
      if (state.session && !state.recovering && now - (state.checkedAt || 0) > 5000) {
        state.checkedAt = now;
        state.recovering = true;
        setTimeout(async () => {
          try {
            const list = await api("/api/sessions");
            if (!(list.sessions || []).some((s) => s.id === state.session)) {
              await recoverSession("that session no longer exists");
            }
          } catch (err) {
            // The server itself is unreachable; the ordinary reconnect path handles that.
          } finally {
            state.recovering = false;
          }
        }, 800);
      }
    };
    es.onmessage = (ev) => {
      let e; try { e = JSON.parse(ev.data); } catch { return; }
      handle(e);
    };
  }

  // The status line. Every figure is computed server-side and arrives in `usage`; this only formats
  // it. A turn is described by what it consumed, how long it took, how fast it streamed and how much
  // of the prompt came from cache, because those are the numbers that answer "is this session healthy
  // and is it economical" -- a token total alone answers neither.
  //
  // Rendered as labelled stat cells rather than a dotted sentence. The previous version joined
  // "3.7s · 7 tok/s · 4.9k tok · 1 req" with separators, which left the reader to work out which
  // number was which; a small caps key over a mono value says it outright and lines the digits up in
  // columns so they can be compared down the row.
  function statCell(key, value, tone) {
    const cell = document.createElement("div");
    cell.className = "stat";
    const k = document.createElement("span");
    k.className = "k";
    k.textContent = key;
    const v = document.createElement("span");
    v.className = "v" + (tone ? " " + tone : "");
    v.textContent = value;
    cell.append(k, v);
    return cell;
  }

  function formatTokens(n) {
    const value = Number(n || 0);
    if (value >= 1_000_000) return (value / 1_000_000).toFixed(value < 10_000_000 ? 2 : 1) + "M";
    if (value >= 1_000) return (value / 1_000).toFixed(value < 10_000 ? 1 : 0) + "k";
    return String(value);
  }

  function renderTurnInfo(usage, seconds) {
    const host = $("turninfo");
    host.innerHTML = "";
    const cells = [];

    if (usage.steps) {
      cells.push(statCell("Steps", String(usage.steps)));
    }
    if (seconds) {
      cells.push(statCell("Took", `${Number(seconds).toFixed(seconds < 10 ? 1 : 0)}s`));
      const out = Number(usage.output_tokens || 0);
      if (out > 0 && seconds > 0.5) {
        cells.push(statCell("Rate", `${Math.round(out / seconds)} tok/s`));
      }
    }
    if (usage.request_count) {
      cells.push(statCell(usage.request_count === 1 ? "Request" : "Requests",
                          String(usage.request_count)));
    }
    const total = Number(usage.total_tokens || 0);
    if (total) {
      cells.push(statCell("Tokens", formatTokens(total)));
    }
    if (usage.cache_read_tokens) {
      const rate = Number(usage.cache_hit_rate || 0);
      // Thresholds are stated here rather than left to judgement: above 80% of the prompt is being
      // served from cache, which is the difference between a cheap long session and an expensive
      // one. Below 40% the cache is barely helping and the session is worth a look.
      cells.push(statCell("Cache hit", `${(rate * 100).toFixed(rate >= 0.995 ? 1 : 0)}%`,
                          rate >= 0.8 ? "good" : (rate < 0.4 ? "warn" : "")));
    }

    cells.forEach((cell) => host.appendChild(cell));
    // The full figures stay available on hover: the cells abbreviate to keep the bar one line, and
    // an abbreviation with no way back to the exact number is a small lie of omission.
    host.title = [
      `turns: ${usage.turn_count || 0}`,
      `requests: ${usage.request_count || 0}`,
      `input: ${(usage.input_tokens || 0).toLocaleString()} tok`,
      `output: ${(usage.output_tokens || 0).toLocaleString()} tok`,
      `cache read: ${(usage.cache_read_tokens || 0).toLocaleString()} tok`,
      `cache write: ${(usage.cache_write_tokens || 0).toLocaleString()} tok`,
      `steps: ${usage.steps || 0}`,
    ].join("\n");
  }

  function handle(e) {
    switch (e.type) {      case "turn_start":
        state.streaming = true; state.assistantEl = null; state.thinkEl = null;
        setBusy(true);
        addMessage("user", e.text);
        showBuffering();
        break;
      case "status":
        $("provider").textContent = e.text || "";
        break;
      case "answer_delta":
        // Cumulative answer text from the model, re-rendered on every delta. Rendered as markdown so
        // bold, lists and tables appear correctly *while* streaming.
        // The first delta replaces the buffering indicator; there is exactly ONE assistant bubble
        // per turn, so the answer cannot appear twice.
        clearBuffering();
        streamAnswer(e.text || "");
        break;
      case "notice":
        if (e.severity === "muted") addNotice(e.text, "normal");
        else addNotice(e.text, e.severity);
        break;
      case "thinking":
        clearBuffering();
        addThinking(e.text || "");
        break;
      case "answer":
        // Full answer sent once by the server if the stream produced no deltas at all (a provider
        // that does not stream). Reusing the same bubble prevents a duplicate.
        clearBuffering();
        streamAnswer(e.text || "");
        break;
      case "tool_call":
        clearBuffering();
        addTool(e.tool, e.args, e.is_error, e.result, e.duration_ms);
        break;
      case "command":
        addNotice(e.text, "muted");
        break;
      case "error":
        setLoci("sorry");
        clearBuffering();
        // `exc_type` carries the exception class. The event's own `kind` is the event name
        // ("error"), so the class cannot live there -- passing it as `kind` to the publisher raised
        // a TypeError and the event never arrived at all.
        addNotice((e.exc_type ? e.exc_type + ": " : "") + (e.message || "error"), "error");
        break;
      case "turn_end":
        setLoci((e.trajectory && e.trajectory.length) ? "cheering" : "idle");
        clearBuffering();
        if (e.trajectory) { state.traj = e.trajectory.map((t) => ({ tool: t.tool, args: t.args, is_error: t.is_error, result: t.result, duration_ms: t.duration_ms })); renderTrajectory(); }
        if (e.usage) renderTurnInfo(e.usage, e.seconds);
        if (e.session) syncSession(e.session);
        state.streaming = false; state.thinkEl = null; state.assistantEl = null; setBusy(false); loadSessions();
        break;
      case "title":
        loadSessions();
        break;
      case "end":
        $("conn").textContent = "stream closed";
        break;
    }
  }

  // Streaming answer: one assistant bubble, re-rendered in place as tokens arrive.
  function streamAnswer(text) {
    if (!state.assistantEl) state.assistantEl = addMessage("assistant", "");
    state.assistantEl.innerHTML = md(text);
    scroll();
  }

  // Reflect a session's provider/model/mode back into the controls so a switch sticks visibly.
  function syncSession(session) {
    if (!session) return;
    if (session.mode) $("mode").value = session.mode;
    if (session.provider) $("provider-sel").value = session.provider;
    if (session.model) setModelOptions(session.model);
    $("provider").textContent = `${session.provider}:${session.model}`;
  }

  function setBusy(busy) {
    $("send").disabled = busy;
    $("send").textContent = busy ? "…" : "Send";
    // The stop button replaces the disabled send button while a turn runs. It is `hidden` rather
    // than disabled so it takes no space when there is nothing to stop.
    $("stop").hidden = !busy;
  }

  async function cancelTurn() {
    if (!state.session) return;
    try {
      await post("/api/cancel", { session: state.session });
      addNotice("stopping…", "warning");
      // The turn ends on its own once the agent's stream loop notices, and `turn_end` clears the
      // busy state. Re-enabling the composer here would let a second turn start over the top of one
      // that is still unwinding.
    } catch (err) {
      addNotice("could not stop: " + err.message, "error");
    }
  }

  // ---------- composer ----------
  const prompt = $("prompt");
  function autosize() { prompt.style.height = "auto"; prompt.style.height = Math.min(prompt.scrollHeight, 200) + "px"; }
  prompt.addEventListener("input", autosize);

  // ---------- slash-command suggestions ----------
  // The terminal has offered completions from the start; the browser only had a placeholder telling
  // you to type "/", which is how a real command came back as "unknown command /loci" with nothing
  // to suggest otherwise. This renders the same catalogue -- availability included, because a menu
  // that hides the terminal-only commands is one where the user keeps trying to remember them.
  const suggest = { items: [], index: 0, open: false, clicking: false };

  function suggestSource() {
    return (state.config && state.config.commands) || [];
  }

  function suggestRender() {
    const box = $("suggest");
    if (!suggest.open || !suggest.items.length) {
      box.classList.remove("on");
      box.innerHTML = "";
      return;
    }
    // The header says the rows are clickable. They always accepted a click, but nothing said so and
    // nothing looked like a button -- so a list of commands that could be inserted with one click
    // read as a read-only hint, and the only way anyone found out was by trying.
    box.innerHTML = `<div class="shead">commands — click one to insert it, or type to filter · `
      + `↑↓ then Tab</div>`
      + suggest.items.map((c, i) => `
        <div class="sitem${i === suggest.index ? " sel" : ""}${c.available ? "" : " na"}"
             role="option" aria-selected="${i === suggest.index}" data-i="${i}"
             title="${c.available ? "Insert " + esc(c.slash) : esc(c.description)}">
          <span class="scmd">${esc(c.slash)}</span>
          <span class="sdesc">${esc(c.description)}</span>
          <span class="sgo" aria-hidden="true">↵</span>
        </div>`).join("");
    box.classList.add("on");
    box.querySelectorAll("[data-i]").forEach((el) => {
      // `mousedown`, not `click` and not blur-timing. A suggestion row is a `<div>` and therefore not
      // focusable, so clicking one blurs the composer while `document.activeElement` becomes the body
      // -- an "is focus still inside the list?" guard can never be true, and the deferred close then
      // removes the row before the click reaches it. mousedown fires BEFORE blur, so setting the flag
      // here is what actually keeps the list alive long enough to be clicked.
      el.onmousedown = (ev) => {
        ev.preventDefault();          // keeps focus in the composer, so there is no blur at all
        suggest.clicking = true;
        suggestAccept(Number(el.dataset.i));
      };
      el.onclick = (ev) => { ev.preventDefault(); };
      el.onmouseenter = () => { suggest.index = Number(el.dataset.i); suggestRender(); };
    });
  }

  function suggestUpdate() {
    const text = prompt.value;
    // Only at the very start of the input, and only for the first word: commands never appear
    // later in a sentence, so suggesting there would be noise.
    if (!text.startsWith("/") || text.includes("\n") || text.slice(1).includes(" ")) {
      suggest.open = false;
      suggestRender();
      return;
    }
    const typed = text.slice(1).toLowerCase();
    const all = suggestSource();
    const matches = all.filter((c) => c.name.toLowerCase().startsWith(typed));
    // Exact match first, then available ones: pressing Enter on "/loci" should not be beaten by
    // "/dotsomething" that happens to sort earlier.
    matches.sort((a, b) => {
      const aExact = a.name.toLowerCase() === typed ? 0 : 1;
      const bExact = b.name.toLowerCase() === typed ? 0 : 1;
      if (aExact !== bExact) return aExact - bExact;
      if (a.available !== b.available) return a.available ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    suggest.items = matches.slice(0, 12);
    suggest.index = 0;
    suggest.open = suggest.items.length > 0;
    suggestRender();
  }

  function suggestAccept(index) {
    const chosen = suggest.items[index === undefined ? suggest.index : index];
    if (!chosen) return;
    // Trailing space, because every one of these takes an argument or a subcommand, and a
    // completion you then have to add a space to has wasted the keystroke it saved.
    prompt.value = chosen.slash + " ";
    suggestUpdate();
    prompt.focus();
    autosize();
  }

  function suggestClose() { suggest.open = false; suggestRender(); }

  prompt.addEventListener("input", suggestUpdate);
  // Shown on focus when the box is empty, so the commands are discoverable without already knowing
  // to type a slash -- which was the whole job the placeholder was failing to do.
  prompt.addEventListener("focus", () => {
    if (!prompt.value) {
      prompt.value = "/";
      suggestUpdate();
      prompt.setSelectionRange(1, 1);
    } else {
      suggestUpdate();
    }
  });
  prompt.addEventListener("blur", () => {
    // Deferred, because the click's own handlers fire around the blur. The flag is what makes a click
    // on a row reliable: leaving the composer by clicking a suggestion must not close the list before
    // the click lands on it. (The row's own `mousedown` calls `preventDefault`, so in practice there
    // is no blur at all -- this is the belt to that pair of braces.)
    setTimeout(() => {
      if (suggest.clicking) { suggest.clicking = false; return; }
      suggestClose();
    }, 140);
  });
  prompt.addEventListener("keydown", (ev) => {
    if (!suggest.open) {
      if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); send(); }
      return;
    }
    if (ev.key === "ArrowDown") {
      ev.preventDefault();
      suggest.index = (suggest.index + 1) % suggest.items.length;
      suggestRender();
      return;
    }
    if (ev.key === "ArrowUp") {
      ev.preventDefault();
      suggest.index = (suggest.index - 1 + suggest.items.length) % suggest.items.length;
      suggestRender();
      return;
    }
    if (ev.key === "Tab") { ev.preventDefault(); suggestAccept(); return; }
    if (ev.key === "Enter" && !ev.shiftKey) {
      ev.preventDefault();
      // Enter takes the highlighted command when that command is an exact match for what was typed
      // -- so "/loci" followed by Enter runs the command, while "/do" followed by Enter completes
      // to /loci rather than sending a half-typed command.
      const typed = prompt.value.slice(1).toLowerCase();
      const best = suggest.items[suggest.index];
      if (best && best.name.toLowerCase() === typed) { suggestClose(); send(); return; }
      suggestAccept();
      return;
    }
    if (ev.key === "Escape") { ev.preventDefault(); suggestClose(); }
  });
  document.addEventListener("click", (ev) => {
    if (!ev.target.closest || !ev.target.closest("#inputrow")) suggestClose();
  });

  async function send() {
  setLoci("thinking");

    const text = prompt.value.trim();
    if (!text || state.streaming) return;
    suggestClose();
    if (!state.session) await newSession();
    prompt.value = ""; autosize();
    const attachments = state.attachments.map((a) => a.path);
    state.attachments = []; renderChips();
    try {
      await post("/api/chat", { session: state.session, message: text, attachments, mode: $("mode").value, model: $("model").value });
    } catch (err) {
      addNotice(err.message, "error");
      // A POST that fails never produces a turn_end event, so the switch that handles turn events is never
      // reached and the header would sit on "thinking" for ever. The failure has to be drawn here.
      setLoci("sorry");
      setBusy(false); state.streaming = false;
    }
  }
  $("send").onclick = send;
  $("stop").onclick = cancelTurn;

  // ---------- attachments ----------
  function renderChips() {
    const box = $("chips");
    box.innerHTML = "";
    state.attachments.forEach((a, i) => {
      const el = document.createElement("div");
      el.className = "chip";
      const thumb = a.is_image ? `<img src="/api/download?path=${encodeURIComponent(a.path)}" alt="">` : "📄";
      el.innerHTML = `${thumb}<span>${esc(a.name)}</span><button title="remove">×</button>`;
      el.querySelector("button").onclick = () => { state.attachments.splice(i, 1); renderChips(); };
      box.appendChild(el);
    });
  }

  async function uploadFiles(files) {
    for (const file of files) {
      try {
        const res = await fetch("/api/upload", { method: "POST", headers: { "X-Filename": encodeURIComponent(file.name) }, body: file });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "upload failed");
        state.attachments.push(data);
      } catch (err) { addNotice("upload failed: " + err.message, "error"); }
    }
    renderChips();
  }

  $("attach").onclick = () => $("file").click();
  $("file").onchange = (ev) => { uploadFiles([...ev.target.files]); ev.target.value = ""; };
  const row = $("inputrow");
  ["dragenter", "dragover"].forEach((t) => document.addEventListener(t, (ev) => { ev.preventDefault(); row.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((t) => document.addEventListener(t, (ev) => { ev.preventDefault(); if (t === "drop" || ev.target === document) row.classList.remove("drag"); }));
  document.addEventListener("drop", (ev) => { if (ev.dataTransfer && ev.dataTransfer.files.length) uploadFiles([...ev.dataTransfer.files]); });
  document.addEventListener("paste", (ev) => {
    const files = [...(ev.clipboardData ? ev.clipboardData.files : [])];
    if (files.length) { ev.preventDefault(); uploadFiles(files); }
  });

  // ---------- tabs / mode / provider / model ----------
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.onclick = () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
      const chat = tab.dataset.pane === "chat";
      $("chat").style.display = chat ? "block" : "none";
      $("trajectory").style.display = chat ? "none" : "block";
    };
  });

  $("mode").onchange = async () => {
    if (!state.session) return;
    try { await post("/api/mode", { session: state.session, mode: $("mode").value }); }
    catch (err) { addNotice("could not set mode: " + err.message, "error"); }
  };

  // Switching vendor must go through the server so the endpoint, credential and model are remapped
  // together -- changing only the name would leave the previous endpoint in place.
  $("provider-sel").onchange = async () => {
    if (!state.session) return;
    const provider = $("provider-sel").value;
    try {
      const out = await post("/api/chat", { session: state.session, message: "/provider " + provider });
      const modelMatch = (out.output || "").match(/model\s+(\S+)/);
      if (modelMatch) setModelOptions(modelMatch[1]);
      $("provider").textContent = provider + ":" + $("model").value;
      // The model list belongs to the vendor, so refresh it after a switch.
      const cfg = await api("/api/config");
      state.config.models = cfg.models;
      state.config.custom_endpoints = cfg.custom_endpoints;
      state.config.providers = cfg.providers;
      setModelOptions($("model").value);
      populateVendors();
      // The local-model panel belongs to the vendor that was just chosen, so it is re-evaluated on
      // every switch: hidden at every other vendor, and populated when this switch was to ollama.
      // Without this the panel kept whatever it showed before -- visible at netra, or missing at
      // ollama until the page was reloaded.
      await loadOllama(provider === "ollama");
    } catch (err) { addNotice("could not switch vendor: " + err.message, "error"); }
  };

  $("model").onchange = async () => {
    if (!state.session) return;
    try {
      await post("/api/model", { session: state.session, model: $("model").value });
      $("provider").textContent = $("provider-sel").value + ":" + $("model").value;
    }
    catch (err) { addNotice("could not set model: " + err.message, "error"); }
  };

  // ---------- local models (Ollama) ---------------------------------------------------------
  // The panel belongs to ONE vendor. It used to appear whenever Ollama merely answered on this
  // machine, which is a different question from "is Ollama the vendor this session is using": a
  // session on Netra showed a four-model local list beside a vendor dropdown that said netra, and
  // the card stretched the whole status strip into a tall box. Local models are only selectable
  // when Ollama is the vendor, so that is the condition under which the list is shown.
  function providerChoice() {
    const sel = $("provider-sel");
    if (sel && sel.value) return sel.value;
    if (state.session && state.session.provider) return state.session.provider;
    return (state.config && state.config.provider) || "";
  }

  function fmtCtx(n) {
    if (!n) return "unknown";
    if (n >= 1000) return (n / 1000) + "K";
    return String(n);
  }

  // One request, full detail. An earlier version probed cheaply first (`?quick=1`, no per-model
  // request) and then re-fetched in full -- but a screenshot showed why that is worse than it sounds:
  // the cheap probe reports `context_declared: 0`, so the row rendered its model name and size with
  // the one number the panel exists to show missing. The detailed probe costs one request per model
  // and there are three models; a brief "scanning…" is not worth hiding the answer behind.
  async function loadOllama(showScanning, providerOverride) {
    const panel = $("ollamapanel");
    // `providerOverride` exists for `switchToLocal`, which populates the panel immediately after
    // switching the session -- at which point the dropdown has not been set yet, so reading it
    // would answer "not ollama" and hide the list that was just built.
    const wantOllama = (providerOverride || providerChoice()) === "ollama";
    // Asked before any request: at another vendor there is nothing this panel could offer, so it
    // must not even be probed for -- the point is that it is absent, not that it is empty.
    if (!wantOllama) { panel.hidden = true; return; }
    try {
      if (showScanning) $("ollamastate").textContent = "scanning…";
      const data = await api("/api/ollama");
      // Re-checked after the await. The vendor can be switched while this request is in flight, and
      // a stale response must not put the panel back on screen for a session that has moved away.
      if ((providerOverride || providerChoice()) !== "ollama") { panel.hidden = true; return; }
      if (!data.reachable) { panel.hidden = true; return; }
      panel.hidden = false;
      $("ollamastate").textContent = data.models.length
        ? data.models.length + " on " + data.base_url.replace(/^https?:\/\//, "")
        : "running, no models pulled";

      const list = $("ollamalist");
      list.textContent = "";
      // The threshold comes from the server so the browser cannot disagree with the CLI about when a
      // window is too small.
      const minimumForAgent = Number(data.minimum_for_agent || 0);
      if (!data.models.length) {
        const empty = document.createElement("div");
        empty.className = "oempty";
        empty.textContent = "Nothing pulled yet. Get one with:  ollama pull qwen2.5-coder:7b";
        list.append(empty);
      }
      for (const m of data.models) {
        const row = document.createElement("button");
        row.type = "button";
        row.className = "orow";
        row.setAttribute("aria-current", String(!!data.active && m.name === data.active_model));
        // Clicking switches the session to this model. Without this the panel would be a read-only
        // report, and the user would still have to type the model name by hand somewhere else.
        row.onclick = () => switchToLocal(m.name);

        const name = document.createElement("span");
        name.className = "oname";
        name.textContent = m.name;
        name.title = m.name;

        const meta = document.createElement("span");
        meta.className = "ometa";
        // Declared is struck through when Ollama runs the model with less (it gives every model 4,096 unless
        // the model's own settings say more), so the difference is visible at a glance rather than explained
        // in a sentence the reader has to decode. Context is the only number emphasised; the rest of the row
        // stays quiet so the column scans.
        const capped = m.context_declared && m.context_usable < m.context_declared;
        const ctx = document.createElement("span");
        ctx.className = "ctx";
        if (capped) {
          const s = document.createElement("s");
          s.textContent = fmtCtx(m.context_declared);
          ctx.append(s, document.createTextNode(" "));
        }
        const b = document.createElement("b");
        b.textContent = fmtCtx(m.context_usable);
        ctx.append(b);
        ctx.title = capped
          ? "The model supports " + m.context_declared.toLocaleString() + " tokens, but Ollama runs it with " +
            m.context_usable.toLocaleString() + ". Run  myriaxon ollama --create  for a copy with the full window."
          : "Context window " + (m.context_usable || 0).toLocaleString() + " tokens";
        meta.append(ctx);

        // Capabilities collapsed into the row's tooltip rather than a chip per ability. Three chips
        // per row was most of the panel's height, and the only ability that changes behaviour is the
        // absence of tool calling, which gets its own marker below.
        const notes = [];
        if (m.parameter_size) notes.push(m.parameter_size);
        if (m.quantisation) notes.push(m.quantisation);
        if (m.capabilities && m.capabilities.length) {
          notes.push(m.capabilities.filter((c) => c !== "completion").join(", "));
        }
        if (capped) {
          notes.push("runs with " + m.context_usable.toLocaleString() + " of the " +
                     m.context_declared.toLocaleString() + " tokens it supports; myriaxon ollama --create " +
                     "makes a copy with the full window");
        }
        if (m.loaded) notes.push("loaded in memory now");
        const info = document.createElement("span");
        info.className = "ometa";
        info.textContent = m.parameter_size || "";
        if (notes.length) info.title = m.name + "\n" + notes.join("\n");

        // `name` must be appended. An earlier revision created it, styled it, and never attached it,
        // so every row rendered as a bare size column with no model to click -- the one field the
        // panel exists to show.
        row.append(name, meta, info);
        if (!m.supports_tools) {
          const warn = document.createElement("span");
          warn.className = "owarn";
          warn.textContent = "⚠";
          warn.title = "No tool calling: this model cannot call functions, so it cannot drive the " +
                       "agent. It answers in prose instead.";
          row.append(warn);
        }
        // A window too small for the agent's own prompt is marked HERE, not left for the user to
        // notice from the numbers. Measured on a 4,096-token model: Myriaxon's system prompt alone is
        // about 4,700 tokens, so the first real turn refuses with "Context window is 216% full" --
        // correct, but only if the user understands that the model was never usable rather than that
        // they did something wrong. The panel is where that is knowable before the turn.
        const tooSmall = minimumForAgent && m.context_usable && m.context_usable < minimumForAgent;
        if (tooSmall) {
          const small = document.createElement("span");
          small.className = "owarn";
          small.textContent = "small window";
          small.title = "Ollama runs this model with " + m.context_usable.toLocaleString() +
                        " tokens; the agent needs at least " + minimumForAgent.toLocaleString() +
                        ". It answers short questions but will refuse a real task. Fix it with:  " +
                        "myriaxon ollama --create";
          row.append(small);
        }
        list.append(row);
      }

      $("ollamanote").textContent = data.models.length
        ? "Click a model to use it. Runs on this machine: no API key, no usage cost."
        : "";
    } catch (err) {
      panel.hidden = true;   // absence is not an error worth showing
    }
  }

  // A running locus is stopped HERE, from its own room. The main composer's Stop button cancels the
  // *Myriaxon* session, and a locus runs in its OWN session -- so "stop" there could not reach it,
  // which is exactly the complaint: a locus kept working with no way to call it off. The button only
  // appears while the locus is working, so it never suggests it can stop something that is idle.
  async function stopLocus() {
    const locus = locusChat.locus;
    if (!locus || !locusChat.sessionId) {
      locusStatus("nothing to stop: this locus has no session yet", "warn");
      return;
    }
    try {
      await post("/api/cancel", { session: locusChat.sessionId });
      locusStatus(`asked ${locus.name} to stop — it ends at the next step boundary`, "ok");
    } catch (err) {
      locusStatus("could not stop: " + err.message, "error");
      return;
    }
    // Polled rather than assumed: cancellation is cooperative and lands between streamed chunks, so
    // the honest thing is to keep showing state until the turn actually ends.
    let waits = 0;
    const tick = setInterval(async () => {
      waits += 1;
      await loadLocusTranscript();
      if (!locusChat.locus || !locusChat.locus.running || waits > 20) {
        clearInterval(tick);
        if (locusChat.locus && !locusChat.locus.running) locusStatus(`${locus.name} stopped`, "ok");
      }
    }, 1000);
  }

  async function switchToLocal(name) {
    if (!state.session) { addNotice("open a session first", "error"); return; }
    try {
      await post("/api/chat", { session: state.session, message: "/provider ollama" });
      await post("/api/model", { session: state.session, model: name });
      $("provider-sel").value = "ollama";
      setModelOptions(name);
      $("provider").textContent = "ollama:" + name;
      addNotice("now using local model " + name, "info");
      await loadOllama(true, "ollama");
    } catch (err) {
      addNotice("could not switch to " + name + ": " + err.message, "error");
    }
  }

  $("ollamarefresh").onclick = () => loadOllama(true);
  // Only probes when the session is already on ollama. At any other vendor the panel stays hidden
  // and no request is made -- a local-model scan on every page load is work the user never asked
  // for and a card they never wanted.
  loadOllama(providerChoice() === "ollama");

  function setModelOptions(model) {
    const select = $("model");
    if (![...select.options].some((o) => o.value === model)) {
      select.insertAdjacentHTML("afterbegin", `<option value="${esc(model)}">${esc(model)}</option>`);
    }
    select.value = model;
  }

  $("newbtn").onclick = newSession;

  // ---------- theme ----------
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    $("themebtn").textContent = theme === "dark" ? "☾ dark" : "☀ light";
    try { localStorage.setItem("myriaxon-theme", theme); } catch (e) { /* private mode */ }
  }
  $("themebtn").onclick = () => {
    const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    applyTheme(next);
    // Persist to both places: localStorage so the next paint is instant, and the server so the
    // choice survives a different browser or a cleared cache.
    post("/api/settings", { theme: next })
      .then((out) => { if (state.config) state.config.settings = out.settings; })
      .catch(() => {});
  };

  // ---------- project picker ----------
  function openProjectModal() {
    $("projpath").value = state.config ? state.config.workspace : "";
    renderRecents();
    $("projmodal").classList.add("open");
    $("projpath").focus();
  }
  function closeProjectModal() { $("projmodal").classList.remove("open"); }

  function renderRecents() {
    const box = $("projrecents");
    const recents = (state.config && state.config.recent_workspaces) || [];
    box.innerHTML = recents.length ? `<div class="sect" style="padding:0 0 4px">recent</div>` : "";
    recents.forEach((path) => {
      const el = document.createElement("div");
      el.className = "recent";
      el.textContent = path;
      el.onclick = () => { $("projpath").value = path; };
      box.appendChild(el);
    });
  }

  async function openProject() {
    const path = $("projpath").value.trim();
    if (!path) return;
    try {
      const out = await post("/api/workspace", { path });
      state.config = out.config;
      refreshBadges();
      $("ws").textContent = out.config.workspace;
      closeProjectModal();
      // Sessions belong to a project (the agent's filesystem root), so the list is re-read.
      state.session = null; state.traj = []; renderTrajectory();
      $("chat").innerHTML = `<div class="hint" id="hint">Now working in <code>${esc(out.config.workspace)}</code>. Send a message to begin.</div>`;
      await loadSessions();
      await newSession();
      addNotice("opened project " + out.config.workspace, "success");
    } catch (err) { addNotice("could not open project: " + err.message, "error"); }
  }

  $("projbtn").onclick = openProjectModal;
  $("projcancel").onclick = closeProjectModal;
  $("projopen").onclick = openProject;
  $("projpath").addEventListener("keydown", (ev) => { if (ev.key === "Enter") openProject(); });
  $("projmodal").addEventListener("click", (ev) => { if (ev.target === $("projmodal")) closeProjectModal(); });

  // ---------- settings ----------
  // The form is generated from the schema the server sends, so adding a setting on the server side
  // does not require touching this file.
  // ---------- Vertex context cache ----------
// Every number shown here comes from Google, read on each open rather than remembered locally. A cache
// is a billing resource: a panel that displayed a stale local copy would report money being spent on
// something that may have been deleted from the console, or hide a cache that is still billing.
//
// The hit rate is the number that decides whether caching is worth keeping. A cache that exists and is
// never hit costs per hour and saves nothing, and it looks identical to a working one unless the misses
// are shown next to the hits -- so both are shown, always.
async function loadVertexCache() {
  const status = $("vcstatus"), list = $("vclist"), summary = $("vcsummary");
  if (!status) return;
  let data;
  try {
    data = await (await fetch("/api/vertex-cache")).json();
  } catch (err) {
    status.textContent = "could not read cache state: " + err.message;
    return;
  }
  const on = !!data.enabled;
  $("vctoggle").textContent = on ? "Disable" : "Enable";
  $("vctoggle").className = on ? "ghost" : "primary";
  $("vcmin").textContent = data.min_tokens || 4096;
  summary.textContent = on ? "on" : "off";

  const live = (data.active || []).length;
  status.innerHTML =
    (on ? "enabled" : "disabled") +
    " · " + live + " live cache" + (live === 1 ? "" : "s") +
    " · hits " + data.hits + " / misses " + data.misses +
    " · hit rate " + ((data.hit_rate || 0) * 100).toFixed(1) + "%" +
    " · " + (data.tokens_served_from_cache || 0).toLocaleString() + " tokens cached" +
    " · ttl " + Math.round((data.ttl_seconds || 0) / 60) + "m" +
    (data.last_error ? "<br><span style='color:var(--warn,#c80)'>" + esc(data.last_error) + "</span>" : "");

  list.innerHTML = "";
  for (const c of (data.active || [])) {
    const row = document.createElement("div");
    row.className = "recent";
    row.innerHTML = "<span>" + esc((c.name || "").split("/").pop()) +
      " · " + (c.tokens || 0).toLocaleString() + " tok · expires in " +
      Math.round(c.expires_in_s || 0) + "s</span>";
    const del = document.createElement("button");
    del.className = "ghost";
    del.textContent = "Delete";
    del.onclick = async () => {
      await act({ action: "delete", name: c.name });
      loadVertexCache();
    };
    row.appendChild(del);
    list.appendChild(row);
  }
}

async function act(body) {
  try {
    const r = await fetch("/api/vertex-cache", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const j = await r.json();
    if (!r.ok || j.error) $("vcstatus").textContent = "error: " + (j.error || r.status);
    return j;
  } catch (err) {
    $("vcstatus").textContent = "error: " + err.message;
    return {};
  }
}

function wireVertexCache() {
  if (!$("vctoggle") || $("vctoggle").dataset.wired) return;
  $("vctoggle").dataset.wired = "1";
  $("vctoggle").onclick = async () => {
    const on = $("vctoggle").textContent.trim() === "Disable";
    await act({ action: on ? "disable" : "enable" });
    loadVertexCache();
  };
  $("vccreate").onclick = async () => {
    // Built server-side from THIS session's system prompt and tools, so the cache is of the text the
    // requests will actually contain. A cache of invented text would never be hit and would still bill.
    $("vcstatus").textContent = "creating…";
    const j = await act({ action: "create", session: state.session, model: $("model").value });
    if (j && j.tokens) $("vcstatus").textContent = "created: " + j.tokens.toLocaleString() + " tokens cached";
    loadVertexCache();
  };
  $("vcpurge").onclick = async () => {
    if (!confirm("Delete every context cache on this project? Caching stops until one is created again.")) return;
    const j = await act({ action: "purge" });
    $("vcstatus").textContent = "deleted " + ((j && j.deleted) || 0) + " cache(s)";
    loadVertexCache();
  };
  loadVertexCache();
}

function renderSettings() {
    const form = $("setform");
    const schema = (state.config && state.config.settings_schema) || {};
    const values = (state.config && state.config.settings) || {};
    form.innerHTML = "";
    Object.entries(schema).forEach(([key, field]) => {
      const row = document.createElement("div");
      row.className = "setrow";
      const value = values[key];
      let control = "";
      if (field.type === "bool") {
        control = `<label class="switch"><input type="checkbox" data-key="${key}"${value ? " checked" : ""}><span class="slider"></span></label>`;
      } else if (field.type === "choice") {
        const options = (field.options || []).map((option) => {
          const label = (field.labels && field.labels[option]) || option || "default";
          return `<option value="${esc(option)}"${option === value ? " selected" : ""}>${esc(label)}</option>`;
        }).join("");
        control = `<select data-key="${key}">${options}</select>`;
      } else if (field.type === "int") {
        control = `<input type="number" data-key="${key}" value="${value}" min="${field.min || 0}">`;
      }
      row.innerHTML = `<div class="info"><div class="lbl">${esc(field.label || key)}</div>
        ${field.help ? `<div class="hint">${esc(field.help)}</div>` : ""}</div>
        <div class="ctl">${control}</div>`;
      form.appendChild(row);
    });

    form.querySelectorAll("[data-key]").forEach((input) => {
      input.addEventListener("change", () => saveSetting(input));
    });
  }

  async function saveSetting(input) {
    const key = input.dataset.key;
    const isBool = input.type === "checkbox";
    const value = isBool ? input.checked : (input.type === "number" ? parseInt(input.value || "0", 10) : input.value);
    try {
      const out = await post("/api/settings", { [key]: value });
      state.config.settings = out.settings;
      // Apply purely visual settings immediately; the server reports which changes rebuilt agents.
      if (key === "theme") applyTheme(out.settings.theme);
      if (key === "density") applyDensity(out.settings.density);
      if ((out.agent_affecting || []).length) {
        addNotice(`settings saved; ${out.rebuilt_sessions} session(s) reloaded (${out.agent_affecting.join(", ")})`, "success");
      } else {
        flashSaved(input);
      }
    } catch (err) { addNotice("could not save setting: " + err.message, "error"); }
  }

  function flashSaved(input) {
    const row = input.closest(".setrow");
    if (!row || row.querySelector(".saved")) return;
    const tag = document.createElement("span");
    tag.className = "saved show";
    tag.textContent = "saved";
    row.querySelector(".info").appendChild(tag);
    setTimeout(() => tag.classList.remove("show"), 1200);
  }

  $("settingsbtn").onclick = () => { setMenu(false); renderSettings(); wireVertexCache(); $("setmodal").classList.add("open"); };
  $("setcancel").onclick = () => $("setmodal").classList.remove("open");
  $("setmodal").addEventListener("click", (ev) => { if (ev.target === $("setmodal")) $("setmodal").classList.remove("open"); });
  $("setreset").onclick = async () => {
    const defaults = { workflow: "single", thinking: false, effort: "", max_tokens: 0, yolo: true,
                       auto_compact: true, theme: "dark", density: "comfortable", show_thinking: true };
    try {
      const out = await post("/api/settings", defaults);
      state.config.settings = out.settings;
      applyTheme(out.settings.theme); applyDensity(out.settings.density);
      renderSettings();
      addNotice("settings reset to defaults", "success");
    } catch (err) { addNotice("could not reset: " + err.message, "error"); }
  };

  function applyDensity(density) {
    document.documentElement.setAttribute("data-density", density || "comfortable");
  }

  // ---------- vendor / endpoint manager ----------
  // Built-in vendors are fixed; anything the user adds becomes a first-class provider: it appears in
  // the dropdown, is switchable mid-conversation, and is usable from /provider.
  const BUILTIN_PROVIDERS = ["gemini", "netra", "deepseek", "openrouter", "anthropic", "openai_compat"];

  function renderVendors() {
    const box = $("vendlist");
    const custom = (state.config && state.config.custom_endpoints) || [];
    const names = (state.config && state.config.providers) || [];
    box.innerHTML = "";
    names.forEach((name) => {
      const entry = custom.find((e) => e.name === name);
      const row = document.createElement("div");
      row.className = "vendrow" + (entry ? "" : " builtin");
      row.innerHTML = `<span class="vname">${esc(name)}</span>
        <span class="vurl">${esc(entry ? entry.base_url : "built-in")}</span>
        ${entry ? '<span class="tag">custom</span>' : ""}
        ${entry ? '<button class="vdel" title="Delete this endpoint">×</button>' : ""}`;
      const del = row.querySelector(".vdel");
      if (del) {
        del.onclick = async () => {
          if (!confirm(`Delete endpoint "${name}"?`)) return;
          try {
            const out = await post("/api/endpoints", { action: "delete", name });
            state.config.custom_endpoints = out.endpoints;
            state.config.providers = BUILTIN_PROVIDERS.concat(out.endpoints.map((e) => e.name));
            renderVendors(); populateVendors();
          } catch (err) { setVendorStatus("delete failed: " + err.message, false); }
        };
      }
      box.appendChild(row);
    });
  }

  function setVendorStatus(text, ok) {
    const el = $("vstatus");
    el.textContent = text;
    el.className = ok ? "ok" : "err";
  }

  function populateVendors() {
    const select = $("provider-sel");
    const names = (state.config && state.config.providers) || [state.config.provider];
    const current = select.value || (state.config && state.config.provider);
    select.innerHTML = names.map((p) => `<option value="${esc(p)}">${esc(p)}</option>`).join("");
    if (names.includes(current)) select.value = current;
  }

  async function fetchModelsFromForm() {
    const name = $("vname").value.trim();
    const base = $("vurl").value.trim();
    if (!base) { setVendorStatus("enter a base URL first", false); return; }
    setVendorStatus("fetching…", true);
    try {
      const out = await post("/api/endpoints/probe", { name, base_url: base, api_key: $("vkey").value.trim() });
      if (!out.ok) { setVendorStatus(out.error || "probe failed", false); return; }
      if (!out.models.length) { setVendorStatus("endpoint answered but listed no models", false); return; }
      $("vmodels").value = out.models.join(", ");
      if (!$("vmodel").value) $("vmodel").value = out.models[0];
      const shown = out.models.slice(0, 3).join(", ");
      setVendorStatus(`found ${out.count} models: ${shown}${out.count > 3 ? ", …" : ""}`, true);
    } catch (err) { setVendorStatus("probe failed: " + err.message, false); }
  }

  async function testEndpointForm() {
    const name = $("vname").value.trim();
    const base = $("vurl").value.trim();
    const model = $("vmodel").value.trim();
    if (!base) { setVendorStatus("enter a base URL first", false); return; }
    if (!model) { setVendorStatus("enter or fetch a model first", false); return; }
    setVendorStatus("sending a test message…", true);
    try {
      const out = await post("/api/endpoints/test", {
        name, base_url: base, api_key: $("vkey").value.trim(), model,
      });
      setVendorStatus(out.ok ? `ok: ${JSON.stringify(out.reply).slice(0, 80)}` : (out.error || "test failed"), out.ok);
    } catch (err) { setVendorStatus("test failed: " + err.message, false); }
  }

  async function saveEndpointForm() {
    const payload = {
      name: $("vname").value.trim().toLowerCase(),
      base_url: $("vurl").value.trim(),
      api_key: $("vkey").value.trim(),
      models: $("vmodels").value,
      model: $("vmodel").value.trim(),
    };
    if (!payload.name) { setVendorStatus("give the endpoint a name", false); return; }
    if (!payload.base_url) { setVendorStatus("enter a base URL", false); return; }
    try {
      const out = await post("/api/endpoints", payload);
      state.config.custom_endpoints = out.endpoints;
      state.config.providers = BUILTIN_PROVIDERS.concat(out.endpoints.map((e) => e.name));
      renderVendors(); populateVendors();
      $("vkey").value = "";
      setVendorStatus(`saved "${payload.name}"`, true);
    } catch (err) { setVendorStatus("save failed: " + err.message, false); }
  }

  $("vendormanage").onclick = () => { renderVendors(); $("vendmodal").classList.add("open"); };
  $("vendclose").onclick = () => $("vendmodal").classList.remove("open");
  $("vendmodal").addEventListener("click", (ev) => { if (ev.target === $("vendmodal")) $("vendmodal").classList.remove("open"); });
  $("vfetch").onclick = fetchModelsFromForm;
  $("vtest").onclick = testEndpointForm;
  $("vsave").onclick = saveEndpointForm;

  // ---------- MCP servers ----------
  // The CLI already has full MCP support (stdio + http + registry search); the only gap was that
  // none of it was reachable without a terminal. These call the same helpers.
  function mcpStatus(text, ok) {
    const el = $("mstatus");
    el.textContent = text;
    el.className = ok ? "ok" : "err";
  }

  // ---------- MCP catalog ----------
  // Every catalog entry is a server whose configuration is already known, so the panel is a list of
  // switches rather than a form. Entries needing a credential show exactly that field; the rest are
  // one click.
  const mcpView = { category: "All", pending: {} };

  function renderCatalog() {
    const mcp = (state.config && state.config.mcp) || {};
    const catalog = mcp.catalog || [];
    const tabs = $("mcptabs");
    const box = $("mcpcatalog");

    const warning = $("mcptransportwarn");
    const transports = mcp.transports || {};
    const anyRemote = transports.streamable_http || transports.sse;
    if (catalog.some((c) => c.transport === "http") && !anyRemote) {
      warning.style.display = "block";
      warning.textContent = "No remote MCP transport is installed, so hosted servers cannot connect " +
        "yet. Run: pip install -e \".[mcp]\"";
    } else {
      warning.style.display = "none";
    }

    const cats = ["All", ...(mcp.categories || [])];
    tabs.innerHTML = "";
    cats.forEach((cat) => {
      const button = document.createElement("button");
      button.className = "tab" + (cat === mcpView.category ? " active" : "");
      button.textContent = cat;
      button.onclick = () => { mcpView.category = cat; renderCatalog(); };
      tabs.appendChild(button);
    });

    box.innerHTML = "";
    const shown = catalog.filter((c) => mcpView.category === "All" || c.category === mcpView.category);
    if (!shown.length) {
      box.innerHTML = `<div class="dim">Nothing in this category.</div>`;
      return;
    }

    shown.forEach((entry) => {
      const row = document.createElement("div");
      row.className = "catrow" + (entry.installed ? " on" : "");

      const main = document.createElement("div");
      main.className = "catmain";
      const title = document.createElement("div");
      title.className = "cattitle";
      const name = document.createElement("span");
      name.textContent = entry.label;
      title.appendChild(name);
      const tag = document.createElement("span");
      tag.className = "cattag";
      tag.textContent = entry.transport === "http" ? "remote" : "local";
      title.appendChild(tag);
      if (entry.fetches_on_first_run) {
        const fetchTag = document.createElement("span");
        fetchTag.className = "cattag";
        fetchTag.textContent = "downloads on first use";
        title.appendChild(fetchTag);
      }
      main.appendChild(title);

      const note = document.createElement("div");
      note.className = "catnote";
      note.textContent = entry.note || "";
      main.appendChild(note);

      // Credential fields, filled in before the switch can be turned on.
      const fields = {};
      (entry.needs || []).forEach((need) => {
        const wrap = document.createElement("div");
        wrap.className = "catfield";
        const label = document.createElement("span");
        label.className = "dim";
        label.style.fontSize = "11px";
        label.textContent = need.label;
        const input = document.createElement("input");
        input.type = need.kind === "token" ? "password" : "text";
        input.placeholder = need.default || "";
        input.value = mcpView.pending[`${entry.key}:${need.key}`] || "";
        input.spellcheck = false;
        input.oninput = () => { mcpView.pending[`${entry.key}:${need.key}`] = input.value; };
        wrap.append(label, input);
        main.appendChild(wrap);
        fields[need.key] = input;
      });

      row.appendChild(main);

      const toggle = document.createElement("button");
      toggle.className = "switch" + (entry.installed ? " on" : "");
      toggle.title = entry.installed ? "Turn off" : "Turn on";
      toggle.setAttribute("aria-label", toggle.title);
      toggle.onclick = () => toggleCatalog(entry, toggle, fields);
      row.appendChild(toggle);

      box.appendChild(row);
    });
  }

  async function toggleCatalog(entry, toggle, fields) {
    if (entry.installed) {
      toggle.disabled = true;
      try {
        const out = await post("/api/mcp", { action: "catalog_disable", key: entry.key });
        state.config.mcp = out;
        renderMcp();
        renderCatalog();
        mcpStatus(`turned off ${entry.label}`, true);
      } catch (err) { mcpStatus("could not turn it off: " + err.message, false); }
      finally { toggle.disabled = false; }
      return;
    }
    const values = {};
    for (const [key, input] of Object.entries(fields || {})) values[key] = input.value.trim();
    toggle.disabled = true;
    try {
      const out = await post("/api/mcp", { action: "catalog_enable", key: entry.key, values });
      state.config.mcp = out;
      renderMcp();
      renderCatalog();
      mcpStatus(`${entry.label} is on — its tools appear on the next message`, true);
    } catch (err) {
      mcpStatus(`${entry.label} needs more: ${err.message}`, false);
    } finally {
      if (toggle.isConnected) toggle.disabled = false;
    }
  }

  function renderMcp() {
    const box = $("mcplist");
    const mcp = (state.config && state.config.mcp) || {};
    const stdio = mcp.stdio_servers || [];
    const url = mcp.url_servers || [];
    box.innerHTML = "";
    if (!stdio.length && !url.length) {
      box.innerHTML = `<div class="dim" style="padding:2px 0 6px">No MCP servers configured.</div>`;
      return;
    }
    const rows = [
      ...url.map((s) => ({ name: s.name, detail: s.url, kind: "http" })),
      ...stdio.map((s) => ({ name: s.name, detail: [s.command, ...(s.args || [])].join(" "), kind: "stdio" })),
    ];
    rows.forEach((row) => {
      const el = document.createElement("div");
      el.className = "vendrow";
      el.innerHTML = `<span class="vname">${esc(row.name)}</span>
        <span class="vurl">${esc(row.detail || "")}</span>
        <span class="tag">${esc(row.kind)}</span>
        <button class="vdel" title="Remove">×</button>`;
      el.querySelector(".vdel").onclick = async () => {
        if (!confirm(`Remove MCP server "${row.name}"?`)) return;
        try {
          const out = await post("/api/mcp", { action: "remove", name: row.name });
          state.config.mcp = out.config;
          renderMcp();
          mcpStatus(`removed ${row.name}; restart is not needed for removal`, true);
        } catch (err) { mcpStatus("remove failed: " + err.message, false); }
      };
      box.appendChild(el);
    });
    if (mcp.config_file) {
      const note = document.createElement("div");
      note.className = "dim";
      note.style.fontSize = "11px";
      note.style.paddingTop = "4px";
      note.textContent = "config: " + mcp.config_file;
      box.appendChild(note);
    }
    // The catalog and the menu badges both depend on which servers are installed, so refreshing them
    // here keeps them consistent however the configuration changed.
    if ($("mcpcatalog")) renderCatalog();
    refreshBadges();
  }

  async function addMcpServer() {
    const kind = $("mkind").value;
    const name = $("mname").value.trim();
    if (!name) { mcpStatus("give the server a name", false); return; }
    const payload = { action: "add", name, kind };
    if (kind === "stdio") {
      const parts = $("mcmd").value.trim().split(/\s+/).filter(Boolean);
      if (!parts.length) { mcpStatus("enter a command", false); return; }
      payload.command = parts[0];
      payload.args = parts.slice(1);
    } else {
      const url = $("murl").value.trim();
      if (!url) { mcpStatus("enter a URL", false); return; }
      payload.url = url;
      const token = $("mtoken").value.trim();
      if (token) payload.token = token;
    }
    try {
      const out = await post("/api/mcp", payload);
      state.config.mcp = out.config;
      renderMcp();
      $("mname").value = ""; $("murl").value = ""; $("mcmd").value = ""; $("mtoken").value = "";
      const warning = out.transport_warning ? ` — ${out.transport_warning}` : "";
      mcpStatus(`added "${name}"${warning}`, !out.transport_warning);
    } catch (err) { mcpStatus("add failed: " + err.message, false); }
  }

  async function searchMcp() {
    const query = $("mquery").value.trim();
    if (!query) return;
    const box = $("mresults");
    box.innerHTML = `<div class="dim">searching…</div>`;
    try {
      const out = await post("/api/mcp/search", { query });
      if (!out.ok) { box.innerHTML = `<div class="dim">${esc(out.error || "search failed")}</div>`; return; }
      box.innerHTML = "";
      if (!out.servers.length) { box.innerHTML = `<div class="dim">no matches</div>`; return; }
      out.servers.forEach((server) => {
        const el = document.createElement("div");
        el.className = "recent";
        el.innerHTML = `<strong>${esc(server.name)}</strong> — ${esc(server.description || "")}`;
        el.title = "click to add";
        el.onclick = () => { $("mname").value = server.name; $("murl").value = server.url || ""; };
        box.appendChild(el);
      });
    } catch (err) { box.innerHTML = `<div class="dim">${esc(err.message)}</div>`; }
  }

  $("mcpbtn").onclick = () => { setMenu(false); renderMcp(); renderCatalog(); $("mcpmodal").classList.add("open"); };
  $("mcpclose").onclick = () => $("mcpmodal").classList.remove("open");
  $("mcpmodal").addEventListener("click", (ev) => { if (ev.target === $("mcpmodal")) $("mcpmodal").classList.remove("open"); });
  $("mkind").onchange = () => {
    const stdio = $("mkind").value === "stdio";
    $("mcmdrow").style.display = stdio ? "flex" : "none";
    $("murlrow").style.display = stdio ? "none" : "flex";
    $("mtokenrow").style.display = stdio ? "none" : "flex";
  };
  $("madd").onclick = addMcpServer;
  $("msearch").onclick = searchMcp;
  $("mquery").addEventListener("keydown", (ev) => { if (ev.key === "Enter") searchMcp(); });

  // ---------- permission rules ----------
  // The policy engine supported layered allow/ask/deny rules already, including argument-aware ones
  // like "run_bash:git *", but only reachable by hand-editing settings.json. These call the same
  // engine; nothing about the precedence model changes.
  const EXAMPLE_RULES = [
    { tool: "run_bash", pattern: "git *", decision: "allow", why: "let the agent use git freely" },
    { tool: "run_bash", pattern: "git push *", decision: "ask", why: "but always confirm a push" },
    { tool: "run_bash", pattern: "rm -rf *", decision: "deny", why: "never allow a recursive delete" },
    { tool: "write_file", pattern: "*.md", decision: "allow", why: "trust documentation edits" },
    { tool: "*", pattern: "", decision: "ask", why: "ask for everything not covered above" },
  ];

  function ruleKey(tool, pattern) {
    return pattern ? `${tool}:${pattern}` : tool;
  }

  function rulesStatus(text, ok) {
    const el = $("rstatus");
    el.textContent = text;
    if (text) el.className = ok ? "ok" : "err";
  }

  function renderRules() {
    const box = $("ruleslist");
    const rules = (state.config && state.config.rules) || {};
    const userRules = rules.user_rules || {};
    const keys = Object.keys(userRules);
    box.innerHTML = "";
    if (!keys.length) {
      box.innerHTML = `<div class="dim" style="padding:2px 0 6px">No rules yet — every action follows the current mode and approval setting.</div>`;
    }
    keys.forEach((key) => {
      const decision = userRules[key];
      const row = document.createElement("div");
      row.className = "vendrow";
      const colour = decision === "deny" ? "var(--err)" : decision === "allow" ? "var(--ok)" : "var(--warn)";
      row.innerHTML = `<span class="vname" style="color:${colour}">${esc(decision)}</span>
        <span class="vurl">${esc(key)}</span>
        <button class="vdel" title="Remove">×</button>`;
      row.querySelector(".vdel").onclick = () => saveRules(key, null);
      box.appendChild(row);
    });
    if (rules.higher_priority_active) {
      const note = document.createElement("div");
      note.className = "dim";
      note.style.cssText = "font-size:11px;padding-top:6px";
      note.textContent = "A project or system settings file also defines rules; those take precedence.";
      box.appendChild(note);
    }

    const examples = $("rexamples");
    examples.innerHTML = "";
    EXAMPLE_RULES.forEach((example) => {
      const el = document.createElement("div");
      el.className = "recent";
      el.innerHTML = `<strong>${esc(example.decision)}</strong> ${esc(ruleKey(example.tool, example.pattern))} — ${esc(example.why)}`;
      el.title = "click to fill the form";
      el.onclick = () => { $("rtool").value = example.tool; $("rpattern").value = example.pattern; $("rdecision").value = example.decision; };
      examples.appendChild(el);
    });
  }

  async function saveRules(key, decision) {
    const rules = { ...(((state.config.rules || {}).user_rules) || {}) };
    if (decision === null) delete rules[key];
    else rules[key] = decision;
    try {
      const out = await post("/api/rules", { rules });
      state.config.rules = out.rules;
      renderRules();
      rulesStatus(decision === null ? `removed ${key}` : `saved ${key} = ${decision}`, true);
    } catch (err) { rulesStatus(err.message, false); }
  }

  function addRule() {
    const tool = $("rtool").value.trim();
    const pattern = $("rpattern").value.trim();
    if (!tool) { rulesStatus("enter a tool name, or * for every tool", false); return; }
    saveRules(ruleKey(tool, pattern), $("rdecision").value).then(() => {
      if (!document.getElementById("rstatus").className.includes("err")) {
        $("rtool").value = ""; $("rpattern").value = "";
      }
    });
  }

  $("rulesbtn").onclick = () => { setMenu(false); renderRules(); $("rulesmodal").classList.add("open"); };
  $("rulesclose").onclick = () => $("rulesmodal").classList.remove("open");
  $("rulesmodal").addEventListener("click", (ev) => { if (ev.target === $("rulesmodal")) $("rulesmodal").classList.remove("open"); });
  $("radd").onclick = addRule;
  $("rtool").addEventListener("keydown", (ev) => { if (ev.key === "Enter") addRule(); });

  // ---------- plugins ----------
  // Plugins are Python files the user placed in a plugins/ directory; nothing is fetched or
  // installed. This panel reports what loaded, what contributed what, and what failed -- a broken
  // plugin is skipped rather than stopping the agent, so without this it would be invisible.
  function renderPlugins() {
    const info = (state.config && state.config.plugins) || {};
    $("plugdirs").innerHTML = (info.dirs || []).map((d) => `looked in: ${esc(d)}`).join("<br>");
    const box = $("pluglist");
    box.innerHTML = "";
    const plugins = info.plugins || [];
    if (!plugins.length) {
      box.innerHTML = `<div class="dim" style="padding:2px 0 6px">No plugins found. Create a <code>.py</code> file in a directory above.</div>`;
      return;
    }
    plugins.forEach((plugin) => {
      const row = document.createElement("div");
      row.className = "vendrow";
      const ok = plugin.ok;
      const colour = ok ? "var(--ok)" : "var(--err)";
      const detail = ok
        ? [
            plugin.tools.length ? `${plugin.tools.length} tool(s): ${plugin.tools.join(", ")}` : "no tools",
            plugin.hooks.length ? `${plugin.hooks.length} hook(s)` : "no hooks",
          ].join(" · ")
        : plugin.error;
      row.innerHTML = `<span class="vname" style="color:${colour}">${ok ? "loaded" : "failed"}</span>
        <span class="vurl" title="${esc(detail)}">${esc(plugin.name)} ${plugin.version ? "v" + esc(plugin.version) : ""} — ${esc(detail)}</span>`;
      box.appendChild(row);
    });
    const hooks = info.hooks || {};
    const hookKeys = Object.keys(hooks);
    if (hookKeys.length) {
      const note = document.createElement("div");
      note.className = "dim";
      note.style.cssText = "font-size:11px;padding-top:6px";
      note.textContent = "active hooks: " + hookKeys.map((k) => `${k}×${hooks[k]}`).join(", ");
      box.appendChild(note);
    }
  }

  async function reloadPlugins() {
    try {
      const out = await post("/api/plugins/reload", {});
      state.config.plugins = out;
      renderPlugins();
      const failed = out.failed || [];
      addNotice(failed.length
        ? `plugins reloaded; ${failed.length} failed: ${failed.join(", ")}`
        : `plugins reloaded: ${out.count} loaded, ${(out.tools || []).length} tool(s)`, failed.length ? "warning" : "success");
    } catch (err) { addNotice("plugin reload failed: " + err.message, "error"); }
  }

  $("plugbtn").onclick = () => { setMenu(false); renderPlugins(); $("plugmodal").classList.add("open"); };
  $("plugclose").onclick = () => $("plugmodal").classList.remove("open");
  $("plugmodal").addEventListener("click", (ev) => { if (ev.target === $("plugmodal")) $("plugmodal").classList.remove("open"); });
  $("plugreload").onclick = reloadPlugins;

  // ---------- messaging (WhatsApp) ----------
  // Credentials are never returned by the server, so these fields show only whether one is stored.
  // Leaving a credential field blank means "keep the stored value" -- treating blank as a new value
  // would erase the secret every time any other field was edited.
  function renderMessaging() {
    const info = (state.config && state.config.messaging) || {};
    $("msgprovider").value = info.provider || "generic";
    $("msgenabled").checked = !!info.enabled;
    $("msgallow").value = (info.allow || []).join(", ");
    $("msgnotify").value = info.notify || "";
    $("msgsid").value = info.account_sid || "";
    $("msgpnid").value = info.phone_number_id || "";
    $("msgfrom").value = info.from_number || "";
    $("msgsendurl").value = info.send_url && info.send_url.startsWith("http") ? info.send_url : "";
    $("msgtoken").value = "";
    $("msgsecret").value = "";
    $("msgacctoken").value = "";
    $("msgtoken").placeholder = info.has_auth_token ? "stored — leave blank to keep" : "auth token";
    $("msgsecret").placeholder = info.has_secret ? "stored — leave blank to keep" : "optional";
    $("msgacctoken").placeholder = info.has_access_token ? "stored — leave blank to keep" : "access token";

    const p = info.provider || "generic";
    $("msgtwilio").style.display = p === "twilio" ? "block" : "none";
    $("msgmeta").style.display = p === "meta" ? "block" : "none";
    $("msggeneric").style.display = p === "generic" ? "block" : "none";

    // Access line: says, in words, who is currently able to drive this agent.
    const allow = info.allow || [];
    const access = $("msgaccess-note");
    const accessText = $("msgaccess-text");
    if (!allow.length) {
      access.className = "statusline warn";
      accessText.textContent = "Nobody may drive the agent — no numbers listed.";
    } else if (!info.enabled) {
      access.className = "statusline";
      accessText.textContent = `${allow.length} number(s) listed, but inbound messages are switched off.`;
    } else {
      access.className = "statusline on";
      accessText.textContent = `${allow.length} number(s) may drive the agent.`;
    }

    const stats = info.stats || {};
    const statsLine = $("msgstats");
    statsLine.className = "statusline " + (info.configured ? "on" : "off");
    $("msgstats-text").textContent =
      `POST /api/inbound · sent ${stats.sent || 0}, failed ${stats.failed || 0} · ` +
      (info.configured ? "ready" : "not usable yet — needs an allowed number and credentials");
  }

  function messagingStatus(text, ok) {
    const el = $("msgstatus");
    el.textContent = text;
    el.className = text ? (ok ? "ok" : "err") : "";
  }

  async function saveMessaging() {
    const body = {
      provider: $("msgprovider").value,
      enabled: $("msgenabled").checked,
      allow: $("msgallow").value.split(",").map((s) => s.trim()).filter(Boolean),
      notify: $("msgnotify").value.trim(),
      secret: $("msgsecret").value,
      account_sid: $("msgsid").value.trim(),
      auth_token: $("msgtoken").value,
      phone_number_id: $("msgpnid").value.trim(),
      access_token: $("msgacctoken").value,
      from_number: $("msgfrom").value.trim(),
    };
    if ($("msgprovider").value === "generic") body.send_url = $("msgsendurl").value.trim();
    // Blank credentials mean "keep the stored value", so removing one needs its own signal; otherwise
    // a rotated or leaked token could be replaced but never deleted.
    if ($("msgclearsecret").checked) body.clear_secrets = ["secret"];
    try {
      const out = await post("/api/messaging", body);
      state.config.messaging = out;
      $("msgclearsecret").checked = false;
      renderMessaging();
      messagingStatus(out.configured ? "saved and ready" : "saved", true);
    } catch (err) { messagingStatus("save failed: " + err.message, false); }
  }

  $("msgbtn").onclick = () => { setMenu(false); renderMessaging(); $("msgmodal").classList.add("open"); };
  $("msgclose").onclick = () => $("msgmodal").classList.remove("open");
  $("msgmodal").addEventListener("click", (ev) => { if (ev.target === $("msgmodal")) $("msgmodal").classList.remove("open"); });
  $("msgsave").onclick = saveMessaging;
  $("msgprovider").onchange = renderMessaging;

  // ---------- the menu ----------
  // One burger replaces the row of abbreviated buttons. Every entry closes the menu first, so opening a
  // dialog never leaves the popup floating over it.
  function setMenu(open) {
    $("menupop").hidden = !open;
    $("menubtn").setAttribute("aria-expanded", open ? "true" : "false");
  }
  function toggleMenu() { setMenu($("menupop").hidden); }
  $("menubtn").onclick = (ev) => { ev.stopPropagation(); toggleMenu(); };
  document.addEventListener("click", (ev) => {
    if (!$("menupop").hidden && !$("menupop").contains(ev.target) && ev.target !== $("menubtn")) setMenu(false);
  });
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") setMenu(false); });

  // Each entry is wrapped so the menu closes before the dialog opens, rather than duplicating the open
  // logic for every panel.
  function menuAction(id, run) {
    const el = $(id);
    if (!el) return;
    el.onclick = () => { setMenu(false); run(); };
  }

  function setBadge(id, text) {
    const el = $(id);
    if (el) el.textContent = text || "";
  }

  function refreshBadges() {
    const config = state.config || {};
    const mcp = config.mcp || {};
    const enabled = (mcp.servers || []).filter((s) => s.enabled).length;
    setBadge("mcpbadge", enabled ? `${enabled} on` : "");
    const plugins = config.plugins || {};
    setBadge("plugbadge", plugins.count ? String(plugins.count) : "");
    const rules = config.rules || {};
    const ruleCount = Object.keys(rules.user_rules || {}).length;
    setBadge("rulesbadge", ruleCount ? String(ruleCount) : "");
    setBadge("msgbadge", (config.messaging || {}).configured ? "on" : "");
    const loci = (config.loci || {}).loci || [];
    const openLoci = loci.filter((d) => d.open_goals).length;
    setBadge("locisbadge", openLoci ? String(openLoci) : "");
    // Rail counters come from the same values as the menu badges, so the two can never disagree.
    setBadge("navLocuss", openLoci ? String(openLoci) : "");
    setBadge("navMcp", enabled ? String(enabled) : "");
    setBadge("navPlug", plugins.count ? String(plugins.count) : "");
    setBadge("navRules", ruleCount ? String(ruleCount) : "");
    setBadge("navMsg", (config.messaging || {}).configured ? "on" : "");
    // The session and approval counters are set from the mission payload instead (see
    // `renderMission`). They were read from `config.runs`, which `config_payload()` does not send --
    // so the value was always undefined and both badges stayed empty, while the Mission control view
    // on the same screen showed a real approval count. A counter that can never render is worse than
    // no counter: it looks like there is nothing waiting.
  }

  // ---------- persistent agents (loci) ----------
  // The panel is a view over loci.json. Every mutation posts to /api/loci and re-renders from the
  // server's reply rather than patching local state: the terminal and another browser tab share
  // the same file, so the reply is the only authoritative picture.
  function renderLocusActivity(entries) {
    if (!entries || !entries.length) return `<div class="locusmeta">No activity recorded yet.</div>`;
    const rows = entries.slice(0, 14).map((entry) => {
      const when = new Date((entry.at || 0) * 1000).toLocaleString(undefined,
        { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
      const kind = String(entry.kind || "");
      return `<li><span class="lwhen">${esc(when)}</span>` +
             `<span class="lkind ${esc(kind)}">${esc(kind)}</span>` +
             `<span>${esc(entry.summary || "")}</span></li>`;
    }).join("");
    return `<ul class="locuslog">${rows}</ul>`;
  }

  function renderLocusGoals(locus) {
    if (!locus.goals || !locus.goals.length) {
      return `<div class="locusmeta">No objectives — it has nothing to work on.</div>`;
    }
    const rows = locus.goals.map((goal) => `
      <li data-goal="${esc(goal.id)}">
        <span class="gstatus ${esc(goal.status)}">${esc(goal.status)}</span>
        <span class="gtitle" title="${esc(goal.detail || goal.title)}">${esc(goal.title)}</span>
        <span class="gid">${esc(goal.id)}</span>
        <span class="gbtns">
          ${goal.status === "done" ? "" : `<button class="ghost small" data-goalstatus="done" title="Mark complete">done</button>`}
          ${goal.status === "blocked" ? "" : `<button class="ghost small" data-goalstatus="blocked" title="Needs a decision from you">block</button>`}
        </span>
      </li>`).join("");
    return `<ul class="goals">${rows}</ul>`;
  }

  // The gallery. Rendered from the payload's templates, so adding a template to Python makes it
  // appear here with no dashboard change.
  function renderBotTemplates(info) {
    const box = $("bottemplates");
    if (!box) return;
    const templates = (info && info.templates) || [];
    if (!templates.length) {
      box.innerHTML = `<p class="mempty">No templates available in this build.</p>`;
      return;
    }
    box.innerHTML = templates.map((t) => `
      <div class="botcard${t.installed ? " done" : ""}">
        <div class="bctop">
          <span class="bcicon">${esc(t.emoji || "◆")}</span>
          <span class="bcname">${esc(t.name)}</span>
        </div>
        <div class="bcrole">${esc(t.role)}${t.proactive ? " · wakes on an interval" : ""}</div>
        <div class="bctag">${esc(t.tagline)}</div>
        <button class="bcgo" data-template="${esc(t.key)}"${t.installed ? ' aria-disabled="true"' : ""}>
          ${t.installed ? "already added" : "Add this bot"}
        </button>
      </div>`).join("");
    box.querySelectorAll("[data-template]").forEach((button) => {
      button.onclick = () => {
        if (button.getAttribute("aria-disabled") === "true") return;
        createFromTemplate(button.dataset.template);
      };
    });
  }

  async function createFromTemplate(key) {
    locusStatus(`adding ${key}…`);
    try {
      const out = await post("/api/loci", { action: "template", template: key });
      state.config.loci = out.loci || state.config.loci;
      renderLoci();
      refreshBadges();
      locusStatus(out.created ? `added ${out.locus}` : `updated ${out.locus}`, "ok");
      addNotice(out.created ? `Added the ${out.locus} bot` : `Updated ${out.locus}`, "success");
    } catch (err) {
      locusStatus(String(err.message || err), "error");
      addNotice("templates: " + err.message, "error");
    }
  }

  // ---------- the Loci page: roster on the left, the selected locus's own chat on the right ----------
  // `locusChat` is the whole of this page's state. It is deliberately NOT the main session: the
  // defect this page fixes was a locus run calling `attach()`, which repointed the Myriaxon chat at
  // the locus's session. Nothing here touches `state.session`.
  const locusChat = { name: "", locus: null, sessionId: "", poll: null, sending: false };

  function locusByName(name) {
    const info = (state.config && state.config.loci) || {};
    return (info.loci || []).find((l) => l.name === name) || null;
  }

  // One compact row per locus. The full card -- objectives, activity log, six buttons -- lives on the
  // right for the selected locus only, so a machine with a dozen loci is a scannable list rather
  // than a page of forms.
  function locusRow(locus) {
    const row = document.createElement("div");
    row.className = "locusrow" + (locus.due_now ? " due" : "") +
                    (locus.name === locusChat.name ? " selected" : "");
    // Which locus this card is, as an attribute rather than only inside the closure that built it.
    // Mission control's approval "Open" needs to scroll to a specific locus's card, and it has the
    // locus's name from the approval id -- without this it could only open the panel and leave the
    // user to find the locus by eye.
    row.dataset.locusname = locus.name;
    const flags = [
      locus.running ? `<span class="locustag live">working</span>` : "",
      locus.proactive ? `<span class="locustag on">proactive</span>` : "",
      locus.enabled ? "" : `<span class="locustag off">paused</span>`,
      locus.due_now && !locus.running ? `<span class="locustag live">due</span>` : "",
    ].join("");
    row.innerHTML = `
      <div class="locushead">
        <span class="markslot mark-mini" data-marksize="13"></span>
        <span class="locusname">${esc(locus.name)}</span>
        <span class="locusrole">${esc(locus.role)}</span>
        ${flags}
      </div>
      <div class="locusmeta">${locus.open_goals} open objective(s) · ${esc(locus.workspace)}</div>
      ${lastOutcomeLine(locus)}`;
    // Clicking the row opens that locus's own chat. There is no "take over my chat" action any more.
    row.onclick = () => openLocusChat(locus.name);
    return row;
  }

  // WHAT THE LAST RUN DID, on the card, because otherwise it is invisible.
  //
  // Measured: a locus whose run had been REFUSED and a locus whose run had finished cleanly rendered
  // identically -- both just "N open objective(s)". The refusal lived in the activity log, which needs the
  // panel open on that locus and is easy to scroll past, and a run that silently did nothing looked the
  // same as one that was working. The server now sends `last_outcome`; this is the half that makes it
  // visible, because a field nobody renders is still invisible.
  //
  // Rendered as DATA, never as markup: the summary comes from `RunOutcome.describe()` and an error can
  // carry model output, so it goes through `esc`.
  function lastOutcomeLine(locus) {
    const o = locus.last_outcome;
    if (!o || !o.summary) return "";
    const age = o.at ? timeAgo(o.at) : "";
    const failed = !o.ok;
    const retried = (o.attempts || 0) > 1 ? ` after ${o.attempts} attempts` : "";
    return `<div class="locusoutcome ${failed ? "bad" : "good"}">
        <span class="lc-out-dot"></span>${esc(o.summary)}${esc(retried)}${age ? ` · ${esc(age)}` : ""}
        ${failed && o.error ? `<div class="lc-out-err">${esc(String(o.error).slice(0, 200))}</div>` : ""}
      </div>`;
  }

  // "12s ago" rather than a timestamp, because the question the line answers is "is this current?".
  function timeAgo(at) {
    const secs = Math.max(0, Math.floor(Date.now() / 1000 - at));
    if (secs < 45) return "just now";
    if (secs < 5400) return `${Math.round(secs / 60)}m ago`;
    if (secs < 172800) return `${Math.round(secs / 3600)}h ago`;
    return `${Math.round(secs / 86400)}d ago`;
  }

  function renderLoci() {
    const info = (state.config && state.config.loci) || {};
    const box = $("locislist");
    // The gallery is rendered first and unconditionally. Both of the early returns below used to
    // skip it, which meant the templates were invisible in exactly the case they matter most --
    // an empty panel, where a new user has nothing to click.
    renderBotTemplates(info);
    if (info.error) {
      box.innerHTML = `<div class="warnbox">Could not read the locus registry: ${esc(info.error)}</div>`;
      return;
    }
    const list = info.loci || [];
    const count = $("lociscount");
    if (count) {
      const open = list.reduce((total, d) => total + (d.open_goals || 0), 0);
      const working = list.filter((d) => d.running).length;
      count.textContent = list.length
        ? `— ${list.length}, ${open} open${working ? `, ${working} working` : ""}`
        : "";
    }
    if (!list.length) {
      box.innerHTML = `<div class="locusempty">No loci yet. Pick one from the templates, or write your own:
        a persistent agent with a role, standing instructions and objectives that survive restarts — so it
        needs no re-briefing and does not wait to be asked.</div>`;
      // With nothing in the roster, the gallery is the only useful thing on the page, so it opens
      // itself. It stays collapsed once a locus exists, where the conversation is what matters.
      $("locistemplates").hidden = false;
      return;
    }
    box.innerHTML = "";
    list.forEach((locus) => box.appendChild(locusRow(locus)));
    // The mark is declared once in <template>; stamp it into the rows just built.
    stampMarks();
  }

  function setLocusPaneVisible(hasLocus) {
    $("locusctrls").hidden = !hasLocus;
    $("locuscomposer").style.display = hasLocus ? "" : "none";
    $("locusdetail").style.display = hasLocus ? "" : "none";
  }

  function locusDetailHtml(locus) {
    const goals = (locus.goals || []).length
      ? renderLocusGoals(locus)
      : `<div class="locusmeta">No objectives — it has nothing to work on until you add one.</div>`;
    return `
      <div><b>Standing instructions</b><div class="locusmeta">${locus.instructions ? esc(locus.instructions) : "none"}</div></div>
      <div style="margin-top:8px"><b>Objectives</b>${goals}</div>
      <div class="locusform">
        <label class="field">
          <span class="flabel">Add an objective</span>
          <input id="lc-newgoal" placeholder="Keep CHANGELOG.md current after every merge" autocomplete="off">
        </label>
        <button class="ghost small" id="lc-addgoal">Add objective</button>
      </div>
      <div style="margin-top:8px"><b>Activity</b>${renderLocusActivity(locus.activity)}</div>
      <div class="locusmeta" style="margin-top:8px">locus id ${esc(locus.id)} ·
        session ${esc(locusChat.sessionId || "none yet")} ·
        ${locus.enabled ? "enabled" : "paused"} ·
        ${locus.proactive ? `wakes every ${locus.interval_seconds}s` : "on demand only"}</div>`;

  }

  function renderLocusHeader() {
    const locus = locusChat.locus;
    $("locuschatname").textContent = locus ? locus.name : "No locus selected";
    $("locuschatsub").textContent = locus
      ? (locus.idle_reason
          ? `${locus.role} · ${locus.idle_reason}`
          : `${locus.role} · ${locus.open_goals} open objective(s) · ${locus.workspace}`)
      : "Pick one on the left to see its conversation.";
    const state = $("locuschatstate");
    if (!locus) { state.textContent = ""; state.className = "lc-state"; return; }
    if (locus.running) { state.textContent = "working now"; state.className = "lc-state running"; }
    else if (!locus.enabled) { state.textContent = "paused"; state.className = "lc-state paused"; }
    else if (locus.due_now) { state.textContent = "due"; state.className = "lc-state running"; }
    else { state.textContent = "idle"; state.className = "lc-state"; }
    $("lc-enable").textContent = locus.enabled ? "Pause" : "Enable";
    $("lc-proactive").textContent = locus.proactive ? "Stop waking" : "Wake on interval";
    // The autonomy control says what the mode IS, not just what clicking will do, because the two modes
    // differ in whether this agent may choose its own work -- and that is not something a button label
    // alone should have to carry. The confinement travels with it: an owner who grants self-direction
    // must be able to see, in the same breath, where the agent may act.
    const auto = $("lc-autonomy");
    if (auto) {
      auto.textContent = locus.self_directed ? "Self-directed" : "Works your objectives";
      auto.classList.toggle("on", !!locus.self_directed);
      auto.title = locus.self_directed
        ? "It may decide and record its own objectives, up to " + (locus.steps_this_run || 1) +
          " step(s) per run. It can only act inside " + (locus.confined_to || "its own folder") + "."
        : "It works only the objectives you gave it. Click to let it decide its own work.";
    }
    const bound = $("lc-bound");
    if (bound) {
      bound.textContent = locus.self_directed
        ? "confined to " + (locus.confined_to || "its own folder")
        : "";
      bound.hidden = !locus.self_directed;
      bound.title = "Self-directed is not unrestricted: this is the only folder it may act in.";
    }
    $("lc-run").textContent = locus.running ? "Working…" : "Run objective";
    $("lc-run").disabled = !!locus.running;
    // The stop control exists only while there is something to stop, so it never invites a click that
    // would do nothing.
    $("lc-stop").hidden = !locus.running;
    // The avatar is the same generated SVG the rail uses, redrawn in the locus's current mood.
    setLocusAvatar(locus.running ? "thinking" : locus.enabled ? "idle" : "sleepy");
  }

  function setLocusAvatar(expression) {
    const box = $("locusavatar");
    if (!box) return;
    box.dataset.expression = expression;
    box.dataset.mood = expression === "thinking" ? "think" : expression === "sleepy" ? "sleep" : "calm";
    box.setAttribute("aria-label", `Loci, ${expression}`);
    const draw = LOCI_CACHE.get(expression);
    if (draw) { box.innerHTML = draw; return; }
    // `/api/avatar` is the endpoint that exists -- the CLI's renderer, served. A made-up
    // `/api/loci/avatar` would 404 and the pane would simply show no character.
    fetch(`/api/avatar?expression=${encodeURIComponent(expression)}&size=30`)
      .then((r) => (r.ok ? r.text() : ""))
      .then((svg) => { if (svg) { LOCI_CACHE.set(expression, svg); box.innerHTML = svg; } })
      .catch(() => {});
  }

  async function openLocusChat(name) {
    locusChat.name = name;
    locusChat.locus = locusByName(name);
    renderLoci();
    renderLocusHeader();
    setLocusPaneVisible(!!locusChat.locus);
    if (!locusChat.locus) return;
    await loadLocusTranscript();
  }

  async function loadLocusTranscript() {
    const box = $("locustranscript");
    if (!locusChat.locus) return;
    try {
      const data = await get(`/api/loci?transcript=${encodeURIComponent(locusChat.name)}`);
      if (data && data.loci) { state.config.loci = data; }
      locusChat.sessionId = (data && data.transcript_session) || "";
      const turns = (data && data.transcript) || [];
      box.innerHTML = "";
      if (!turns.length) {
        box.innerHTML = `<div class="lc-empty">Nothing said yet. Send it a message below, or press
          <b>Run objective</b> and watch it work. Everything it does stays on this page.</div>`;
      }
      turns.forEach((turn) => {
        const wrap = document.createElement("div");
        wrap.className = "lc-turn " + (turn.role === "user" ? "you" : "them");
        const label = document.createElement("div");
        label.className = "lc-who-label";
        label.textContent = turn.role === "user" ? "You" : locusChat.name;
        const bubble = document.createElement("div");
        bubble.className = "lc-bubble";
        // textContent, not innerHTML: this is model output and file contents, and building markup
        // from either is how a transcript becomes a scripting vector.
        bubble.textContent = turn.text || "";
        wrap.append(label, bubble);
        box.appendChild(wrap);
      });
      box.scrollTop = box.scrollHeight;
      // The roster entry carries `running`, so refreshing the pane also updates "working now".
      const fresh = locusByName(locusChat.name);
      if (fresh) { locusChat.locus = fresh; renderLocusHeader(); renderLoci(); }
      scheduleLocusPoll();
    } catch (err) {
      locusStatus(String(err.message || err), "error");
    }
  }

  // While a locus is working, its transcript is refreshed on a timer. Its turn runs in the server's
  // session thread, and the session's SSE stream is what the *main* chat listens to -- subscribing
  // the locus pane to it as well would give one turn two readers writing two panes, which is the
  // coupling this page exists to remove. A poll only while something is actually running costs
  // nothing when nothing is.
  function scheduleLocusPoll() {
    if (locusChat.poll) { clearTimeout(locusChat.poll); locusChat.poll = null; }
    if (!locusChat.locus || (!locusChat.locus.running && !locusChat.sending)) return;
    locusChat.poll = setTimeout(() => { loadLocusTranscript(); }, 1500);
  }

  async function sendToLocus(text) {
    const locus = locusChat.locus;
    if (!locus) return;
    const message = (text || "").trim();
    if (!message) return;
    locusChat.sending = true;
    $("locusend").disabled = true;
    locusStatus(`sending to ${locus.name}…`);
    try {
      const out = await post("/api/loci", { action: "run", locus: locus.name, message });
      if (!out.accepted) {
        locusStatus(`${locus.name}: ${out.reason || "could not start"}`, "warn");
        return;
      }
      locusStatus(`${locus.name} is working`, "ok");
      await loadLocusTranscript();
    } catch (err) {
      locusStatus(String(err.message || err), "error");
    } finally {
      locusChat.sending = false;
      $("locusend").disabled = false;
    }
  }

  async function runLocusHere(message) {
    // "Run objective" and the composer are the same call; the objective run sends no message, which
    // is what makes the locus advance its own work instead of answering you.
    const locus = locusChat.locus;
    if (!locus) return;
    if (!message) {
      locusStatus(`starting ${locus.name} on its next objective…`);
      try {
        const out = await post("/api/loci", { action: "run", locus: locus.name, message: "" });
        locusStatus(out.accepted ? `${locus.name} is working on its objectives`
                                 : `${locus.name}: ${out.reason || "could not start"}`,
                    out.accepted ? "ok" : "warn");
        await loadLocusTranscript();
      } catch (err) {
        locusStatus(String(err.message || err), "error");
      }
      return;
    }
    await sendToLocus(message);
  }

  async function locusToggle(field, value) {
    const locus = locusChat.locus;
    if (!locus) return;
    await locusAction({ action: "toggle", locus: locus.name, [field]: value });
    const fresh = locusByName(locus.name);
    if (fresh) { locusChat.locus = fresh; renderLocusHeader(); }
  }

  async function locusDelete() {
    const locus = locusChat.locus;
    if (!locus) return;
    if (!confirm(`Delete the locus "${locus.name}" and its ${(locus.goals || []).length} objective(s)?\n\n` +
                 `Its conversation file stays on disk; the locus itself is removed.`)) return;
    await locusAction({ action: "delete", locus: locus.name });
    locusChat.name = ""; locusChat.locus = null; locusChat.sessionId = "";
    $("locustranscript").innerHTML =
      `<div class="lc-empty">That locus is gone. Pick another on the left.</div>`;
    renderLoci(); renderLocusHeader(); setLocusPaneVisible(false);
  }

  // Re-rendering the roster after any mutation keeps the selected locus's panel in step with it, so
  // a toggle does not leave the right-hand pane describing the state it had a moment ago.
  function refreshSelectedLocus() {
    if (!locusChat.name) return;
    const fresh = locusByName(locusChat.name);
    locusChat.locus = fresh;
    if (fresh) { renderLocusHeader(); $("locusdetail").innerHTML = locusDetailHtml(fresh); bindLocusDetail(); }
  }

  function bindLocusDetail() {
    const add = $("lc-addgoal");
    if (add) {
      add.onclick = () => {
        const input = $("lc-newgoal");
        const title = (input.value || "").trim();
        if (!title) { locusStatus("the objective needs a title", "warn"); return; }
        locusAction({ action: "goal_add", locus: locusChat.name, title });
        input.value = "";
      };
    }
    document.querySelectorAll("#locusdetail [data-goalstatus]").forEach((button) => {
      button.onclick = () => locusAction({
        action: "goal_status", locus: locusChat.name,
        goal: button.closest("li").dataset.goal, status: button.dataset.goalstatus,
      });
    });
  }

  function locusStatus(text, kind) {
    // One status line for the whole page, coloured by state, so an action always reports back
    // somewhere the user is already looking rather than in a line that appears only sometimes.
    const line = $("locistatusline");
    const el = $("locisstatus");
    if (!el) return;
    el.textContent = text || "Ready.";
    if (line) {
      line.className = "statusline " +
        (kind === "error" ? "err" : kind === "ok" ? "on" : kind === "warn" ? "warn" : "");
    }
  }

  async function locusAction(body) {
    locusStatus("working…");
    try {
      const out = await post("/api/loci", body);
      state.config.loci = out.loci || state.config.loci;
      renderLoci();
      refreshBadges();
      refreshSelectedLocus();
      locusStatus(`${body.action.replace("_", " ")} ok`, "ok");
    } catch (err) {
      locusStatus(String(err.message || err), "error");
    }
  }

  // A locus run is NOT an ordinary Myriaxon turn any more, and this is the whole point of the page.
  //
  // It used to call `attach(out.session.id)`, which repointed the Myriaxon chat at the locus's
  // session: the roster closed, the transcript the user was reading was replaced by the locus's, and
  // every `[tool.name]…` line the locus's console printed appeared in the Myriaxon conversation. Two
  // agents ended up sharing one transcript with no way to tell which was speaking.
  //
  // The run now stays on this page. The server still executes it in the locus's own session -- that
  // is what gives it a transcript, a busy flag and a cancellation path -- and this pane reads that
  // session's messages directly. `state.session` is never touched.

  async function createLocus() {
    const name = $("locusname").value.trim();
    if (!name) { locusStatus("a locus needs a name", "error"); return; }
    const goals = $("locusgoals").value.split("\n").map((s) => s.trim()).filter(Boolean);
    locusStatus("creating…");
    try {
      const out = await post("/api/loci", {
        action: "create", name,
        role: $("locusrole").value.trim() || "generalist",
        instructions: $("locusinstr").value.trim(),
        goals,
        proactive: $("locusproactive").checked,
        interval_seconds: parseInt($("locusevery").value, 10) || 900,
      });
      state.config.loci = out.loci || state.config.loci;
      ["locusname", "locusrole", "locusgoals", "locusinstr"].forEach((id) => { $(id).value = ""; });
      $("locusproactive").checked = false;
      $("locisform").hidden = true;
      renderLoci();
      refreshBadges();
      // Opened straight away: creating a locus and then having to find it in the roster is a step
      // that exists only because the panel used to have nowhere to put the conversation.
      await openLocusChat(name);
      locusStatus(
        goals.length
          ? `Created ${name}.`
          : `Created ${name} — it will do nothing until you give it an objective.`,
        goals.length ? "ok" : "warn"
      );
    } catch (err) {
      locusStatus(String(err.message || err), "error");
    }
  }

  async function refreshLoci() {
    try {
      const out = await get("/api/loci");
      state.config.loci = out;
      renderLoci();
      refreshBadges();
      refreshSelectedLocus();
    } catch (err) {
      locusStatus(String(err.message || err), "error");
    }
  }

  // Opening the page always lands on a locus's own chat rather than a wall of settings: the first
  // locus if one is selected, otherwise the first that exists at all.
  $("locisbtn").onclick = () => {
    setMenu(false);
    $("locismodal").classList.add("open");
    renderLoci();
    const wanted = locusChat.name || (((state.config.loci || {}).loci || [])[0] || {}).name || "";
    if (wanted) openLocusChat(wanted);
    else { renderLocusHeader(); setLocusPaneVisible(false); }
  };
  $("lociclose").onclick = () => {
    $("locismodal").classList.remove("open");
    // The poll is stopped with the page: a timer that keeps asking the server for a transcript
    // nobody is looking at is exactly the kind of background work this page should not create.
    if (locusChat.poll) { clearTimeout(locusChat.poll); locusChat.poll = null; }
  };
  $("locismodal").addEventListener("click", (ev) => {
    if (ev.target === $("locismodal")) $("lociclose").click();
  });
  $("locirefresh").onclick = refreshLoci;
  $("locisrefresh2").onclick = refreshLoci;

  // ============================================================== the pane wall
  //
  // Several loci side by side so a multi-agent run can be watched rather than inferred. The single-pane view
  // answers "what did this one do"; this answers "what are they doing to each other".
  //
  // WHY A SEPARATE POLL RATHER THAN THE SESSION STREAM. A locus turn runs in the server's session thread, and
  // subscribing nine panes to nine session streams would give one turn nine readers writing nine panes -- the
  // coupling the single-pane view was built to avoid. One request carries every visible transcript, so the
  // cost of watching more agents does not grow with how many are watched.

  const wall = {
    panes: [],          // locus names, "" for an empty slot. Length is the grid size.
    cols: 2,
    links: null,        // cross-agent events, newest last; null until the stream is wired
    poll: null,
    paused: false,
    dragFrom: -1,
  };

  function wallByName(name) { return locusByName(name); }

  function wallStateOf(name) {
    if (!name) return "empty";
    const l = wallByName(name);
    if (!l) return "gone";
    return l.running ? "working" : "idle";
  }

  // Panes are remembered so a reload does not lose the arrangement. localStorage rather than the server: this
  // is one browser's view of the machine, not a property of the machine, and two tabs may reasonably want
  // different walls.
  function wallSave() {
    try { localStorage.setItem("myriaxon.wall", JSON.stringify({ panes: wall.panes, cols: wall.cols })); }
    catch (err) { /* private mode, or a full quota: the wall still works, it just does not persist */ }
  }

  function wallLoad() {
    try {
      const saved = JSON.parse(localStorage.getItem("myriaxon.wall") || "null");
      if (saved && Array.isArray(saved.panes)) {
        wall.panes = saved.panes.slice(0, 9).map((n) => (typeof n === "string" ? n : ""));
        wall.cols = [1, 2, 3].includes(saved.cols) ? saved.cols : 2;
        return;
      }
    } catch (err) { /* corrupt entry: fall through to the default */ }
    wall.panes = [];
  }

  // The grid is always a full rectangle, because a wall with a ragged edge has no obvious place to drop a pane.
  function wallEnsureSize() {
    const needed = wall.cols * wall.cols;
    while (wall.panes.length < needed) wall.panes.push("");
    if (wall.panes.length > needed) wall.panes.length = needed;
  }

  function wallDefaultFill() {
    // First open: fill the panes with the loci that have something to say, so the room is not empty on arrival.
    const loci = ((state.config && state.config.loci) || {}).loci || [];
    const interesting = loci.filter((l) => l.running).concat(loci.filter((l) => !l.running));
    wall.panes = wall.panes.map((existing, i) => existing || (interesting[i] ? interesting[i].name : ""));
  }

  function wallRenderRoster() {
    const host = $("wallroster");
    if (!host) return;
    const loci = ((state.config && state.config.loci) || {}).loci || [];
    host.innerHTML = "";
    if (!loci.length) {
      host.innerHTML = `<span class="dim">No loci yet. Create one from the Loci page.</span>`;
      $("wallrosterhint").textContent = "";
      return;
    }
    const open = wall.panes.filter(Boolean).length;
    $("wallrosterhint").textContent = `${open} of ${wall.panes.length} panes used`;
    loci.forEach((locus) => {
      const chip = document.createElement("div");
      chip.className = "wall-chip" + (wall.panes.includes(locus.name) ? " on" : "");
      chip.draggable = true;
      chip.dataset.locus = locus.name;
      const state_ = locus.running ? "working" : "idle";
      chip.innerHTML = `<span class="pane-dot ${state_}"></span><span>${esc(locus.name)}</span>` +
        `<span class="dim">${locus.open_goals || 0}</span>`;
      // Drag into a pane, or click to drop it into the first free slot -- a drag is a nice way to arrange,
      // and a poor way to do the one thing everybody does first.
      chip.addEventListener("dragstart", (ev) => {
        wall.dragFrom = -1;
        ev.dataTransfer.setData("text/plain", "locus:" + locus.name);
        ev.dataTransfer.effectAllowed = "copy";
      });
      chip.addEventListener("click", () => {
        if (wall.panes.includes(locus.name)) return;
        const free = wall.panes.indexOf("");
        if (free === -1) { wallStatus("Every pane is taken. Drag one out, or raise the grid.", "warn"); return; }
        wall.panes[free] = locus.name;
        wallSave(); renderWall();
      });
      host.appendChild(chip);
    });
  }

  function paneTurn(turn, name) {
    const wrap = document.createElement("div");
    wrap.className = "pane-turn " + (turn.role === "user" ? "you" : "them");
    const who = document.createElement("div");
    who.className = "pane-who";
    who.textContent = turn.role === "user" ? "you" : name;
    const bubble = document.createElement("div");
    bubble.className = "pane-bubble";
    // textContent, not innerHTML. This is model output and file contents, and building markup from either is
    // how a transcript becomes a scripting vector.
    bubble.textContent = turn.text || "";
    wrap.append(who, bubble);
    return wrap;
  }

  function wallLinkLines(name) {
    // Cross-agent traffic for this pane, from the transparency stream's AGENTS layer. This is the "see their
    // communication together" half: a locus's own transcript shows what it said to a peer through a tool call
    // and not what the peer did about it, so the two halves only meet if something joins them.
    const links = wall.links;
    if (!links || !wallLinksOn()) return [];
    return links.filter((e) => e.locus === name || (e.detail && e.detail.member === name));
  }

  function wallLinksOn() { return $("wall-links") && $("wall-links").checked; }

  // ONE path for an incoming cross-agent event: the live stream calls it, and so does the diagnostic hook.
  // Two paths would mean the check exercised something the product does not run.
  function pushAgentEvent(payload) {
    if (!state.wallLinks) state.wallLinks = [];
    state.wallLinks.push(payload);
    if (state.wallLinks.length > 120) state.wallLinks.shift();
    wall.links = state.wallLinks;
    if ($("wallmodal").classList.contains("open") && wallLinksOn()) renderWall();
    return state.wallLinks.length;
  }

  // ------------------------------------------------------------------ saying when something is wrong
  //
  // WHY THIS EXISTS, and it is not defensive habit. A wall pane threw `TypeError: wall.linksOn is not a
  // function` inside `renderWall`'s own loop, so the panes were never appended: the room opened, looked
  // empty, and said nothing. The only account of it was an exception in the browser console, which the
  // person using the dashboard does not have open. A feature that fails silently is worse than one that
  // fails loudly, because the reader concludes the FEATURE is empty rather than BROKEN, and goes looking
  // for the problem in their own setup.
  //
  // So every panel here reports its own failures into the page. The role="alert" is deliberate: a screen
  // reader should hear this too, and a diagnostic only sighted users receive is half a diagnostic.

  function wallFail(what, err) {
    const detail = String((err && (err.stack || err.message)) || err || "unknown error");
    state.wallErrors = state.wallErrors || [];
    // Deduplicated by message: a per-pane failure in a 3x3 grid would otherwise print nine identical lines
    // and bury the one fact that matters.
    if (!state.wallErrors.some((e) => e.message === detail)) {
      state.wallErrors.push({ what, message: detail, at: Date.now() });
    }
    const host = $("wall-errors");
    if (host) {
      host.hidden = false;
      host.innerHTML = "";
      const head = document.createElement("div");
      head.className = "wall-error-head";
      head.textContent = `${state.wallErrors.length} problem(s) in the wall — this is a bug, not an empty room`;
      host.appendChild(head);
      state.wallErrors.slice(-4).forEach((entry) => {
        const row = document.createElement("div");
        row.className = "wall-error-row";
        // textContent: this is an exception message, and exception messages can contain anything at all --
        // including text read from a file that a tool just touched.
        row.textContent = `${entry.what}: ${entry.message.split("\n")[0]}`;
        row.title = entry.message;
        host.appendChild(row);
      });
    }
    if (typeof addNotice === "function") addNotice(`${what} failed — see the wall for the error`, "error");
    // Still to the console, because a developer with it open wants the stack.
    console.error(`[wall] ${what}`, err);
  }

  function wallClearErrors() {
    state.wallErrors = [];
    const host = $("wall-errors");
    if (host) { host.hidden = true; host.innerHTML = ""; }
  }

  // Runs `fn`, and on a throw reports it on the page instead of letting it vanish. Used for the render path
  // and for every async action, because those are the two places a silent failure hides.
  function wallGuard(what, fn) {
    try {
      return fn();
    } catch (err) {
      wallFail(what, err);
      return undefined;
    }
  }

  function renderWall() {
    const grid = $("wallgrid");
    if (!grid) return;
    // WRAPPED, so a bug in here is visible on the page. This is not hypothetical: a bad call inside this
    // function's loop meant the panes were never appended, and the wall opened empty and silent -- the
    // reader could only conclude the feature did nothing.
    return wallGuard("rendering the panes", () => renderWallInner());
  }

  function renderWallInner() {
    const grid = $("wallgrid");
    if (!grid) return;
    wallEnsureSize();
    grid.dataset.cols = String(wall.cols);
    grid.innerHTML = "";

    wall.panes.forEach((name, index) => {
      const pane = document.createElement("div");
      pane.className = "pane" + (name ? "" : " empty");
      pane.dataset.index = String(index);

      if (!name) {
        pane.innerHTML = `<div class="pane-hint">Empty.<br>Drag a locus here from the roster below,<br>
          or click one to place it.</div>`;
      } else {
        const locus = wallByName(name);
        const stateName = wallStateOf(name);
        const label = stateName === "working" ? "working" : stateName === "gone" ? "not found" : "idle";

        const bar = document.createElement("div");
        bar.className = "pane-bar";
        bar.draggable = true;
        bar.innerHTML = `<span class="pane-dot ${stateName === "working" ? "working" : stateName === "gone" ? "waiting" : ""}"></span>
          <span class="pane-name">${esc(name)}</span>
          <span class="pane-what">${esc(label)}${locus && locus.open_goals ? " · " + locus.open_goals + " open" : ""}</span>
          <span class="pane-actions">
            <button class="ghost small" data-act="run" title="Advance its next objective now">Run</button>
            <button class="ghost small" data-act="close" title="Remove this pane">✕</button>
          </span>`;
        bar.addEventListener("dragstart", (ev) => {
          wall.dragFrom = index;
          ev.dataTransfer.setData("text/plain", "pane:" + index);
          ev.dataTransfer.effectAllowed = "move";
          pane.classList.add("dragging");
        });
        bar.addEventListener("dragend", () => pane.classList.remove("dragging"));
        bar.querySelector('[data-act="close"]').onclick = (ev) => {
          ev.stopPropagation();
          wall.panes[index] = "";
          wallSave(); renderWall();
        };
        bar.querySelector('[data-act="run"]').onclick = async (ev) => {
          ev.stopPropagation();
          wallStatus(`running ${name}…`);
          try { await post("/api/loci", { action: "run", locus: name }); wallStatus(`${name}: started`); }
          catch (err) { wallStatus(`${name}: ${err.message || err}`, "error"); }
          refreshWallTranscripts();
        };
        pane.appendChild(bar);

        const body = document.createElement("div");
        body.className = "pane-body";
        body.dataset.paneFor = name;
        const turns = (state.wallTranscripts || {})[name] || [];
        if (!turns.length) {
          body.innerHTML = `<div class="dim" style="font-size:12px">Nothing said yet in this conversation.</div>`;
        } else {
          turns.forEach((turn) => body.appendChild(paneTurn(turn, name)));
        }
        wallLinkLines(name).forEach((event) => {
          const link = document.createElement("div");
          link.className = "pane-link";
          link.textContent = "⇄ " + (event.summary || "");
          body.appendChild(link);
        });
        pane.appendChild(body);

        const composer = document.createElement("form");
        composer.className = "pane-composer";
        const input = document.createElement("textarea");
        input.rows = 1;
        input.placeholder = `Message ${name}…`;
        const send = document.createElement("button");
        send.className = "primary";
        send.type = "submit";
        send.textContent = "Send";
        composer.append(input, send);
        composer.addEventListener("submit", async (ev) => {
          ev.preventDefault();
          const message = input.value.trim();
          if (!message) return;
          input.value = "";
          wallStatus(`sending to ${name}…`);
          try {
            const out = await post("/api/loci", { action: "run", locus: name, message });
            wallStatus(out.accepted ? `${name}: started` : `${name}: ${out.reason || "refused"}`,
                       out.accepted ? "" : "warn");
          } catch (err) { wallStatus(`${name}: ${err.message || err}`, "error"); }
          refreshWallTranscripts();
        });
        pane.appendChild(composer);
      }

      // A drop target says so BEFORE the drop. Without the highlight a drag is a guess, and the guess is
      // usually wrong in a 3x3 grid where the panes are the same size.
      pane.addEventListener("dragover", (ev) => { ev.preventDefault(); pane.classList.add("drop-target"); });
      pane.addEventListener("dragleave", () => pane.classList.remove("drop-target"));
      pane.addEventListener("drop", (ev) => {
        ev.preventDefault();
        pane.classList.remove("drop-target");
        const payload = ev.dataTransfer.getData("text/plain") || "";
        if (payload.startsWith("locus:")) {
          const incoming = payload.slice(6);
          const existing = wall.panes.indexOf(incoming);
          if (existing !== -1) wall.panes[existing] = wall.panes[index];   // move, not duplicate
          wall.panes[index] = incoming;
        } else if (payload.startsWith("pane:")) {
          const from = Number(payload.slice(5));
          // SWAP rather than insert. An insert renumbers every pane after the drop, so the arrangement the
          // user was looking at changes everywhere except where they dropped -- in a 3x3 grid that reads as
          // the wall shuffling itself.
          const held = wall.panes[index];
          wall.panes[index] = wall.panes[from];
          wall.panes[from] = held;
        }
        wallSave(); renderWall(); refreshWallTranscripts();
      });

      grid.appendChild(pane);
    });

    wallRenderRoster();
    document.querySelectorAll("[data-wall-cols]").forEach((button) => {
      button.setAttribute("aria-pressed", String(Number(button.dataset.wallCols) === wall.cols));
    });
    $("wallhint").textContent = `${wall.panes.filter(Boolean).length} of ${wall.panes.length} panes · ${wall.cols} across`;
    const busy = wall.panes.filter((n) => wallStateOf(n) === "working").length;
    setBadge("wallbadge", busy ? String(busy) : "");
  }

  function wallStatus(text, tone) {
    const el = $("wallstatus");
    if (!el) return;
    el.textContent = text;
    el.style.color = tone === "error" ? "var(--err)" : tone === "warn" ? "var(--warn)" : "";
  }

  async function refreshWallTranscripts() {
    const names = wall.panes.filter(Boolean);
    if (!names.length) { state.wallTranscripts = {}; renderWall(); return; }
    try {
      const data = await get(`/api/loci?transcripts=${encodeURIComponent(names.join(","))}`);
      if (data && data.loci) state.config.loci = data;
      state.wallTranscripts = (data && data.transcripts) || {};
      // A successful read clears the failure report: leaving a stale error on screen after the cause is gone
      // teaches the reader to ignore the box, which is exactly what it must not become.
      wallClearErrors();
      renderWall();
      wallSchedule();
    } catch (err) {
      wallFail("reading the conversations", err);
      wallStatus(`could not read transcripts: ${err.message || err}`, "error");
    }
  }

  // One timer for the whole wall, and only while something is actually running. Nine panes each polling would
  // be nine requests per interval for one screen; this is one. A pane that is idle costs nothing, which is why
  // the check is on `working` rather than on "the wall is open".
  function wallSchedule() {
    if (wall.poll) { clearTimeout(wall.poll); wall.poll = null; }
    if (wall.paused || !$("wallmodal").classList.contains("open")) return;
    if (!wall.panes.some((n) => wallStateOf(n) === "working")) return;
    wall.poll = setTimeout(refreshWallTranscripts, 1500);
  }

  function wireWallLinks() {
    // Cross-agent events come from the transparency feed rather than a second mechanism, because that feed is
    // already the one place every tool call passes through. Filtered to the AGENTS layer: a pane wall exists
    // to show coordination, and the actions layer would bury it in file reads.
    if (state.wallLinkWired) return;
    state.wallLinkWired = true;
    state.wallLinks = [];
    const es = new EventSource("/api/transparency/stream");
    es.onmessage = (ev) => {
      let payload; try { payload = JSON.parse(ev.data); } catch { return; }
      if (payload.type === "dial" || payload.layer !== 6) return;
      pushAgentEvent(payload);
    };
  }

  $("wallbtn").onclick = () => {
    setMenu(false);
    $("wallmodal").classList.add("open");
    wallGuard("opening the wall", () => {
      wallLoad();
      wallEnsureSize();
      wallDefaultFill();
      wireWallLinks();
      wall.links = state.wallLinks || [];
      renderWall();
      refreshWallTranscripts();
    });
  };
  $("wallclose").onclick = () => {
    if (wall.poll) { clearTimeout(wall.poll); wall.poll = null; }
    $("wallmodal").classList.remove("open");
  };
  $("wallmodal").addEventListener("click", (ev) => {
    if (ev.target === $("wallmodal")) $("wallclose").click();
  });
  $("wallrefresh").onclick = refreshWallTranscripts;
  $("wallclear").onclick = () => { wall.panes = wall.panes.map(() => ""); wallSave(); renderWall(); };
  $("wall-live").onclick = () => {
    wall.paused = !wall.paused;
    $("wall-live").textContent = wall.paused ? "Resume" : "Pause";
    wallStatus(wall.paused ? "paused" : "live");
    if (!wall.paused) refreshWallTranscripts();
  };
  $("wall-links").onchange = () => renderWall();
  document.querySelectorAll("[data-wall-cols]").forEach((button) => {
    button.onclick = () => {
      wall.cols = Number(button.dataset.wallCols);
      // Growing the grid adds empty panes rather than dropping the ones that no longer fit: a pane the user
      // placed and then lost to a layout change is work thrown away by a control that was meant to be a view.
      wallEnsureSize();
      wallSave(); renderWall();
    };
  });

  // ---- diagnostics ------------------------------------------------------------------------------
  //
  // The wall's internals are exposed on `window` for one reason: so it can be DRIVEN and checked by a real
  // browser, rather than validated by reading its markup. That distinction is not academic here -- the first
  // version of this room shipped a call to a function that did not exist, and every static check passed while
  // the room rendered nothing at all.
  //
  // A test hook is also a debugging hook: `myriaxonWall.panes` and `.errors` in a console answer "why is it
  // empty" without a rebuild.
  window.myriaxonWall = {
    state: wall,
    render: () => renderWall(),
    refresh: () => refreshWallTranscripts(),
    errors: () => (state.wallErrors || []).slice(),
    setPanes: (names) => { wall.panes = names.slice(0, 9); wallEnsureSize(); wallSave(); renderWall(); },
    linksOn: () => wallLinksOn(),
    // Feeds one event through the SAME path the live stream uses, so a check exercises the real filter rather
    // than a re-implementation of it. A hook that bypassed the filter would prove nothing about the filter.
    pushEvent: (event) => pushAgentEvent(event),
    // The filter's own decision, exposed so a check can assert WHY a line did or did not render.
    isAgentEvent: (event) => !!event && event.layer === 6,
  };

  // A GLOBAL TRAP, so an exception thrown from anywhere the user can reach lands on the page and not only in
  // a console they do not have open. `error` covers synchronous throws and resource failures;
  // `unhandledrejection` covers a rejected promise, which is how most async UI work fails.
  window.addEventListener("error", (event) => {
    if (event && event.message) wallFail("uncaught error", event.error || event.message);
  });
  window.addEventListener("unhandledrejection", (event) => {
    wallFail("unhandled promise rejection", (event && event.reason) || "no reason given");
  });

  $("locuscreate").onclick = createLocus;
  $("locisnew").onclick = () => {
    // Opening the new-locus form also opens the gallery above it. They answer the same question --
    // "how do I get one of these" -- and a blank form with no suggestions is the worse half of it.
    $("locistemplates").hidden = false;
    const form = $("locisform");
    form.hidden = !form.hidden;
    if (!form.hidden) { $("locusname").focus(); form.scrollIntoView({ block: "nearest" }); }
  };
  $("locistoggletemplates").onclick = () => {
    const gallery = $("locistemplates");
    gallery.hidden = !gallery.hidden;
    if (!gallery.hidden) gallery.scrollIntoView({ block: "nearest" });
  };
  // The gallery and the new-locus form start collapsed: a page that opens with a gallery and a form
  // stacked above the conversation buries the thing the user came for. Both are one click away.
  $("locistemplates").hidden = true;
  $("lc-enable").onclick = () => locusToggle("enabled", !(locusChat.locus || {}).enabled);
  $("lc-proactive").onclick = () => locusToggle("proactive", !(locusChat.locus || {}).proactive);
  // Clicking grants or withdraws self-direction. No confirmation dialog, deliberately: the state is
  // reversible with the same click, it is shown on the button itself, and the boundary is displayed
  // beside it. A dialog for a reversible toggle trains people to dismiss dialogs.
  $("lc-autonomy").onclick = () => {
    const now = !!(locusChat.locus || {}).self_directed;
    locusToggle("autonomy", now ? "assisted" : "self_directed");
  };
  $("lc-run").onclick = () => runLocusHere("");
  $("lc-stop").onclick = stopLocus;
  $("lc-refresh").onclick = () => loadLocusTranscript();
  $("lc-delete").onclick = locusDelete;
  $("locuscomposer").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const input = $("locusmessage");
    const text = (input.value || "").trim();
    if (!text) return;
    input.value = "";
    sendToLocus(text);
  });
  $("locusmessage").addEventListener("keydown", (ev) => {
    // Enter sends, Shift+Enter is a newline -- the same contract as the main composer.
    if (ev.key === "Enter" && !ev.shiftKey) {
      ev.preventDefault();
      $("locuscomposer").requestSubmit();
    }
  });
  setLocusPaneVisible(false);

  // ---------- file explorer + diff review ----------
  // Browsing uses /api/files and /api/file, reviewing uses /api/git and /api/git/diff. Diff content is
  // arbitrary file text, so every line is written with textContent rather than as markup: building
  // HTML from a file's contents is how a repository file becomes a scripting vector.
  const codeState = { tab: "files", path: "", viewing: null, staged: false };

  function codeShow(which) {
    $("codepane-files").style.display = which === "files" && !codeState.viewing ? "block" : "none";
    $("codepane-changes").style.display = which === "changes" && !codeState.viewing ? "block" : "none";
    $("codeviewer").style.display = codeState.viewing ? "block" : "none";
    document.querySelectorAll("[data-codetab]").forEach((b) =>
      b.classList.toggle("active", b.dataset.codetab === which));
  }

  function fileRow(name, opts) {
    const row = document.createElement("div");
    row.className = "filerow";
    const icon = document.createElement("span");
    icon.textContent = opts.icon || "";
    const label = document.createElement("span");
    label.className = "fname";
    label.textContent = name;
    row.append(icon, label);
    if (opts.meta) {
      const meta = document.createElement("span");
      meta.className = "fmeta";
      meta.textContent = opts.meta;
      row.appendChild(meta);
    }
    if (opts.onclick) row.onclick = opts.onclick;
    return row;
  }

  async function loadDir(relPath) {
    try {
      const out = await get(`/api/files?path=${encodeURIComponent(relPath || "")}`);
      codeState.path = relPath || "";
      $("codepath").textContent = "workspace / " + (relPath || ".");
      const list = $("codelist");
      list.innerHTML = "";
      if (relPath) {
        const up = relPath.includes("/") ? relPath.slice(0, relPath.lastIndexOf("/")) : "";
        list.appendChild(fileRow("..", { icon: "📁", meta: "up", onclick: () => loadDir(up) }));
      }
      (out.files || []).forEach((entry) => {
        const childPath = entry.path || (relPath ? `${relPath}/${entry.name}` : entry.name);
        if (entry.is_dir) {
          list.appendChild(fileRow(entry.name + "/", { icon: "📁", meta: "dir", onclick: () => loadDir(childPath) }));
        } else {
          const kb = entry.size > 1024 ? `${(entry.size / 1024).toFixed(1)} KB` : `${entry.size} B`;
          list.appendChild(fileRow(entry.name, {
            icon: /\.(png|jpe?g|gif|webp)$/i.test(entry.name) ? "🖼" : "📄",
            meta: kb,
            onclick: () => openFile(childPath),
          }));
        }
      });
      if (!(out.files || []).length) {
        const empty = document.createElement("div");
        empty.className = "muted";
        empty.textContent = "empty directory";
        list.appendChild(empty);
      }
    } catch (err) { addNotice("could not list files: " + err.message, "error"); }
  }

  async function openFile(relPath) {
    codeState.viewing = { kind: "file", path: relPath };
    $("codetitle").textContent = relPath;
    $("codestagedtoggle").style.display = "none";
    codeShow(codeState.tab);
    try {
      const out = await get(`/api/file?path=${encodeURIComponent(relPath)}`);
      const body = $("codebody");
      body.innerHTML = "";
      if (out.too_large) {
        body.textContent = `file is too large to display (${out.size} bytes)`;
      } else {
        const lines = String(out.text || "").split("\n");
        lines.forEach((text, index) => {
          const row = document.createElement("div");
          row.className = "cl";
          const num = document.createElement("span");
          num.className = "ln";
          num.textContent = String(index + 1);
          const content = document.createElement("span");
          content.className = "tx";
          content.textContent = text;
          row.append(num, content);
          body.appendChild(row);
        });
      }
    } catch (err) { $("codebody").textContent = "could not read the file: " + err.message; }
  }

  async function openDiff(relPath, staged) {
    codeState.viewing = { kind: "diff", path: relPath };
    codeState.staged = !!staged;
    $("codetitle").textContent = (relPath ? relPath : "all changes") + (staged ? "  (staged)" : "");
    $("codestagedtoggle").style.display = "inline-block";
    $("codestagedtoggle").textContent = staged ? "unstaged" : "staged";
    codeShow("changes");
    try {
      const out = await get(`/api/git/diff?path=${encodeURIComponent(relPath)}&staged=${staged ? 1 : 0}`);
      const body = $("codebody");
      body.innerHTML = "";
      if (out.error) { body.textContent = out.error; return; }
      if (!(out.hunks || []).length) {
        body.textContent = out.empty === false ? "" : "no changes to show";
        if (!out.diff) body.textContent = "no changes to show";
        return;
      }
      (out.hunks || []).forEach((hunk) => {
        if (hunk.header) {
          const head = document.createElement("div");
          head.className = "cl hunk";
          head.textContent = hunk.header;
          body.appendChild(head);
        }
        (hunk.lines || []).forEach((line) => {
          const row = document.createElement("div");
          row.className = "cl " + (line.type === "add" ? "add" : line.type === "del" ? "del"
            : line.type === "meta" ? "meta" : "");
          const num = document.createElement("span");
          num.className = "ln";
          num.textContent = line.new ?? line.old ?? "";
          const content = document.createElement("span");
          content.className = "tx";
          content.textContent = line.text;
          row.append(num, content);
          body.appendChild(row);
        });
      });
      if (out.truncated) {
        const note = document.createElement("div");
        note.className = "cl meta";
        note.textContent = "… diff truncated for display";
        body.appendChild(note);
      }
    } catch (err) { $("codebody").textContent = "could not load the diff: " + err.message; }
  }

  async function loadChanges() {
    try {
      const out = await get("/api/git");
      const list = $("codechanges");
      list.innerHTML = "";
      $("codebranch").textContent = out.is_repo
        ? `${out.branch || "(no branch)"} · ${(out.files || []).length} changed`
        : "not a git repository";
      $("codecount").textContent = out.is_repo && (out.files || []).length ? `(${out.files.length})` : "";
      if (!out.is_repo) {
        const note = document.createElement("div");
        note.className = "muted";
        note.textContent = "This workspace is not a git repository, so there are no changes to review.";
        list.appendChild(note);
        return;
      }
      if (!(out.files || []).length) {
        const note = document.createElement("div");
        note.className = "muted";
        note.textContent = "Working tree clean.";
        list.appendChild(note);
        return;
      }
      (out.files || []).forEach((entry) => {
        const row = document.createElement("div");
        row.className = "filerow";
        const code = document.createElement("span");
        code.className = "fcode " + (entry.untracked ? "untracked" : entry.code === "D" ? "del"
          : entry.code === "M" ? "mod" : "add");
        code.textContent = entry.code;
        const name = document.createElement("span");
        name.className = "fname";
        name.textContent = entry.path;
        const meta = document.createElement("span");
        meta.className = "fmeta";
        meta.textContent = entry.label + (entry.staged ? " · staged" : "");
        row.append(code, name, meta);
        row.onclick = () => openDiff(entry.path, entry.staged && !entry.unstaged);
        list.appendChild(row);
      });
    } catch (err) { addNotice("could not read git status: " + err.message, "error"); }
  }

  document.querySelectorAll("[data-codetab]").forEach((button) => {
    button.onclick = () => {
      codeState.tab = button.dataset.codetab;
      codeState.viewing = null;
      codeShow(codeState.tab);
      if (codeState.tab === "changes") loadChanges();
    };
  });
  $("codeback").onclick = () => {
    codeState.viewing = null;
    codeShow(codeState.tab);
    if (codeState.tab === "changes") loadChanges();
  };
  $("codestagedtoggle").onclick = () => {
    if (codeState.viewing && codeState.viewing.kind === "diff") {
      openDiff(codeState.viewing.path, !codeState.staged);
    }
  };
  $("coderefresh").onclick = () => {
    if (codeState.tab === "changes") loadChanges();
    else loadDir(codeState.path);
  };
  $("codebtn").onclick = () => {
    setMenu(false);
    codeState.viewing = null;
    codeShow(codeState.tab);
    $("codemodal").classList.add("open");
    if (codeState.tab === "changes") loadChanges();
    else loadDir(codeState.path);
  };
  $("codeclose").onclick = () => $("codemodal").classList.remove("open");
  $("codemodal").addEventListener("click", (ev) => { if (ev.target === $("codemodal")) $("codemodal").classList.remove("open"); });

  // ---------- mission control ----------
  // A read-only operational view over the same state the chat uses. It reads /api/mission-control,
  // which gathers everything server-side; the page never computes a number it displays, so the
  // figure on screen and the figure in the API can never disagree.
  const mc = { view: "mission", data: null, traceFilter: "all", timer: null };

  function mcShow(view) {
    mc.view = view;
    const onMission = view === "mission";
    $("mc").classList.toggle("on", onMission);
    $("chat").style.display = onMission ? "none" : "";
    $("trajectory").style.display = "none";
    $("composer").style.display = onMission ? "none" : "";
    document.querySelectorAll("#nav button").forEach((button) => {
      button.toggleAttribute("aria-current", false);
      if (button.dataset.view === view) button.setAttribute("aria-current", "page");
    });
    if (onMission) loadMission();
  }

  // Rail entries that open a dialog name the button which already owns that dialog. It is a map
  // rather than an inline expression so that a missing entry is a visible omission in one place --
  // and so `ui_check.py` can assert that every data-ui in the markup appears here. Without that
  // check, an unmapped entry silently does nothing, which is exactly what shipped once.
  const RAIL_DIALOGS = {
    loci: "locisbtn",
    wall: "wallbtn",
    code: "codebtn",
    mcp: "mcpbtn",
    plugins: "plugbtn",
    rules: "rulesbtn",
    messaging: "msgbtn",
    settings: "settingsbtn",
  };

  $("nav").addEventListener("click", (ev) => {
    const button = ev.target.closest("button");
    if (!button) return;
    const ui = button.dataset.ui;
    if (ui) {
      // Entries that open a dialog reuse the buttons that already own those dialogs, so there is
      // one implementation of each panel rather than a second one behind the rail.
      const opener = RAIL_DIALOGS[ui];
      if (opener && $(opener)) {
        $(opener).click();
      } else {
        // A rail entry naming a dialog that does not exist would be a dead button. Say so rather
        // than appearing to do nothing.
        addNotice(`${ui} has no panel in this build`, "warning");
      }
      return;
    }
    const view = button.dataset.view || "chat";
    if (view === "approvals") {
      // Approvals is a section of the mission view, not a separate page; scrolling to it keeps one
      // source of truth for what is pending.
      mc.approvalsFocus = true;
      mcShow("mission");
      const target = $("mc-approvals");
      if (target) target.scrollIntoView({ block: "center", behavior: "smooth" });
      return;
    }
    mcShow(view);
  });

  function mcMeter(label, value, sub, fraction, colour) {
    const bar = typeof fraction === "number"
      ? `<div class="bar"><i style="width:${Math.max(0, Math.min(100, fraction * 100))}%${
          colour ? ";background:" + colour : ""}"></i></div>`
      : "";
    return `<div class="meter"><div class="mlabel">${esc(label)}</div>
      <div class="mvalue">${esc(String(value))}</div>
      ${sub ? `<div class="msub">${esc(sub)}</div>` : ""}${bar}</div>`;
  }

  function mcDuration(seconds) {
    const s = Math.max(0, Math.round(seconds || 0));
    if (s < 60) return s + "s";
    if (s < 3600) return Math.floor(s / 60) + "m " + (s % 60) + "s";
    return Math.floor(s / 3600) + "h " + Math.floor((s % 3600) / 60) + "m";
  }

  function mcTime(epoch) {
    if (!epoch) return "—";
    return new Date(epoch * 1000).toLocaleTimeString();
  }

  function renderCore(health) {
    // The diagram is drawn from the health list, so it can never show a connection the list does
    // not. Nodes are placed on a ring and coloured by state; the middle is the mark.
    const box = $("mc-core");
    // Every item, not the first ten. The cap was silent and the note beside the diagram said
    // "12 checked" while ten nodes were drawn -- so the ring disagreed with its own label. Twelve
    // nodes on a ring are still legible; if the health list ever grows past what a ring can carry,
    // the fix is a second ring, not dropping nodes without saying so.
    const items = health.items || [];
    if (!items.length) {
      box.innerHTML = `<svg viewBox="0 0 132 132"><circle class="cring" cx="66" cy="66" r="52"/></svg>`;
      return;
    }
    const colours = { ok: "var(--ok)", warn: "var(--warn)", error: "var(--err)", off: "var(--line-2)" };
    const spokes = items.map((item, index) => {
      const angle = (index / items.length) * Math.PI * 2 - Math.PI / 2;
      const x = 66 + Math.cos(angle) * 46;
      const y = 66 + Math.sin(angle) * 46;
      return `<line class="cspoke" x1="66" y1="66" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}"/>`;
    }).join("");
    const nodes = items.map((item, index) => {
      const angle = (index / items.length) * Math.PI * 2 - Math.PI / 2;
      const x = 66 + Math.cos(angle) * 46;
      const y = 66 + Math.sin(angle) * 46;
      return `<circle class="cnode ${esc(item.state)}" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="7"
        style="stroke:${colours[item.state] || "var(--line-2)"}"><title>${esc(item.label)}: ${esc(item.detail)}</title></circle>`;
    }).join("");
    box.innerHTML = `<svg viewBox="0 0 132 132" role="img" aria-label="${esc(health.summary || "")}">
      <circle class="cring" cx="66" cy="66" r="52"/>
      <circle class="cring" cx="66" cy="66" r="30"/>
      ${spokes}${nodes}
      <g transform="translate(48 48) scale(0.18)" class="coremark">
        <g fill="currentColor">
          <polygon points="100,6 104.5,68 100,80 95.5,68"/>
          <polygon points="100,6 104.5,68 100,80 95.5,68" transform="rotate(90 100 100)"/>
          <polygon points="100,6 104.5,68 100,80 95.5,68" transform="rotate(180 100 100)"/>
          <polygon points="100,6 104.5,68 100,80 95.5,68" transform="rotate(270 100 100)"/>
          <polygon points="100,36 103,70 100,80 97,70" transform="rotate(45 100 100)"/>
          <polygon points="100,36 103,70 100,80 97,70" transform="rotate(135 100 100)"/>
          <polygon points="100,36 103,70 100,80 97,70" transform="rotate(225 100 100)"/>
          <polygon points="100,36 103,70 100,80 97,70" transform="rotate(315 100 100)"/>
          <circle cx="100" cy="100" r="12"/>
        </g>
        <circle cx="100" cy="100" r="8.5" fill="var(--panel)"/>
        <circle class="core-locus" cx="100" cy="100" r="4"/>
      </g>
    </svg>`;
  }

  function renderMission(data) {
    mc.data = data;
    const usage = data.usage || {};
    const counts = data.counts || {};
    const health = data.health || {};

    $("mc-summary").textContent = health.summary || "";
    $("mc-updated").textContent = "updated " + mcTime(data.generated_at);

    renderCore(health);

    const total = usage.total_tokens || 0;
    $("mc-meters").innerHTML = [
      mcMeter("Tokens", total.toLocaleString(), `${(usage.input_tokens || 0).toLocaleString()} in · ${(usage.output_tokens || 0).toLocaleString()} out`),
      mcMeter("Requests", (usage.requests || 0).toLocaleString(), `${usage.turns || 0} turns · ${usage.tools_called || 0} tools`),
      mcMeter("Sessions", counts.sessions || 0, `${usage.errors || 0} error(s)`),
      mcMeter("Loci", counts.loci || 0, `${counts.open_goals || 0} open objective(s)`),
      mcMeter("Uptime", mcDuration(usage.started_at ? (data.generated_at - usage.started_at) : 0), "this process"),
    ].join("");

    // approvals
    const approvals = data.approvals || [];
    $("mc-approval-count").textContent = String(approvals.length);
    // The rail counters are driven from the mission payload, which is where these numbers actually
    // exist. They used to read `config.runs`, a key `config_payload()` never sends: the Sessions
    // counter was therefore always blank, and `navApprovals` was never written at all -- so the rail
    // showed no counter while Mission control displayed "Waiting on you 1" on the same screen.
    setBadge("navApprovals", approvals.length ? String(approvals.length) : "");
    setBadge("navSessions", counts.sessions ? String(counts.sessions) : "");
    $("mc-approvals").innerHTML = approvals.length
      ? approvals.map((a) => `<div class="approval"><p>${esc(a.what)}</p>
          <div class="ameta">${esc(a.why)}</div>
          <div class="arow">
            <button class="ghost small" data-approve="${esc(a.id)}" data-locus="${esc(a.locus || "")}">Open</button>
          </div></div>`).join("")
      : `<p class="mempty">Nothing waiting. An objective a locus cannot finish without you shows up here.</p>`;
    $("mc-approvals").querySelectorAll("[data-approve]").forEach((button) => {
      // The id was rendered into the button and then thrown away, so every "Open" did the same thing
      // regardless of which approval it belonged to: clicking Open on a blocked objective belonging to
      // "cowork" opened the Loci dialog with nothing selected, leaving the user to find the locus by eye.
      //
      // The target comes from `a.locus`, which the payload already carries, rather than from parsing the
      // id -- the id is `goal:<locus id>:<goal id>`, so its last segment is the GOAL and using it as a
      // locus name would silently match nothing.
      button.onclick = () => {
        const target = button.dataset.locus || "";
        $("locisbtn").click();
        if (!target) return;
        // The panel re-renders from the server reply, so the scroll has to wait for that render
        // rather than running against the previous one -- which is why the first version of this
        // scrolled to an empty list.
        mc.approvalsFocus = true;
        setTimeout(() => {
          const card = Array.from($("locislist").querySelectorAll(".locusrow"))
            .find((element) => element.dataset.locusname === target);
          if (!card) return;
          card.scrollIntoView({ block: "center", behavior: "smooth" });
          card.classList.add("aimed");
          setTimeout(() => card.classList.remove("aimed"), 1800);
        }, 150);
      };
    });

    // connections
    const items = health.items || [];
    $("mc-health-note").textContent = items.length ? `${items.length} checked` : "";
    $("mc-health").innerHTML = items.length
      ? items.map((item) => `<div class="hitem ${esc(item.state)}">
          <span class="hdot"></span>
          <span class="hmain"><span class="hlabel">${esc(item.label)}</span>
          <span class="hdetail" title="${esc(item.detail)}">${esc(item.detail)}</span></span>
        </div>`).join("")
      : `<p class="mempty">No connections configured yet. Run <code>myriaxon auth</code> to add a provider.</p>`;

    // runs
    const runs = data.runs || [];
    $("mc-runs-note").textContent = runs.length ? `${runs.length}` : "";
    $("mc-runs").innerHTML = runs.length
      ? runs.map((run) => {
          const tags = [
            run.kind === "locus" ? `<span class="mtag locus">${esc(run.locus || "locus")}</span>` : "",
            run.busy ? `<span class="mtag live">running</span>` : "",
            run.status === "error" ? `<span class="mtag bad">error</span>` : "",
            `<span class="mtag">${esc(run.mode || "")}</span>`,
          ].join("");
          const bar = typeof run.progress === "number"
            ? `<div class="bar"><i style="width:${Math.round(run.progress * 100)}%"></i></div>` : "";
          return `<div class="runrow">
            <div class="rtitle"><span class="locus${run.busy ? "" : " off"}"></span><span>${esc(run.title || run.id)}</span></div>
            <div class="rmeta">${tags}<span>${esc(run.model || "")}</span>
              <span>${run.turns || 0} turn(s)</span><span>${esc(mcDuration(run.elapsed_s))}</span></div>
            ${bar}
            <div class="ractions"><button class="ghost small" data-openrun="${esc(run.id)}">Open</button></div>
          </div>`;
        }).join("")
      : `<p class="mempty">No sessions yet — start one from the composer.</p>`;
    $("mc-runs").querySelectorAll("[data-openrun]").forEach((button) => {
      button.onclick = async () => {
        mcShow("chat");
        await attach(button.dataset.openrun);
      };
    });

    // schedules — the same loci data the Loci panel uses
    const schedules = (data.schedules || []).filter((s) => s.enabled);
    $("mc-schedules").innerHTML = schedules.length
      ? schedules.map((s) => {
          const when = !s.proactive ? "on demand"
            : s.due_now ? "due now"
            : "in " + mcDuration(s.seconds_until_due);
          return `<li><div>${esc(s.locus)}<small>${esc(s.role)} · ${s.open_goals} open</small></div>
            <span class="mtag${s.due_now ? " live" : ""}">${esc(when)}</span></li>`;
        }).join("")
      : `<li><p class="mempty">No loci yet. A locus keeps a role and objectives across sessions and can
         work on its own interval — create one from Loci in the rail.</p></li>`;

    // routing
    const routing = data.routing || [];
    $("mc-routebar").innerHTML = routing.map((r, i) =>
      `<i style="width:${Math.max(2, Math.round((r.share || 0) * 100))}%;opacity:${(1 - i * 0.22).toFixed(2)}"></i>`).join("");
    $("mc-routing").innerHTML = routing.length
      ? routing.map((r) => `<li><span class="sw" style="opacity:${Math.max(0.25, 1 - routing.indexOf(r) * 0.22)}"></span>
          <span>${esc(r.model)}</span><span class="pct">${(r.requests || 0)}</span>
          <span class="pct">${Math.round((r.share || 0) * 100)}%</span></li>`).join("")
      : `<li><span class="mempty">No requests yet this process.</span></li>`;

    renderTrace();

    // memory
    const memory = data.memory || {};
    $("mc-mem-note").textContent = memory.sessions_indexed
      ? `${memory.sessions_indexed} project transcript(s) indexed for search.`
      : "Nothing indexed yet — the store fills as sessions end.";
    $("mc-memory").innerHTML = (memory.recent || []).length
      ? memory.recent.map((m) => `<li>${esc(m.snippet || "")}<small>${esc(m.project || "")} · ${esc(mcTime(m.when))}</small></li>`).join("")
      : `<li class="mempty">No past sessions recorded.</li>`;

    // skills
    const skills = data.skills || [];
    $("mc-skills-note").textContent = skills.length
      ? `${skills.length} available to the agent.`
      : "None yet. The agent can save one with save_skill when it finds a reusable approach.";
    $("mc-skills").innerHTML = skills.length
      ? skills.map((s) => `<span class="skillchip"><b>${esc(s.name)}</b> <span class="faint">· ${esc(s.scope)}</span></span>`).join("")
      : "";
  }

  function renderTrace() {
    const entries = ((mc.data || {}).trace) || [];
    const filter = mc.traceFilter;
    const shown = entries.filter((e) => filter === "all" || e.kind === filter ||
      (filter === "warn" && e.kind === "error"));
    $("mc-trace").innerHTML = shown.length
      ? shown.map((e) => `<li><span class="tw">${esc(new Date((e.at || 0) * 1000).toTimeString().slice(0, 8))}</span>
          <span class="ts ${esc(e.kind)}">${esc(e.source || "")}</span>
          <span>${esc(e.text || "")}</span></li>`).join("")
      : `<li><span class="tw"></span><span class="ts"></span>
          <span class="mempty">Nothing recorded yet this session.</span></li>`;
  }

  $("mc-tracefilter").addEventListener("click", (ev) => {
    const button = ev.target.closest("button");
    if (!button) return;
    mc.traceFilter = button.dataset.f;
    $("mc-tracefilter").querySelectorAll("button").forEach((b) =>
      b.setAttribute("aria-pressed", String(b === button)));
    renderTrace();
  });

  async function loadMission() {
    try {
      const data = await api("/api/mission-control");
      if (data.error) {
        $("mc-summary").textContent = "unavailable: " + data.error;
        return;
      }
      renderMission(data);
    } catch (err) {
      $("mc-summary").textContent = "could not read state: " + err.message;
    }
  }
  $("mc-refresh").onclick = loadMission;
  $("mc-opendots").onclick = () => $("locisbtn").click();

  // Poll only while the view is visible: a dashboard left open on the chat tab should not keep
  // asking the server for numbers nobody is looking at.
  setInterval(() => { if (mc.view === "mission" && !document.hidden) loadMission(); }, 5000);

  // ---------- the startup vendor choice ----------
  // Offered when neither gateway is ready -- no saved choice, or the one in use has no key. The key
  // is asked for HERE rather than at the first failed turn, because a missing DeepSeek key otherwise
  // surfaces as a 401 in the middle of the user's first real task, naming an HTTP status instead of
  // the missing credential.
  const VENDORS = [
    { id: "deepseek", name: "DeepSeek", sub: "api.deepseek.com · DeepSeek's own API" },
    { id: "netra", name: "Netra", sub: "api.netraruntime.com · gateway for the same models" },
  ];
  const vendorState = { picked: "", state: {} };

  function renderVendorPicker() {
    const box = $("vendpick");
    box.innerHTML = "";
    VENDORS.forEach((vendor) => {
      const ready = (vendorState.state[vendor.id] || {}).has_key;
      const card = document.createElement("button");
      card.type = "button";
      card.className = "vendcard";
      card.setAttribute("aria-pressed", String(vendorState.picked === vendor.id));
      card.innerHTML = `<span class="vcname">${esc(vendor.name)}</span>` +
                       `<span class="vcsub">${esc(vendor.sub)}</span>` +
                       `<span class="vcstate ${ready ? "ready" : "needs"}">` +
                       `${ready ? "key ready" : "needs an API key"}</span>`;
      card.onclick = () => {
        vendorState.picked = vendor.id;
        renderVendorPicker();
      };
      box.appendChild(card);
    });
    const chosen = vendorState.picked;
    const ready = chosen && (vendorState.state[chosen] || {}).has_key;
    // The key field appears only for a gateway that has none, so a prepared machine is never asked
    // for a credential it already holds.
    $("vendkeyfield").hidden = !chosen || ready;
    if (chosen && !ready) {
      const label = VENDORS.find((v) => v.id === chosen);
      $("vendkeylabel").textContent = `${label ? label.name : chosen} API key`;
      $("vendkeyhint").textContent = "Stored in your Myriaxon config, never in this page.";
      $("vendkey").focus();
    }
    $("vendnote").textContent = chosen
      ? (ready ? `${chosen} is ready.` : "")
      : "Choose one to continue.";
    $("vendsave").disabled = !chosen;
  }

  async function saveVendorChoice() {
    if (!vendorState.picked) return;
    const ready = (vendorState.state[vendorState.picked] || {}).has_key;
    const key = ($("vendkey").value || "").trim();
    if (!ready && !key) { $("vendnote").textContent = "Paste the key, or press Later."; return; }
    $("vendsave").disabled = true;
    $("vendnote").textContent = "checking…";
    try {
      const out = await post("/api/vendor", { provider: vendorState.picked, api_key: key });
      if (out.ok === false) {
        $("vendnote").textContent = out.message || "that did not work";
        $("vendsave").disabled = false;
        return;
      }
      $("vendkey").value = "";
      state.config = out.config || state.config;
      vendorState.state = (state.config && state.config.vendor_keys) || vendorState.state;
      $("provider").textContent = out.provider + ":" + out.model;
      populateVendors();
      setModelOptions(out.model);
      if (state.session) {
        // The running session still holds a client for the old provider, so it is re-synced rather
        // than left pointing at the previous host.
        try { syncSession({ provider: out.provider, model: out.model }); } catch (e) { /* ignore */ }
      }
      $("vendormodal").classList.remove("open");
      addNotice(`using ${out.provider}:${out.model}`, "success");
      if (out.message) addNotice(out.message, "warning");
    } catch (err) {
      $("vendnote").textContent = "could not save: " + err.message;
      $("vendsave").disabled = false;
    }
  }

  function maybeAskVendor() {
    const cfg = state.config || {};
    const keys = cfg.vendor_keys || {};
    vendorState.state = keys;
    const current = cfg.provider;
    const currentReady = (keys[current] || {}).has_key;
    // Only the two DeepSeek gateways are offered here. Another provider (Ollama, Gemini, ...) that is
    // already configured is left alone: this is a first-run question, not a takeover.
    const isVendor = VENDORS.some((v) => v.id === current);
    if (isVendor && currentReady) return;
    vendorState.picked = isVendor ? current : "";
    renderVendorPicker();
    $("vendormodal").classList.add("open");
  }

  $("vendsave").onclick = saveVendorChoice;
  $("vendlater").onclick = () => { $("vendormodal").classList.remove("open"); };
  $("vendkey").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") { ev.preventDefault(); saveVendorChoice(); }
  });
  $("vendormodal").addEventListener("click", (ev) => {
    if (ev.target === $("vendormodal")) $("vendormodal").classList.remove("open");
  });

  // ---------- boot ----------
  (async () => {
    let saved = null;
    try { saved = localStorage.getItem("myriaxon-theme"); } catch (e) { /* ignore */ }
    applyTheme(saved || (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"));
    try {
      const cfg = await api("/api/config");
      state.config = cfg;
      refreshBadges();
      $("ws").textContent = cfg.workspace;
      $("provider").textContent = cfg.provider + ":" + cfg.model;
      $("mode").innerHTML = cfg.modes.map((m) => `<option value="${m}"${m === cfg.mode ? " selected" : ""}>${NAMES[m] || m}</option>`).join("");
      populateVendors();
      setModelOptions(cfg.model);
      // Server settings win over the locally cached theme, so a preference set in one browser applies
      // in another; localStorage is only there to avoid a flash of the wrong theme on first paint.
      const prefs = cfg.settings || {};
      if (prefs.theme) applyTheme(prefs.theme);
      applyDensity(prefs.density);
      const list = await api("/api/sessions");
      // A session listed a moment ago can be gone by the time we attach (another tab, or a server
      // that restarted between the two calls), so a failure here recovers rather than reporting.
      const first = (list.sessions || [])[0];
      const opened = first ? await attach(first.id, { quiet: true }) : await newSession();
      if (first && !opened) await recoverSession("that session no longer exists");
      $("conn").textContent = "ready";
      // Mission control is the landing view: it is the one that answers "what is going on" without
      // the user having to ask, and the chat is one click away.
      mcShow("mission");
      // The transparency feed and its dial, started after the page is usable. This stream covers loci as well
      // as sessions, so it runs even when no session is open -- and a stream that cannot connect must not stop
      // the page from working.
      wireTransparency();
      loadTransparency();
      // After the page is usable, never before: the picker is a question, and a question that blocks
      // the interface is a worse first impression than a working page with a dialog over it.
      maybeAskVendor();
    } catch (err) {
      $("conn").textContent = "error: " + err.message;
      addNotice("could not reach the Myriaxon server: " + err.message, "error");
    }
  })();
})();
</script>
</body>
</html>
"""
