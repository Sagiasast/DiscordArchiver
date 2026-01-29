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
from urllib.parse import quote


class HTMLGenerator:
    def __init__(self, archive_path: str = "./discord_archive",
                 output_path: str = "./discord_html",
                 index_chunk_size: int = 5000):
        self.archive_path = Path(archive_path)
        self.output_path = Path(output_path)
        self.output_path.mkdir(parents=True, exist_ok=True)
        self.messages_per_page = 500  # Split into pages for large channels
        self.index_chunk_size = index_chunk_size  # Messages per search index chunk

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
    # Deterministic colored avatars
    # --------------------------
    def _hsl_to_hex(self, h: float, s: float, l: float) -> str:
        """Convert HSL to hex color."""
        s /= 100.0
        l /= 100.0

        c = (1 - abs(2 * l - 1)) * s
        x = c * (1 - abs(((h / 60.0) % 2) - 1))
        m = l - c / 2

        if 0 <= h < 60:
            r, g, b = c, x, 0
        elif 60 <= h < 120:
            r, g, b = x, c, 0
        elif 120 <= h < 180:
            r, g, b = 0, c, x
        elif 180 <= h < 240:
            r, g, b = 0, x, c
        elif 240 <= h < 300:
            r, g, b = x, 0, c
        else:
            r, g, b = c, 0, x

        r = int((r + m) * 255)
        g = int((g + m) * 255)
        b = int((b + m) * 255)

        return f"#{r:02x}{g:02x}{b:02x}"

    def _user_color_hex(self, user_id: int) -> str:
        """Deterministic color from user_id. Stable across runs/updates."""
        try:
            uid = int(user_id)
        except Exception:
            uid = 0
        hue = (uid * 37) % 360
        return self._hsl_to_hex(hue, 70, 45)

    def _initials(self, display_name: str) -> str:
        """Get 1–2 initials."""
        name = (display_name or "").strip()
        if not name:
            return "?"
        parts = [p for p in re.split(r"\s+", name) if p]
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[0][:1] + parts[1][:1]).upper()

    def _avatar_svg_data_uri(self, user_id: int, display_name: str) -> str:
        """
        Deterministic colored SVG avatar with initials.
        """
        color = self._user_color_hex(user_id)
        initials = self._initials(display_name)

        svg = (
            "<svg xmlns='http://www.w3.org/2000/svg' width='40' height='40'>"
            f"<rect width='40' height='40' rx='20' fill='{color}'/>"
            "<text x='20' y='25' text-anchor='middle' "
            "font-family='Segoe UI, Arial' font-size='14' fill='white' font-weight='600'>"
            f"{html.escape(initials)}</text></svg>"
        )
        return "data:image/svg+xml;charset=utf-8," + quote(svg, safe="")

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

        with open(server_path / "server_info.json", "r", encoding="utf-8") as f:
            server_info = json.load(f)

        with open(server_path / "channels.json", "r", encoding="utf-8") as f:
            channels = json.load(f)

        output_dir = self.output_path / server_id
        output_dir.mkdir(exist_ok=True)

        self.generate_index(output_dir, server_info, channels)

        for channel in channels:
            self.generate_channel_pages(
                server_path / f"channel_{channel['id']}",
                output_dir,
                channel,
                server_info
            )

        self.generate_search_index(server_path, output_dir, channels)
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
        """Generate HTML for channel list with thread indicators"""
        categories: Dict[str, List[Dict]] = {}
        for channel in sorted(channels, key=lambda c: c.get("position", 0)):
            category = channel.get("category", "Uncategorized")
            categories.setdefault(category, []).append(channel)

        html_parts = []
        for category, category_channels in categories.items():
            html_parts.append('<div class="category">')
            html_parts.append(f'<div class="category-name">{html.escape(category)}</div>')
            for channel in category_channels:
                thread_count = len(channel.get('threads', []))
                thread_badge = ''
                if thread_count > 0:
                    thread_badge = f'<span class="thread-badge">{thread_count} 🧵</span>'

                pinned_count = channel.get('pinned_count', 0)
                pinned_badge = ''
                if pinned_count > 0:
                    pinned_badge = f'<span class="pinned-badge">{pinned_count} 📌</span>'

                html_parts.append(
                    f'<a href="channel_{channel["id"]}_p1.html" class="channel-link">'
                    f'<span class="channel-hash">#</span> {html.escape(channel["name"])}'
                    f'{pinned_badge}{thread_badge}'
                    f'<span class="message-count">({channel.get("message_count", 0)} msgs)</span>'
                    f"</a>"
                )
            html_parts.append("</div>")

        return "\n".join(html_parts)

    def generate_pinned_messages_section(self, channel_path: Path, _channel_id: int) -> str:
        """Generate HTML for pinned messages section (collapsible)"""
        pinned_file = channel_path / 'pinned_messages.json'
        if not pinned_file.exists():
            return ""

        with open(pinned_file, 'r', encoding='utf-8') as f:
            pinned = json.load(f)

        if not pinned:
            return ""

        html_parts = [
            '<div class="pinned-messages-section">',
            '  <div class="pinned-header" onclick="togglePinnedMessages()">',
            f'    <span class="pin-icon">📌</span>',
            f'    <span class="pinned-count">{len(pinned)} Pinned Message{"s" if len(pinned) != 1 else ""}</span>',
            '    <span class="pinned-toggle">▼</span>',
            '  </div>',
            '  <div class="pinned-content" id="pinned-content">'
        ]

        for msg in pinned:
            author = msg['author']
            display_name = author.get('display_name') or author.get('name', 'Unknown')
            content = html.escape((msg.get('content', '') or '')[:200])
            timestamp = self.format_timestamp(msg['timestamp'])

            html_parts.append(f'''
            <a href="#msg-{msg['id']}" class="pinned-message">
                <span class="pinned-author">{html.escape(display_name)}</span>
                <span class="pinned-preview">{content}</span>
                <span class="pinned-timestamp">{timestamp}</span>
            </a>
            ''')

        html_parts.extend(['  </div>', '</div>'])
        return '\n'.join(html_parts)

    def generate_thread_indicator(self, thread_info: Dict, _channel_id: int) -> str:
        """Generate HTML for thread indicator on a message"""
        if not thread_info:
            return ""

        thread_link = f"thread_{thread_info['id']}_p1.html"

        return f'''
        <div class="thread-indicator">
            <span class="thread-icon"> 🧵</span>
            <a href="{thread_link}" class="thread-link">
                <span class="thread-name">{html.escape(thread_info.get('name', 'Thread'))}</span>
                <span class="thread-count">{thread_info.get('message_count', 0)} replies</span>
            </a>
        </div>
        '''

    def generate_channel_users_html(self, messages: List[Dict]) -> str:
        """Generate HTML for the list of users who participated in a channel"""
        if not messages:
            return ""

        # Collect unique users with their info
        users: Dict[str, Dict] = {}
        for msg in messages:
            author = msg.get("author", {})
            uid = str(author.get("id", ""))
            if uid and uid not in users:
                users[uid] = {
                    "id": uid,
                    "name": author.get("display_name") or author.get("name", "Unknown"),
                    "avatar_url": author.get("avatar_url"),
                    "bot": author.get("bot", False)
                }

        if not users:
            return ""

        # Sort users alphabetically by name
        sorted_users = sorted(users.values(), key=lambda u: u["name"].lower())

        html_parts = [
            '<div class="channel-users">',
            f'<div class="users-header">Members — {len(sorted_users)}</div>',
            '<div class="users-list">'
        ]

        for user in sorted_users:
            # Generate fallback avatar
            try:
                uid = int(user["id"])
            except (ValueError, TypeError):
                uid = 0
            fallback = self._avatar_svg_data_uri(uid, user["name"])
            avatar_src = user.get("avatar_url") or fallback
            onerror = f"this.onerror=null;this.src='{fallback}';"

            bot_tag = '<span class="user-bot-tag">BOT</span>' if user.get("bot") else ""

            html_parts.append(f'''
            <div class="user-item">
                <img class="user-avatar" src="{avatar_src}" alt="" onerror="{onerror}">
                <span class="user-name">{html.escape(user["name"])}</span>
                {bot_tag}
            </div>
            ''')

        html_parts.extend(['</div>', '</div>'])
        return '\n'.join(html_parts)

    def generate_channel_pages(self, channel_path: Path, output_dir: Path,
                               channel: Dict, server_info: Dict):
        """Generate paginated HTML pages for a channel"""
        messages_file = channel_path / "messages.json"
        if not messages_file.exists():
            return

        with open(messages_file, "r", encoding="utf-8") as f:
            messages = json.load(f)

        total_pages = max(1, (len(messages) + self.messages_per_page - 1) // self.messages_per_page)

        msg_by_id: Dict[str, Dict] = {}
        page_by_id: Dict[str, int] = {}

        for idx, m in enumerate(messages):
            mid = str(m.get("id"))
            msg_by_id[mid] = m
            page_by_id[mid] = (idx // self.messages_per_page) + 1

        # Generate pinned messages section HTML (only for page 1)
        pinned_section = self.generate_pinned_messages_section(channel_path, channel['id'])

        # Generate channel users list (from all messages)
        channel_users_html = self.generate_channel_users_html(messages)

        for page_num in range(1, total_pages + 1):
            start_idx = (page_num - 1) * self.messages_per_page
            end_idx = min(start_idx + self.messages_per_page, len(messages))
            page_messages = messages[start_idx:end_idx]

            self.generate_channel_page(
                output_dir, channel, server_info,
                page_messages, page_num, total_pages,
                msg_by_id, page_by_id,
                pinned_section if page_num == 1 else "",
                channel_users_html
            )

        # Generate thread pages
        threads_dir = channel_path / 'threads'
        if threads_dir.exists():
            for thread_dir in threads_dir.iterdir():
                if thread_dir.is_dir() and thread_dir.name.startswith('thread_'):
                    thread_info_file = thread_dir / 'thread_info.json'
                    if thread_info_file.exists():
                        with open(thread_info_file, 'r', encoding='utf-8') as f:
                            thread_info = json.load(f)
                        self.generate_thread_pages(
                            thread_dir, output_dir, thread_info, channel, server_info
                        )

    def generate_channel_page(self, output_dir: Path, channel: Dict,
                              server_info: Dict, messages: List[Dict],
                              page_num: int, total_pages: int,
                              msg_by_id: Dict[str, Dict], page_by_id: Dict[str, int],
                              pinned_section: str = "",
                              channel_users: str = ""):

        tpl = self.load_template("channel.html")

        pagination = self.generate_pagination(channel["id"], page_num, total_pages)
        messages_html = self.generate_messages_html(messages, channel["id"], msg_by_id, page_by_id)

        topic_html = ""
        if channel.get("topic"):
            topic_html = f'<p class="channel-topic">{html.escape(channel["topic"])}</p>'

        context = {
            "title": f"#{channel['name']} - {server_info['name']}",
            "server_name": html.escape(server_info["name"]),
            "channel_name": html.escape(channel["name"]),
            "channel_topic": topic_html,
            "pinned_section": pinned_section,
            "channel_users": channel_users,
            "messages_html": messages_html,
            "pagination": pagination,
        }

        html_content = self.render_template(tpl, context)
        filename = f"channel_{channel['id']}_p{page_num}.html"
        (output_dir / filename).write_text(html_content, encoding="utf-8")

    def generate_thread_pages(self, thread_path: Path, output_dir: Path,
                              thread_info: Dict, parent_channel: Dict, server_info: Dict):
        """Generate paginated HTML pages for a thread"""
        messages_file = thread_path / 'messages.json'
        if not messages_file.exists():
            return

        with open(messages_file, 'r', encoding='utf-8') as f:
            messages = json.load(f)

        if not messages:
            return

        total_pages = max(1, (len(messages) + self.messages_per_page - 1) // self.messages_per_page)

        msg_by_id = {str(m['id']): m for m in messages}
        page_by_id = {str(m['id']): (idx // self.messages_per_page) + 1
                      for idx, m in enumerate(messages)}

        # Generate thread users list
        thread_users_html = self.generate_channel_users_html(messages)

        for page_num in range(1, total_pages + 1):
            start_idx = (page_num - 1) * self.messages_per_page
            end_idx = min(start_idx + self.messages_per_page, len(messages))
            page_messages = messages[start_idx:end_idx]

            self.generate_thread_page(
                output_dir, thread_info, parent_channel, server_info,
                page_messages, page_num, total_pages,
                msg_by_id, page_by_id,
                thread_users_html
            )

    def generate_thread_page(self, output_dir: Path, thread_info: Dict,
                             parent_channel: Dict, server_info: Dict,
                             messages: List[Dict], page_num: int, total_pages: int,
                             msg_by_id: Dict[str, Dict], page_by_id: Dict[str, int],
                             channel_users: str = ""):
        """Generate a single thread page"""
        tpl = self.load_template("thread.html")

        pagination = self.generate_thread_pagination(thread_info['id'], page_num, total_pages)
        messages_html = self.generate_messages_html(
            messages, thread_info['id'], msg_by_id, page_by_id
        )

        context = {
            "title": f"{thread_info['name']} - #{parent_channel['name']} - {server_info['name']}",
            "server_name": html.escape(server_info["name"]),
            "channel_name": html.escape(parent_channel["name"]),
            "channel_id": parent_channel["id"],
            "thread_name": html.escape(thread_info["name"]),
            "thread_message_count": thread_info.get("message_count", 0),
            "channel_users": channel_users,
            "messages_html": messages_html,
            "pagination": pagination,
        }

        html_content = self.render_template(tpl, context)
        filename = f"thread_{thread_info['id']}_p{page_num}.html"
        (output_dir / filename).write_text(html_content, encoding='utf-8')

    def generate_thread_pagination(self, thread_id: int, page_num: int, total_pages: int) -> str:
        """Generate pagination HTML for threads"""
        if total_pages <= 1:
            return ""

        parts = ['<div class="pagination">']

        if page_num > 1:
            parts.append(f'<a href="thread_{thread_id}_p{page_num-1}.html" class="page-btn">← Previous</a>')
        else:
            parts.append('<span class="page-btn disabled">← Previous</span>')

        parts.append(f'<span class="page-info">Page {page_num} of {total_pages}</span>')

        if page_num < total_pages:
            parts.append(f'<a href="thread_{thread_id}_p{page_num+1}.html" class="page-btn">Next →</a>')
        else:
            parts.append('<span class="page-btn disabled">Next →</span>')

        parts.append("</div>")
        return "\n".join(parts)

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

    def generate_messages_html(self, messages: List[Dict], channel_id: int,
                               msg_by_id: Dict[str, Dict], page_by_id: Dict[str, int]) -> str:
        """Generate HTML for messages (with mentions + reply previews)"""

        user_map: Dict[str, str] = {}
        for msg in messages:
            author = msg.get("author", {})
            uid = author.get("id")
            if uid is not None:
                user_map[str(uid)] = author.get("display_name") or author.get("name") or str(uid)

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

            if group_message:
                html_parts.append(self.generate_grouped_message(msg, user_map, channel_id, msg_by_id, page_by_id))
            else:
                html_parts.append(self.generate_full_message(msg, user_map, channel_id, msg_by_id, page_by_id))

            last_author = author_name
            last_timestamp = timestamp

        return "\n".join(html_parts)

    def generate_full_message(self, msg: Dict, user_map: Dict[str, str],
                              channel_id: int, msg_by_id: Dict[str, Dict], page_by_id: Dict[str, int]) -> str:
        """Generate HTML for a full message with avatar and author + reply preview"""
        author = msg["author"]
        timestamp = self.format_timestamp(msg["timestamp"])
        content = self.format_content(msg.get("content", ""), user_map)
        reply_html = self.render_reply_context(msg, channel_id, msg_by_id, page_by_id, user_map)

        display_name = author.get("display_name") or author.get("name") or "Unknown"
        try:
            uid = int(author.get("id", 0) or 0)
        except Exception:
            uid = 0

        fallback = self._avatar_svg_data_uri(uid, display_name)

        # Use real avatar if present, but ALWAYS fallback on error
        src = author.get("avatar_url") or fallback
        onerror = f"this.onerror=null;this.src='{fallback}';"

        # Pin indicator
        pin_indicator = ''
        if msg.get('pinned'):
            pin_indicator = '<span class="pin-badge" title="Pinned">📌</span>'

        # Thread indicator
        thread_html = ''
        if msg.get('thread'):
            thread_html = self.generate_thread_indicator(msg['thread'], channel_id)

        # Add pinned class for visual highlight
        pinned_class = ' message-pinned' if msg.get('pinned') else ''

        return f"""
        <div class="message{pinned_class}" id="msg-{msg['id']}">
            <div class="message-avatar">
                <img src="{src}" alt="" onerror="{onerror}">
            </div>
            <div class="message-content">
                {reply_html}
                <div class="message-header">
                    <span class="message-author">{html.escape(display_name)}</span>
                    {pin_indicator}
                    <span class="message-timestamp">{timestamp}</span>
                    {' <span class="message-edited">(edited)</span>' if msg.get('edited_timestamp') else ''}
                    {' <span class="message-bot-tag">BOT</span>' if author.get('bot') else ''}
                </div>
                <div class="message-text">{content}</div>
                {self.generate_attachments_html(msg.get('attachments', []))}
                {self.generate_embeds_html(msg.get('embeds', []))}
                {self.generate_reactions_html(msg.get('reactions', []))}
                {thread_html}
            </div>
        </div>"""

    def generate_grouped_message(self, msg: Dict, user_map: Dict[str, str],
                                 channel_id: int, msg_by_id: Dict[str, Dict], page_by_id: Dict[str, int]) -> str:
        """Generate HTML for a grouped message (no avatar, compact) + reply preview"""
        timestamp = self.format_timestamp(msg["timestamp"])
        content = self.format_content(msg.get("content", ""), user_map)
        reply_html = self.render_reply_context(msg, channel_id, msg_by_id, page_by_id, user_map)

        # Pin indicator
        pin_indicator = ''
        if msg.get('pinned'):
            pin_indicator = '<span class="pin-badge" title="Pinned">📌</span> '

        # Thread indicator
        thread_html = ''
        if msg.get('thread'):
            thread_html = self.generate_thread_indicator(msg['thread'], channel_id)

        # Add pinned class for visual highlight
        pinned_class = ' message-pinned' if msg.get('pinned') else ''

        return f"""
        <div class="message message-grouped{pinned_class}" id="msg-{msg['id']}">
            <div class="message-avatar"></div>
            <div class="message-content">
                {reply_html}
                <div class="message-text">
                    <span class="message-timestamp-inline">{timestamp}</span>
                    {pin_indicator}{content}
                </div>
                {self.generate_attachments_html(msg.get('attachments', []))}
                {self.generate_embeds_html(msg.get('embeds', []))}
                {self.generate_reactions_html(msg.get('reactions', []))}
                {thread_html}
            </div>
        </div>"""

    def format_content(self, content: str, user_map: Dict[str, str]) -> str:
        """Format message content with Discord markdown (simple) + user mention rendering"""
        if not content:
            return ""

        content = html.escape(content)

        def replace_mention(match: re.Match) -> str:
            user_id = match.group(1)
            name = user_map.get(user_id, user_id)
            safe_name = html.escape(name)
            return (
                f'<span class="mention mention-user" '
                f'data-mention-id="{user_id}" '
                f'data-mention-name="{safe_name}">@{safe_name}</span>'
            )

        content = re.sub(r"&lt;@!?(\d+)&gt;", replace_mention, content)

        content = re.sub(
            r"```(\w*)\n(.+?)\n```",
            r'<pre><code class="language-\1">\2</code></pre>',
            content,
            flags=re.DOTALL
        )

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

    def generate_search_index(self, server_path: Path, output_dir: Path, channels: List[Dict]):
        """Generate chunked search index for client-side search including threads."""
        all_messages = []
        channel_map = {}
        author_set = set()

        for channel in channels:
            channel_id = str(channel['id'])
            channel_map[channel_id] = {
                'name': channel.get('name', 'unknown'),
                'category': channel.get('category', 'Uncategorized')
            }

            channel_path = server_path / f"channel_{channel['id']}"
            messages_file = channel_path / "messages.json"
            if not messages_file.exists():
                continue

            with open(messages_file, 'r', encoding='utf-8') as f:
                messages = json.load(f)

            for idx, msg in enumerate(messages):
                author_name = msg['author'].get('display_name', msg['author']['name'])
                author_set.add(author_name)
                page_num = (idx // self.messages_per_page) + 1

                all_messages.append({
                    'i': msg['id'],
                    'c': channel_id,
                    'a': author_name,
                    't': msg['timestamp'][:10],
                    'x': msg.get('content', '')[:500],
                    'p': page_num
                })

            # Index thread messages
            threads_dir = channel_path / 'threads'
            if threads_dir.exists():
                for thread_dir in threads_dir.iterdir():
                    if not thread_dir.is_dir():
                        continue

                    thread_info_file = thread_dir / 'thread_info.json'
                    thread_messages_file = thread_dir / 'messages.json'

                    if not thread_messages_file.exists():
                        continue

                    thread_info = {}
                    if thread_info_file.exists():
                        with open(thread_info_file, 'r', encoding='utf-8') as f:
                            thread_info = json.load(f)

                    thread_id = str(thread_info.get('id', thread_dir.name.replace('thread_', '')))
                    thread_name = thread_info.get('name', 'Thread')

                    # Add thread to channel map
                    channel_map[thread_id] = {
                        'name': f"🧵 {thread_name}",
                        'category': channel.get('category', 'Uncategorized'),
                        'parent_channel': channel['name'],
                        'is_thread': True
                    }

                    with open(thread_messages_file, 'r', encoding='utf-8') as f:
                        thread_messages = json.load(f)

                    for idx, msg in enumerate(thread_messages):
                        author_name = msg['author'].get('display_name', msg['author']['name'])
                        author_set.add(author_name)
                        page_num = (idx // self.messages_per_page) + 1

                        all_messages.append({
                            'i': msg['id'],
                            'c': thread_id,
                            'a': author_name,
                            't': msg['timestamp'][:10],
                            'x': msg.get('content', '')[:500],
                            'p': page_num,
                            'th': True  # marker for thread message
                        })

        all_messages.sort(key=lambda m: m['t'], reverse=True)

        total_chunks = max(1, (len(all_messages) + self.index_chunk_size - 1) // self.index_chunk_size)

        manifest = {
            'version': 1,
            'totalMessages': len(all_messages),
            'totalChunks': total_chunks,
            'chunkSize': self.index_chunk_size,
            'channels': channel_map,
            'authors': sorted(list(author_set)),
            'dateRange': {
                'start': all_messages[-1]['t'] if all_messages else None,
                'end': all_messages[0]['t'] if all_messages else None
            }
        }

        with open(output_dir / 'search_manifest.json', 'w', encoding='utf-8') as f:
            json.dump(manifest, f, separators=(',', ':'))

        for chunk_num in range(total_chunks):
            start_idx = chunk_num * self.index_chunk_size
            end_idx = min(start_idx + self.index_chunk_size, len(all_messages))
            chunk_data = all_messages[start_idx:end_idx]

            chunk_file = output_dir / f'search_index_{chunk_num}.json'
            with open(chunk_file, 'w', encoding='utf-8') as f:
                json.dump(chunk_data, f, separators=(',', ':'), ensure_ascii=False)

        print(f"  Generated search index: {len(all_messages)} messages in {total_chunks} chunks")

    def generate_static_files(self, output_dir: Path):
        """Copy CSS and JavaScript files from templates/"""
        self.templates_dir.mkdir(exist_ok=True)
        self.components_dir.mkdir(exist_ok=True)

        css_src = self.templates_dir / "style.css"
        js_src = self.templates_dir / "script.js"
        ico_src = self.templates_dir / "favicon.ico"

        if not css_src.exists() or not js_src.exists():
            raise FileNotFoundError(
                f"Missing templates. Expected:\n  {css_src}\n  {js_src}"
            )

        shutil.copyfile(css_src, output_dir / "style.css")
        shutil.copyfile(js_src, output_dir / "script.js")

        # Optional favicon
        if ico_src.exists():
            shutil.copyfile(ico_src, output_dir / "favicon.ico")

    def render_reply_context(self, msg: Dict, channel_id: int,
                             msg_by_id: Dict[str, Dict], page_by_id: Dict[str, int],
                             user_map: Dict[str, str]) -> str:
        ref = msg.get("reference")
        if not ref:
            return ""

        ref_msg_id = ref.get("message_id")
        ref_channel_id = ref.get("channel_id")

        if not ref_msg_id or not ref_channel_id or int(ref_channel_id) != int(channel_id):
            return ""

        ref_msg = msg_by_id.get(str(ref_msg_id))
        if not ref_msg:
            return '<div class="reply-context"><span class="reply-missing">Reply to a message that is not in the archive</span></div>'

        ref_author = ref_msg.get("author", {})
        ref_author_name = ref_author.get("display_name") or ref_author.get("name") or "Unknown"

        ref_content = (ref_msg.get("content") or "").strip()
        if ref_content:
            snippet = ref_content.splitlines()[0][:120]
        else:
            atts = ref_msg.get("attachments") or []
            snippet = "(attachment)" if atts else "(message)"

        snippet_html = self.format_content(snippet, user_map)

        ref_page = page_by_id.get(str(ref_msg_id), 1)
        link = f'channel_{channel_id}_p{ref_page}.html#msg-{ref_msg_id}'

        return f"""
        <div class="reply-context">
            <span class="reply-line"></span>
            <a class="reply-link" href="{link}">
                <span class="reply-author">{html.escape(ref_author_name)}</span>
                <span class="reply-snippet">{snippet_html}</span>
            </a>
        </div>
        """

    @staticmethod
    def format_timestamp(timestamp_str: str) -> str:
        """Format ISO timestamp to readable format in local timezone"""
        try:
            dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            # Convert to local timezone
            local_dt = dt.astimezone()
            return local_dt.strftime("%Y-%m-%d %H:%M")
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
