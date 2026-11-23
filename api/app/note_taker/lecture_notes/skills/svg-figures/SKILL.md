---
name: svg-figures
description: Use for a precise static picture no diagram language draws well - a geometric construction, a labelled schematic, an annotated plot of a known shape, a number line. You write the SVG file yourself into /notes/assets/ and include it as a figure.
---

# Hand-made SVG figures

Quarto docs: Figures (quarto.org/docs/authoring/figures.html).

## Steps

1. Write the file with `write_file` to `/notes/assets/<name>.svg`. Names are lowercase letters,
   digits and `-`, ending in `.svg`.
2. Include it in the note:

```markdown
![Projection of $b$ onto the line through $a$](assets/projection.svg){#fig-projection width=70%}
```

3. Reference it: "as @fig-projection shows, ...".

## Template

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 240" role="img"
     font-family="Helvetica, Arial, sans-serif" font-size="14">
  <title>Projection of b onto a</title>
  <defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7"
            orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#333"/>
    </marker>
  </defs>
  <line x1="20" y1="200" x2="380" y2="80" stroke="#999" stroke-dasharray="4 4"/>
  <line x1="40" y1="193" x2="300" y2="107" stroke="#4a78b5" stroke-width="3" marker-end="url(#arrow)"/>
  <line x1="40" y1="193" x2="250" y2="40" stroke="#c0504d" stroke-width="3" marker-end="url(#arrow)"/>
  <text x="300" y="130" fill="#4a78b5">a</text>
  <text x="255" y="35" fill="#c0504d">b</text>
</svg>
```

## Rules (enforced by render_notes)

- Root element `<svg>` with a `viewBox`; no `width`/`height` in pixels, so it scales.
- Allowed elements: `svg g defs title desc path rect circle ellipse line polyline polygon text
  tspan marker linearGradient radialGradient stop clipPath mask pattern use symbol style`.
- Not allowed: `<script>`, `<foreignObject>`, `<image>`, `<a>`, animation, any `on...` attribute,
  links or `url(...)` pointing outside the file (only `url(#id)` and `href="#id"`).
  No DOCTYPE or ENTITY. At most 200 KB.
- Always include a `<title>` (screen readers) and use `role="img"`.
- Colours that read on white and in print: `#4a78b5` blue, `#c0504d` red, `#9bbb59` green,
  `#333` text, `#999` guides. Do not rely on colour alone; label things.
- Text at least `font-size="12"` at the viewBox scale. Cyrillic text works.
- Check your coordinates: compute positions, don't eyeball them. A wrong picture is worse than
  none.

## Text and labels

No line, curve, shape or other label may cross a piece of text. Crossed labels are the most
common fault in these figures. `render_notes` checks this: it estimates every label's box and
refuses the figure if a line, curve, shape edge, moving element or other label runs through it.
The axes and dashed guides count too.

- Reserve room for labels before you draw: a legend column on the right of the plot (widen the
  `viewBox` for it) or a row above it. Plot the data inside its own box and keep labels out of
  that box.
- Prefer direct labels just past the right end of each series, in its colour, at the y where
  that series ends. Space them at least `1.3 × font-size` apart vertically; nudge them apart if
  the series end close together.
- Estimate each label's box before you place it: width ≈ `0.6 × font-size × characters`,
  height ≈ `font-size`, baseline at `y`. Check that box against every path at that x range by
  computing the path's y there. If they meet, move the label.
- If a label must sit on top of the drawing (an annotation pointing at a feature), give it a
  white halo so lines behind it don't cut through the letters:
  `<text ... stroke="#fff" stroke-width="4" stroke-linejoin="round" paint-order="stroke">`.
- Use one `font-size` for all labels in a figure (axis ticks may be one size smaller), and
  `text-anchor="middle"` for tick labels centred under their tick.
- In an animation, nothing that moves may pass over text. Text itself stays still.
