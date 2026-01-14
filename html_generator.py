#!/usr/bin/env python3
"""
Discord Archive HTML Generator
Converts JSON archive to static HTML pages

Templates :
- templates/index.html
- templates/components/search_modal.html
- templates/style.css
- templates/script.js
"""

import json
import shutil
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any
import html
import re


class HTMLGenerator:
    def __init__(self, archive_path: str = "./discord_archive",
                 output_path: str = "./discord_html"):
        self.archive_path = Path(archive_path)
        self.output_path = Path(output_path)
        self.output_path.mkdir(parents=True, exist_ok=True)
        self.messages_per_page = 500  # Split into pages for large channels

        self.templates_dir = Path(__file__).parent / "templates"
        self.components_dir = self.templates_dir / "components"

    # --------------------------
    # Template "components" API
    # --------------------------
    def load_template(self, relative_path: str) -> str:
        """Load a template file from templates/"""
        path = self.templates_dir / relative_path
        if not path.exists():
            raise FileNotFoundError(f"Missing template: {path}")
        return path.read_text(encoding="utf-8")

    def _render_includes(self, template: str) -> str:
        """
        Replace include directives like:
          {{> components/search_modal.html }}
        """
        include_re = re.compile(r"\{\{\>\s*([^}]+?)\s*\}\}")

        def replace_include(match: re.Match) -> str:
            rel = match.group(1).strip()
            included = self.load_template(rel)
            # Allow nested includes
            return self._render_includes(included)

        return include_re.sub(replace_include, template)

    def render_template(self, template: str, context: Dict[str, Any]) -> str:
        """
        Very small renderer:
          - resolves includes
          - replaces {{key}} with context[key]
        """
        template = self._render_includes(template)

        # Replace variables: {{key}}
        var_re = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")

        def replace_var(match: re.Match) -> str:
            key = match.group(1)
            val = context.get(key, "")
            return str(val)

        return var_re.sub(replace_var, template)

    # --------------------------
    # Generation
    # --------------------------
    def generate_all(self):
        """Generate HTML for all archived servers"""
        for server_dir in self.archive_path.glob("server_*"):
            if server_dir.is_dir():
                self.generate_server(server_dir)

    def generate_server(self, server_path: Path):
        """Generate HTML for a single server"""
        server_id = server_path.name.replace("server_", "")

        # Load server info
        with open(server_path / "server_info.json", "r", encoding="utf-8") as f:
            server_info = json.load(f)

        # Load channels
        with open(server_path / "channels.json", "r", encoding="utf-8") as f:
            channels = json.load(f)

        # Create output directory
        output_dir = self.output_path / server_id
        output_dir.mkdir(exist_ok=True)

        # Generate index page (templated)
        self.generate_index(output_dir, server_info, channels)

        # Generate channel pages (existing HTML generation, but modal is now a component)
        for channel in channels:
            self.generate_channel_pages(
                server_path / f"channel_{channel['id']}",
                output_dir,
                channel,
                server_info
            )

        # Copy CSS and JS into output folder
        self.generate_static_files(output_dir)

        print(f"Generated HTML for server: {server_info['name']}")

    def generate_index(self, output_dir: Path, server_info: Dict, channels: List[Dict]):
        """Generate main index page from templates/index.html"""
        tpl = self.load_template("index.html")

        context = {
            "title": f"{html.escape(server_info['name'])} - Discord Archive",
            "server_name": html.escape(server_info["name"]),
            "archived_at": self.format_timestamp(server_info.get("archived_at", "")),
            "member_count": str(server_info.get("member_count", "")),
            "channel_list": self.generate_channel_list(channels),
        }

        html_content = self.render_template(tpl, context)
        (output_dir / "index.html").write_text(html_content, encoding="utf-8")

    def generate_channel_list(self, channels: List[Dict]) -> str:
        """Generate HTML for channel list"""
        categories: Dict[str, List[Dict]] = {}
        for channel in sorted(channels, key=lambda c: c.get("position", 0)):
            category = channel.get("category", "Uncategorized")
            categories.setdefault(category, []).append(channel)

        html_parts = []
        for category, category_channels in categories.items():
            html_parts.append('<div class="category">')
            html_parts.append(f'<div class="category-name">{html.escape(category)}</div>')
            for channel in category_channels:
                html_parts.append(
                    f'<a href="channel_{channel["id"]}_p1.html" class="channel-link">'
                    f'<span class="channel-hash">#</span> {html.escape(channel["name"])}'
                    f'<span class="message-count">({channel.get("message_count", 0)} msgs)</span>'
                    f"</a>"
                )
            html_parts.append("</div>")

        return "\n".join(html_parts)

    def generate_channel_pages(self, channel_path: Path, output_dir: Path,
                               channel: Dict, server_info: Dict):
        """Generate paginated HTML pages for a channel"""
        messages_file = channel_path / "messages.json"
        if not messages_file.exists():
            return

        with open(messages_file, "r", encoding="utf-8") as f:
            messages = json.load(f)

        total_pages = max(1, (len(messages) + self.messages_per_page - 1) // self.messages_per_page)

        for page_num in range(1, total_pages + 1):
            start_idx = (page_num - 1) * self.messages_per_page
            end_idx = min(start_idx + self.messages_per_page, len(messages))
            page_messages = messages[start_idx:end_idx]

            self.generate_channel_page(
                output_dir, channel, server_info,
                page_messages, page_num, total_pages
            )

    def generate_channel_page(self, output_dir: Path, channel: Dict,
                            server_info: Dict, messages: List[Dict],
                            page_num: int, total_pages: int):

        tpl = self.load_template("channel.html")

        pagination = self.generate_pagination(channel["id"], page_num, total_pages)
        messages_html = self.generate_messages_html(messages)

        topic_html = ""
        if channel.get("topic"):
            topic_html = f'<p class="channel-topic">{html.escape(channel["topic"])}</p>'

        context = {
            "title": f"#{channel['name']} - {server_info['name']}",
            "server_name": html.escape(server_info["name"]),
            "channel_name": html.escape(channel["name"]),
            "channel_topic": topic_html,
            "messages_html": messages_html,
            "pagination": pagination,
        }

        html_content = self.render_template(tpl, context)
        filename = f"channel_{channel['id']}_p{page_num}.html"

        (output_dir / filename).write_text(html_content, encoding="utf-8")


    def generate_pagination(self, channel_id: int, page_num: int, total_pages: int) -> str:
        """Generate pagination HTML"""
        if total_pages <= 1:
            return ""

        parts = ['<div class="pagination">']

        if page_num > 1:
            parts.append(f'<a href="channel_{channel_id}_p{page_num-1}.html" class="page-btn">← Previous</a>')
        else:
            parts.append('<span class="page-btn disabled">← Previous</span>')

        parts.append(f'<span class="page-info">Page {page_num} of {total_pages}</span>')

        if page_num < total_pages:
            parts.append(f'<a href="channel_{channel_id}_p{page_num+1}.html" class="page-btn">Next →</a>')
        else:
            parts.append('<span class="page-btn disabled">Next →</span>')

        parts.append("</div>")
        return "\n".join(parts)

    def generate_messages_html(self, messages: List[Dict]) -> str:
        """Generate HTML for messages"""
        html_parts = []
        last_author = None
        last_timestamp = None

        for msg in messages:
            author_name = msg["author"]["name"]
            timestamp = datetime.fromisoformat(msg["timestamp"].replace("Z", "+00:00"))

            group_message = False
            if last_author == author_name and last_timestamp:
                time_diff = (timestamp - last_timestamp).total_seconds()
                if time_diff < 300:
                    group_message = True

            html_parts.append(self.generate_grouped_message(msg) if group_message else self.generate_full_message(msg))

            last_author = author_name
            last_timestamp = timestamp

        return "\n".join(html_parts)

    def generate_full_message(self, msg: Dict) -> str:
        """Generate HTML for a full message with avatar and author"""
        author = msg["author"]
        timestamp = self.format_timestamp(msg["timestamp"])
        content = self.format_content(msg.get("content", ""))

        avatar_url = author.get("avatar_url", "data:image/svg+xml,<svg xmlns=\"http://www.w3.org/2000/svg\"/>")

        return f"""
        <div class="message" id="msg-{msg['id']}">
            <div class="message-avatar">
                <img src="{avatar_url}" alt="{html.escape(author['name'])}" onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%2240%22 height=%2240%22><rect fill=%22%235865F2%22 width=%2240%22 height=%2240%22/></svg>'">
            </div>
            <div class="message-content">
                <div class="message-header">
                    <span class="message-author">{html.escape(author.get('display_name', author['name']))}</span>
                    <span class="message-timestamp">{timestamp}</span>
                    {' <span class="message-edited">(edited)</span>' if msg.get('edited_timestamp') else ''}
                    {' <span class="message-bot-tag">BOT</span>' if author.get('bot') else ''}
                </div>
                <div class="message-text">{content}</div>
                {self.generate_attachments_html(msg.get('attachments', []))}
                {self.generate_embeds_html(msg.get('embeds', []))}
                {self.generate_reactions_html(msg.get('reactions', []))}
            </div>
        </div>"""

    def generate_grouped_message(self, msg: Dict) -> str:
        """Generate HTML for a grouped message (no avatar, compact)"""
        timestamp = self.format_timestamp(msg["timestamp"])
        content = self.format_content(msg.get("content", ""))

        return f"""
        <div class="message message-grouped" id="msg-{msg['id']}">
            <div class="message-avatar"></div>
            <div class="message-content">
                <div class="message-text">
                    <span class="message-timestamp-inline">{timestamp}</span>
                    {content}
                </div>
                {self.generate_attachments_html(msg.get('attachments', []))}
                {self.generate_embeds_html(msg.get('embeds', []))}
                {self.generate_reactions_html(msg.get('reactions', []))}
            </div>
        </div>"""

    def format_content(self, content: str) -> str:
        """Format message content with Discord markdown (simple)"""
        if not content:
            return ""

        content = html.escape(content)

        # code blocks first (so we don't bold/italic inside them as easily)
        content = re.sub(r"```(\w*)\n(.+?)\n```", r'<pre><code class="language-\1">\2</code></pre>', content, flags=re.DOTALL)

        content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", content)
        content = re.sub(r"__(.+?)__", r"<u>\1</u>", content)
        content = re.sub(r"~~(.+?)~~", r"<del>\1</del>", content)
        content = re.sub(r"`(.+?)`", r"<code>\1</code>", content)
        content = re.sub(r"\*(.+?)\*", r"<em>\1</em>", content)
        content = re.sub(r"_(.+?)_", r"<em>\1</em>", content)

        url_pattern = r"(https?://[^\s<>\"{}|\\^\[\]`]+)"
        content = re.sub(url_pattern, r'<a href="\1" target="_blank">\1</a>', content)

        content = content.replace("\n", "<br>")
        return content

    def generate_attachments_html(self, attachments: List[Dict]) -> str:
        """Generate HTML for attachments"""
        if not attachments:
            return ""

        html_parts = ['<div class="attachments">']
        for att in attachments:
            if att.get("content_type", "").startswith("image/"):
                html_parts.append(
                    f'<div class="attachment attachment-image">'
                    f'<a href="{att["url"]}" target="_blank">'
                    f'<img src="{att["url"]}" alt="{html.escape(att.get("filename", "image"))}" loading="lazy">'
                    f"</a>"
                    f"</div>"
                )
            else:
                html_parts.append(
                    f'<div class="attachment attachment-file">'
                    f'<a href="{att["url"]}" target="_blank">'
                    f'📎 {html.escape(att.get("filename", "file"))} ({self.format_bytes(att.get("size", 0))})'
                    f"</a>"
                    f"</div>"
                )
        html_parts.append("</div>")
        return "\n".join(html_parts)

    def generate_embeds_html(self, embeds: List[Dict]) -> str:
        """Generate HTML for embeds"""
        if not embeds:
            return ""

        html_parts = []
        for embed in embeds:
            if not embed.get("title") and not embed.get("description"):
                continue

            color = f"#{embed['color']:06x}" if embed.get("color") else "#5865F2"
            html_parts.append(f'<div class="embed" style="border-left-color: {color}">')

            if embed.get("title"):
                if embed.get("url"):
                    html_parts.append(
                        f'<div class="embed-title"><a href="{embed["url"]}" target="_blank">{html.escape(embed["title"])}</a></div>'
                    )
                else:
                    html_parts.append(f'<div class="embed-title">{html.escape(embed["title"])}</div>')

            if embed.get("description"):
                html_parts.append(f'<div class="embed-description">{html.escape(embed["description"])}</div>')

            html_parts.append("</div>")

        return "\n".join(html_parts)

    def generate_reactions_html(self, reactions: List[Dict]) -> str:
        """Generate HTML for reactions"""
        if not reactions:
            return ""

        html_parts = ['<div class="reactions">']
        for reaction in reactions:
            html_parts.append(
                f'<span class="reaction">{html.escape(reaction.get("emoji", ""))} {reaction.get("count", 0)}</span>'
            )
        html_parts.append("</div>")
        return "\n".join(html_parts)

    def generate_static_files(self, output_dir: Path):
        """Copy CSS and JavaScript files from templates/"""
        self.templates_dir.mkdir(exist_ok=True)
        self.components_dir.mkdir(exist_ok=True)

        css_src = self.templates_dir / "style.css"
        js_src = self.templates_dir / "script.js"

        if not css_src.exists() or not js_src.exists():
            raise FileNotFoundError(
                f"Missing templates. Expected:\n  {css_src}\n  {js_src}"
            )

        shutil.copyfile(css_src, output_dir / "style.css")
        shutil.copyfile(js_src, output_dir / "script.js")

    @staticmethod
    def format_timestamp(timestamp_str: str) -> str:
        """Format ISO timestamp to readable format"""
        try:
            dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return timestamp_str

    @staticmethod
    def format_bytes(bytes_size: int) -> str:
        """Format bytes to human readable format"""
        try:
            size = float(bytes_size)
        except Exception:
            size = 0.0

        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"


def main():
    import sys

    archive_path = sys.argv[1] if len(sys.argv) > 1 else "./discord_archive"
    output_path = sys.argv[2] if len(sys.argv) > 2 else "./discord_html"

    generator = HTMLGenerator(archive_path, output_path)
    generator.generate_all()

    print("\n HTML generation complete!")
    print(f"📁 Output directory: {Path(output_path).absolute()}")
    print("🌐 Open index.html in your browser to view the archive")


if __name__ == "__main__":
    main()
