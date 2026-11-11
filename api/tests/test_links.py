from app.links import html_to_markdown

QUARTO = r"""<!doctype html><html><head><title>T</title><script>x()</script></head><body>
<div class="reveal"><div class="slides">
<section class="slide level2"><h2>Correlation</h2>
<p>Between  \(x_t\) and
\(y_t\):</p>
<p><span class="math display">\[
r = \frac{a_1}{b}
\]</span></p>
<img data-src=".02_files/fig-1.svg" class="r-stretch">
<a href="#/next">next slide</a>
</section>
<section class="slide level2">
<!-- ## Draft slide {.smaller} - not published -->
<h2>Code</h2>
<pre><code>df.set_index(  "t")
df.plot()</code></pre>
</section>
</div></div></body></html>"""


def test_quarto_slides_become_markdown() -> None:
    text = html_to_markdown(QUARTO, "https://user.quarto.pub/graphics")

    assert text.startswith("## Correlation\n\nBetween $x_t$ and $y_t$:")
    assert "$$\nr = \\frac{a_1}{b}\n$$" in text
    # reveal.js images load from data-src; the page's last segment is a folder.
    assert "![](https://user.quarto.pub/graphics/.02_files/fig-1.svg)" in text
    # In-deck anchors are not links.
    assert "next slide" in text and "#/next" not in text
    # Code keeps its spacing and lines.
    assert 'df.set_index(  "t")\ndf.plot()' in text
    # HTML comments (unpublished slides) and scripts are not content.
    assert "Draft slide" not in text and "x()" not in text


def test_links_on_a_file_page_resolve_against_its_folder() -> None:
    text = html_to_markdown('<p><a href="b.pdf">B</a></p>', "https://site.test/docs/a.html")
    assert text == "[B](https://site.test/docs/b.pdf)"
