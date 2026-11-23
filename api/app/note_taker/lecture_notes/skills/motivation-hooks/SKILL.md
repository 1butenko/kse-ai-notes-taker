---
name: motivation-hooks
description: Use for the note's opening - the hook under the title that makes the student want to learn. When a lecture needs one, the four kinds (tangible problem, application, nerd-snipe, historical moment), and the three devices that make it new (a real web image with its source, an animated SVG, a "try it first" interaction), in a .hook div with no heading.
---

# The hook: why should I care?

The hook is the first thing under the title, before "What you will learn". It answers one question: *have we made the reader want to learn this?* Readers skip anything labelled "Motivation", so the hook has **no heading, no callout and no box**. It reads as the page's opening paragraph, with one striking piece of media.

## Is one needed?

| Lecture | Hook? |
|---------|-------|
| Teaches a concept, a method or a result | Yes |
| Introduction to the course, syllabus, organisation | No |
| Exam, revision, a test or a quiz session | No |
| A guest talk or a session with no readings to teach from | No |

When in doubt, ask: is there one idea here the student will use later? If so, hook it.

## The four kinds: pick exactly one

| Kind | Works when | Good | Bad |
|------|-----------|------|-----|
| `tangible-problem` | The idea solves a problem the student can feel | "Your phone guesses the next word you type. How can it know?" (n-gram models) | "Language modelling is an important problem." |
| `application` | The idea is in use today, somewhere concrete | A photo of the 2019 black hole image, then: "it was computed from sparse data with the regularisation you learn today" | "Regularisation has many applications in industry." |
| `nerd-snipe` | A puzzle or surprise that this lecture resolves | "Type 40 random 0s and 1s. You will fail, and we can prove it." (randomness tests) | "Randomness is a fascinating topic." |
| `historical` | A moment when the idea changed something | A photo of Jacquard's punched cards: a loom programmed in 1804, before computers existed (programs as data) | "In the 19th century many inventions appeared." |

A good hook is **concrete** (a thing, a number, a person, a moment), **surprising** for this audience, and **leads straight into the first concept**. Its last sentence hands over: the question this lecture answers.

## Shape and length

- One `::: {.hook}` div at the very top of the body, before the `learning-goals` callout and before any `##`. One per note.
- 80 to 200 words of plain, vivid prose. Short sentences. Talk to the reader ("you").
- One device (below). Not two.
- Facts from the web are linked to their page: `[the 1890 census](https://...)`. Facts from the readings are cited as `[@r1, p. 3]`. Never invent a date, a number or a quote.

## Device 1: a real image from the web

Find it with `web_search` and `page_images`. Then call `check_image(image_url, source_page, source_title)`: it checks the image and gives you the Markdown. Images are shown from their own URL. The caption **must** keep its `Source: [title](page)` link; `render_notes` refuses an image without one, or one you did not check. Prefer Wikimedia Commons, museums, archives, public agencies and the original publisher. Leave the hook's image unnumbered (no `{#fig-...}`).

```markdown
::: {.hook}
In 1804 a weaver in Lyon could change the pattern of a silk cloth without touching the loom.
He swapped a chain of punched cards. Each card said, hole by hole, which threads to lift.
The loom was following a **program**, more than a century before the first computer.

![Punched cards of a Jacquard loom. Source: [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Jacquard.loom.cards.jpg)](https://upload.wikimedia.org/wikipedia/commons/thumb/2/2d/Jacquard.loom.cards.jpg/640px-Jacquard.loom.cards.jpg)

A program is just data that a machine reads. That idea is the whole of this lecture:
how can a list of symbols control a machine?
:::
```

## Device 2: an animated SVG

A small loop that shows the idea moving: a queue filling and draining, a ball bouncing to rest, a wave adding up. Write it to `/notes/assets/<name>.svg` (see `svg-figures`) with SMIL animation: `<animate>`, `<animateTransform>`, `<animateMotion>` or `<set>`, or CSS `@keyframes` in a `<style>`. Animate positions, sizes, colours and opacity. Animating `href` or event handlers is refused. Keep it under 10 seconds per loop and make the still frame make sense too. Follow the label rules in `svg-figures` ("Text and labels"): series names go in a legend or as direct labels outside the plot area, never over the curves. A marker that travels along a curve must follow it: `<animateMotion dur="6s" repeatCount="indefinite"><mpath href="#curve-id"/></animateMotion>` on the marker, not a straight `translateX` at a fixed height.

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 80" role="img">
  <title>Customers join a queue faster than it is served</title>
  <rect x="250" y="20" width="50" height="40" rx="6" fill="none" stroke="currentColor"/>
  <circle cx="20" cy="40" r="10" fill="steelblue">
    <animate attributeName="cx" values="20;230" dur="2s" repeatCount="indefinite"/>
  </circle>
  <circle cx="20" cy="40" r="10" fill="steelblue" opacity="0.6">
    <animate attributeName="cx" values="20;205" dur="2s" begin="0.7s" repeatCount="indefinite"/>
  </circle>
</svg>
```

```markdown
::: {.hook}
Every lunchtime the same thing happens at the university canteen: two cashiers, a queue out
of the door, and then, ten minutes later, nobody. The cashiers did not get faster.

![People arrive in bursts; the queue grows faster than it shrinks](assets/queue.svg)

Why do queues explode when the servers are only *slightly* busier? This lecture's model
answers that with one formula.
:::
```

## Device 3: try it first

The reader acts before being told: they guess, type or choose, and the reveal shows the surprise the lecture explains. Use one or two `{ojs}` cells (see `ojs-interactive`): an input, then a cell that answers. The answer cell waits until the reader has done something.

````markdown
::: {.hook}
Before you read on, play a game with yourself. Type 40 zeros and ones, as randomly as you can.

```{ojs}
//| echo: false
viewof bits = Inputs.text({label: "Your random 0s and 1s", placeholder: "0110100111...", width: 360})
```

```{ojs}
//| echo: false
{
  const s = bits.replace(/[^01]/g, "");
  if (s.length < 20) return md`*Type at least 20 digits to see how random you are.*`;
  let switches = 0, run = 1, longest = 1;
  for (let i = 1; i < s.length; i++) {
    if (s[i] !== s[i - 1]) { switches++; run = 1; } else { run++; longest = Math.max(longest, run); }
  }
  const rate = Math.round(100 * switches / (s.length - 1));
  return md`You switched digits **${rate}%** of the time, and your longest run was **${longest}**.
A fair coin switches about 50% of the time, and in 40 tosses it usually has a run of 5 or more.`;
}
```

Most people switch too often and avoid long runs. A machine can tell you are not a coin.
This lecture is about how: tests that measure what "random" looks like.
:::
````

## Checklist

- Needed? If not, no hook at all.
- Exactly one kind and one device; no heading, no callout.
- Concrete, true and linked; every image keeps its `Source:` link.
- The last sentence asks the question this lecture answers.
