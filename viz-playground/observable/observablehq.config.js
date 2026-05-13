// Observable Framework config for the antiquarian viz playground.
// The "narrative-first" stack — long-form prose interleaved with Plot atoms,
// like reading an essay where the charts are evidence cited in the body.

export default {
  title: "Antiquarian — story view",
  root: "src",
  theme: ["air", "alt"], // light + airy serif-friendly theme
  toc: false, // single-page narrative; TOC would fight the prose flow
  sidebar: false,
  pager: false,
  search: false,
  header: "",
  footer:
    'Observable Framework variant of the <a href="https://github.com/tclancy/antiquarian/issues/8">Antiquarian playground</a>. Real npm build — <code>npm run dev</code> for live reload.',
  style: "./style.css",
};
