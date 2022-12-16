from markdown_it import MarkdownIt


def render_markdown(content):
    md = MarkdownIt("gfm-like")
    return md.render(content)
