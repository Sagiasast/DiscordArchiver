#!/usr/bin/env python3
"""
Discord Server Archiver Bot
Archives Discord server messages with incremental updates
- Optionally includes bot-authored messages (default: False)
- Stores HUMAN member count (bots excluded) in server_info.json
- Supports message limit per channel (--limit N)
- Supports channel filtering (--channel NAME or --channel ID)
- Supports downloading attachments locally (--download-attachments)
"""

import discord
from discord.ext import commands, tasks
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
import logging
import aiohttp
import asyncio

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('discord_archiver')


class DiscordArchiver(commands.Bot):
    def __init__(
        self,
        archive_path: str = "./discord_archive",
        update_interval_hours: int = 24,
        include_bots: bool = False,
        message_limit: Optional[int] = None,
        channel_filter: Optional[List[str]] = None,
        download_attachments: bool = False,
        api_delay: float = 0.0
    ):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.members = True

        super().__init__(command_prefix='!archive_', intents=intents)

        self.archive_path = Path(archive_path)
        self.archive_path.mkdir(parents=True, exist_ok=True)
        self.update_interval_hours = update_interval_hours
        self.include_bots = include_bots
        self.message_limit = message_limit  # Max messages per channel (None = unlimited)
        self.channel_filter = channel_filter  # List of channel names/IDs to archive (None = all)
        self.download_attachments = download_attachments  # Download attachments locally
        self._http_session: Optional[aiohttp.ClientSession] = None
        self.api_delay: float = api_delay  # Delay between API calls (seconds)

        self.metadata_file = self.archive_path / "metadata.json"
        self.metadata = self.load_metadata()

    def load_metadata(self) -> Dict:
        """Load archiving metadata"""
        if self.metadata_file.exists():
            with open(self.metadata_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {
            'last_archive_time': None,
            'channels': {},
            'server_info': {}
        }

    def save_metadata(self):
        """Save archiving metadata"""
        with open(self.metadata_file, 'w', encoding='utf-8') as f:
            json.dump(self.metadata, f, indent=2, default=str)

    # ----------------------------
    # Human member count
    # ----------------------------
    async def get_human_member_count(self, guild: discord.Guild) -> int:
        """
        Return count of non-bot members (humans only).
        """
        # Best: fetch all members
        try:
            humans = 0
            async for m in guild.fetch_members(limit=None):
                if not m.bot:
                    humans += 1
            return humans
        except Exception as e:
            logger.warning(f"Could not fetch all members for guild {guild.id}, using fallback: {e}")

        # Fallback: cached members
        try:
            cached = list(guild.members)
            if cached:
                return sum(1 for m in cached if not m.bot)
        except Exception:
            pass

        # Last fallback: approximate by subtracting this bot if present
        try:
            if guild.member_count:
                if guild.me is not None:
                    return max(0, guild.member_count - 1)
                return max(0, guild.member_count)
        except Exception:
            pass

        return 0

    # ----------------------------
    # Cleanup helpers
    # ----------------------------
    def _rebuild_messages_txt(self, txt_path: Path, messages: List[Dict]):
        """Rewrite messages.txt from messages list (no duplicates)."""
        with open(txt_path, "w", encoding="utf-8") as f:
            for msg in messages:
                ts = msg.get("timestamp", "")
                author = msg.get("author", {}).get("name", "")
                content = msg.get("content", "")
                f.write(f"[{ts}] {author}: {content}\n")

    def clean_existing_bot_messages_in_channel(self, channel_path: Path) -> int:
        """
        Remove already-archived bot messages from a channel's messages.json/messages.txt.
        Returns number of removed messages.

        NOTE: If include_bots=True, keep bots.
        """
        if self.include_bots:
            return 0

        messages_file = channel_path / "messages.json"
        if not messages_file.exists():
            return 0

        try:
            with open(messages_file, "r", encoding="utf-8") as f:
                msgs = json.load(f)
        except Exception as e:
            logger.error(f"Failed to read {messages_file}: {e}")
            return 0

        before = len(msgs)
        cleaned = [m for m in msgs if not m.get("author", {}).get("bot", False)]
        removed = before - len(cleaned)

        if removed <= 0:
            return 0

        try:
            with open(messages_file, "w", encoding="utf-8") as f:
                json.dump(cleaned, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to write {messages_file}: {e}")
            return 0

        # Rewrite TXT to match cleaned JSON
        txt_file = channel_path / "messages.txt"
        try:
            self._rebuild_messages_txt(txt_file, cleaned)
        except Exception as e:
            logger.error(f"Failed to rebuild {txt_file}: {e}")

        return removed

    def should_archive_channel(self, channel: discord.TextChannel) -> bool:
        """Check if channel should be archived based on filter"""
        if not self.channel_filter:
            return True  # No filter, archive all channels

        # Check if channel name or ID matches any filter
        for f in self.channel_filter:
            # Match by name (case-insensitive)
            if f.lower() == channel.name.lower():
                return True
            # Match by ID
            if f.isdigit() and int(f) == channel.id:
                return True
        return False

    async def get_http_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session for downloading attachments"""
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession()
        return self._http_session

    async def download_attachment(self, url: str, save_path: Path, max_retries: int = 3) -> bool:
        """Download an attachment from URL to local path with retry logic"""
        session = await self.get_http_session()

        for attempt in range(max_retries):
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        save_path.parent.mkdir(parents=True, exist_ok=True)
                        with open(save_path, 'wb') as f:
                            f.write(await response.read())
                        # Small delay between downloads to avoid CDN rate limits
                        await asyncio.sleep(0.1)
                        return True
                    elif response.status == 429:
                        # Rate limited - wait and retry
                        retry_after = float(response.headers.get('Retry-After', 1.0))
                        logger.warning(f"CDN rate limited, waiting {retry_after}s...")
                        await asyncio.sleep(retry_after)
                        continue
                    else:
                        logger.warning(f"Failed to download {url}: HTTP {response.status}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(0.5 * (attempt + 1))
                            continue
                        return False
            except asyncio.TimeoutError:
                logger.warning(f"Timeout downloading {url} (attempt {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1.0 * (attempt + 1))
                    continue
                return False
            except Exception as e:
                logger.error(f"Error downloading {url}: {e} (attempt {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                return False

        return False

    # ----------------------------
    # Discord events / tasks
    # ----------------------------
    async def on_ready(self):
        """Bot ready event"""
        logger.info(f'Logged in as {self.user.name} ({self.user.id})')
        logger.info(f'Archive path: {self.archive_path.absolute()}')
        logger.info(f'Include bot messages: {self.include_bots}')
        logger.info(f'Download attachments: {self.download_attachments}')
        if self.message_limit:
            logger.info(f'Message limit per channel: {self.message_limit}')
        if self.channel_filter:
            logger.info(f'Channel filter: {", ".join(self.channel_filter)}')
        if self.api_delay > 0:
            logger.info(f'API delay: {self.api_delay}s between requests')

        # Start automatic archiving if configured
        if self.update_interval_hours > 0:
            self.auto_archive.change_interval(hours=self.update_interval_hours)
            self.auto_archive.start()
            logger.info(f'Auto-archive enabled: every {self.update_interval_hours} hours')

    @tasks.loop(hours=24)
    async def auto_archive(self):
        """Automatic archiving task"""
        logger.info('Starting automatic archive update...')
        for guild in self.guilds:
            await self.archive_server(guild, incremental=True)
        logger.info('Automatic archive update completed')

    # ----------------------------
    # Archiving
    # ----------------------------
    async def archive_server(self, guild: discord.Guild, incremental: bool = False):
        """Archive entire server or update incrementally"""
        logger.info(f'Archiving server: {guild.name} (ID: {guild.id})')

        # Create server directory
        server_path = self.archive_path / f"server_{guild.id}"
        server_path.mkdir(exist_ok=True)

        # HUMAN members only
        human_count = await self.get_human_member_count(guild)

        # Save server info
        server_info = {
            'id': guild.id,
            'name': guild.name,
            'description': guild.description,
            'member_count': human_count,  # humans only
            'created_at': guild.created_at.isoformat(),
            'archived_at': datetime.now(timezone.utc).isoformat(),
            'icon_url': str(guild.icon.url) if guild.icon else None,
            'include_bots': self.include_bots,
        }

        with open(server_path / 'server_info.json', 'w', encoding='utf-8') as f:
            json.dump(server_info, f, indent=2)

        # Archive channels (with optional filtering)
        channels_data = []
        for channel in guild.text_channels:
            if not self.should_archive_channel(channel):
                logger.info(f'Skipping channel: #{channel.name} (not in filter)')
                continue
            try:
                channel_data = await self.archive_channel(channel, server_path, incremental)
                channels_data.append(channel_data)
            except Exception as e:
                logger.error(f'Error archiving channel {channel.name}: {e}')

        # Save channels index
        with open(server_path / 'channels.json', 'w', encoding='utf-8') as f:
            json.dump(channels_data, f, indent=2)

        # Update metadata
        self.metadata['last_archive_time'] = datetime.now(timezone.utc).isoformat()
        self.metadata['server_info'][str(guild.id)] = server_info
        self.save_metadata()

        logger.info(f'Server archive completed: {guild.name}')

    async def archive_channel(
        self,
        channel: discord.TextChannel,
        server_path: Path,
        incremental: bool = False
    ) -> Dict:
        """Archive a single channel"""
        channel_id = str(channel.id)
        logger.info(f'Archiving channel: #{channel.name}')

        # Get last archived message id (used as `after=` cursor)
        after_obj = None
        if incremental and channel_id in self.metadata['channels']:
            last_msg_id = self.metadata['channels'][channel_id].get('last_message_id')
            if last_msg_id:
                after_obj = discord.Object(id=int(last_msg_id))

        # Create channel directory
        channel_path = server_path / f"channel_{channel.id}"
        channel_path.mkdir(exist_ok=True)

        # Archive messages (new)
        new_messages: List[Dict] = []
        last_message_id = None
        new_message_count = 0

        # Use message_limit if set, otherwise fetch all (None)
        fetch_limit = self.message_limit

        try:
            async for message in channel.history(
                limit=fetch_limit,
                after=after_obj,
                oldest_first=True
            ):
                # Skip bots unless include_bots=True
                if message.author.bot and not self.include_bots:
                    continue

                msg_data = await self.serialize_message(message, channel_path)
                new_messages.append(msg_data)
                last_message_id = message.id
                new_message_count += 1

                # Check if we've hit the message limit (for non-bot messages)
                if self.message_limit and new_message_count >= self.message_limit:
                    logger.info(f'  Reached message limit ({self.message_limit}) for #{channel.name}')
                    break

                if new_message_count % 100 == 0:
                    logger.info(f'  Archived {new_message_count} new messages from #{channel.name}')
                    # Apply API delay every 100 messages to avoid rate limits
                    if self.api_delay > 0:
                        await asyncio.sleep(self.api_delay)

        except discord.Forbidden:
            logger.warning(f'No permission to read channel: #{channel.name}')
        except Exception as e:
            logger.error(f'Error reading messages from #{channel.name}: {e}')

        # Load existing messages if present
        messages_file = channel_path / 'messages.json'
        all_messages: List[Dict] = []

        if messages_file.exists():
            try:
                with open(messages_file, 'r', encoding='utf-8') as f:
                    all_messages = json.load(f)
            except Exception as e:
                logger.error(f"Failed to read existing {messages_file}: {e}")
                all_messages = []

        # Merge (incremental => append; full => replace)
        if incremental:
            all_messages.extend(new_messages)
        else:
            all_messages = new_messages

        # Write merged JSON
        try:
            with open(messages_file, 'w', encoding='utf-8') as f:
                json.dump(all_messages, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to write {messages_file}: {e}")

        # Clean old bot messages from previous runs (only if include_bots=False)
        removed = self.clean_existing_bot_messages_in_channel(channel_path)
        if removed:
            logger.info(f"  Cleaned {removed} old bot messages from #{channel.name}")

        # Reload final messages from disk (post-clean)
        try:
            with open(messages_file, "r", encoding="utf-8") as f:
                all_messages = json.load(f)
        except Exception as e:
            logger.error(f"Failed to reload {messages_file}: {e}")

        # Always rewrite messages.txt from final list (prevents duplicates)
        text_file = channel_path / 'messages.txt'
        try:
            self._rebuild_messages_txt(text_file, all_messages)
        except Exception as e:
            logger.error(f"Failed to rebuild {text_file}: {e}")

        # Channel metadata
        channel_data = {
            'id': channel.id,
            'name': channel.name,
            'topic': channel.topic,
            'position': channel.position,
            'category': channel.category.name if channel.category else None,
            'message_count': len(all_messages),
            'last_message_id': last_message_id  # last NEW message id this run
        }

        # Update metadata
        self.metadata['channels'][channel_id] = channel_data
        self.save_metadata()

        logger.info(f'Channel archived: #{channel.name} ({new_message_count} new messages)')
        return channel_data

    async def serialize_message(self, message: discord.Message, channel_path: Optional[Path] = None) -> Dict:
        """Convert Discord message to JSON-serializable dict"""
        attachments = []
        for att in message.attachments:
            att_data = {
                'filename': att.filename,
                'url': att.url,
                'size': att.size,
                'content_type': att.content_type
            }

            # Download attachment if enabled
            if self.download_attachments and channel_path:
                attachments_dir = channel_path / "attachments"
                # Use message_id + filename to avoid collisions
                local_filename = f"{message.id}_{att.filename}"
                local_path = attachments_dir / local_filename

                # Only download if not already exists
                if not local_path.exists():
                    if await self.download_attachment(att.url, local_path):
                        att_data['local_path'] = f"attachments/{local_filename}"
                        logger.info(f"    Downloaded: {att.filename}")
                    else:
                        att_data['local_path'] = None  # Download failed
                else:
                    att_data['local_path'] = f"attachments/{local_filename}"

            attachments.append(att_data)

        embeds = []
        for embed in message.embeds:
            embeds.append({
                'title': embed.title,
                'description': embed.description,
                'url': embed.url,
                'color': embed.color.value if embed.color else None,
                'timestamp': embed.timestamp.isoformat() if embed.timestamp else None
            })

        reactions = []
        for reaction in message.reactions:
            reactions.append({
                'emoji': str(reaction.emoji),
                'count': reaction.count
            })

        return {
            'id': message.id,
            'timestamp': message.created_at.isoformat(),
            'edited_timestamp': message.edited_at.isoformat() if message.edited_at else None,
            'author': {
                'id': message.author.id,
                'name': message.author.name,
                'display_name': message.author.display_name,
                'discriminator': message.author.discriminator,
                'bot': message.author.bot,
                'avatar_url': str(message.author.avatar.url) if message.author.avatar else None
            },
            'content': message.content,
            'attachments': attachments,
            'embeds': embeds,
            'reactions': reactions,
            'reference': {
                'message_id': message.reference.message_id,
                'channel_id': message.reference.channel_id
            } if message.reference else None,
            'pinned': message.pinned
        }

    @commands.command(name='full')
    async def archive_full(self, ctx):
        """Perform full server archive"""
        await ctx.send('Starting full server archive...')
        await self.archive_server(ctx.guild, incremental=False)
        await ctx.send('Full archive completed!')

    @commands.command(name='update')
    async def archive_update(self, ctx):
        """Update archive with new messages"""
        await ctx.send('Starting incremental archive update...')
        await self.archive_server(ctx.guild, incremental=True)
        await ctx.send('Archive updated!')

    @commands.command(name='status')
    async def archive_status(self, ctx):
        """Show archive status"""
        last_archive = self.metadata.get('last_archive_time', 'Never')
        channel_count = len(self.metadata.get('channels', {}))

        embed = discord.Embed(
            title='Archive Status',
            color=discord.Color.blue()
        )
        embed.add_field(name='Last Archive', value=last_archive, inline=False)
        embed.add_field(name='Channels Archived', value=channel_count, inline=False)
        embed.add_field(name='Archive Path', value=str(self.archive_path.absolute()), inline=False)
        embed.add_field(name='Include Bots', value=str(self.include_bots), inline=False)

        await ctx.send(embed=embed)


def main():
    """Main entry point"""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python discord_archiver.py <BOT_TOKEN> [update_interval_hours] [archive_path] [options]")
        print("  BOT_TOKEN: Your Discord bot token")
        print("  update_interval_hours: Auto-update interval (default: 24, 0 to disable)")
        print("  archive_path: Path to store archives (default: ./discord_archive)")
        print("Options:")
        print("  --include-bots         Include bot-authored messages in archive (default: False)")
        print("  --limit N              Limit messages per channel (default: unlimited)")
        print("  --channel NAME/ID      Only archive specific channel(s) (can be repeated)")
        print("  --download-attachments Download attachments locally (default: False)")
        print("  --delay N              Delay in seconds between API batches (default: 0)")
        sys.exit(1)

    token = sys.argv[1]
    update_interval = int(sys.argv[2]) if len(sys.argv) > 2 and not str(sys.argv[2]).startswith("--") else 24
    archive_path = sys.argv[3] if len(sys.argv) > 3 and not str(sys.argv[3]).startswith("--") else "./discord_archive"
    include_bots = "--include-bots" in sys.argv
    download_attachments = "--download-attachments" in sys.argv

    # Parse --limit N
    message_limit = None
    if "--limit" in sys.argv:
        try:
            limit_idx = sys.argv.index("--limit")
            message_limit = int(sys.argv[limit_idx + 1])
        except (IndexError, ValueError):
            print("Error: --limit requires a number")
            sys.exit(1)

    # Parse --channel NAME/ID (can be repeated)
    channel_filter = []
    i = 0
    while i < len(sys.argv):
        if sys.argv[i] == "--channel":
            try:
                channel_filter.append(sys.argv[i + 1])
                i += 2
            except IndexError:
                print("Error: --channel requires a channel name or ID")
                sys.exit(1)
        else:
            i += 1

    # Parse --delay N
    api_delay = 0.0
    if "--delay" in sys.argv:
        try:
            delay_idx = sys.argv.index("--delay")
            api_delay = float(sys.argv[delay_idx + 1])
        except (IndexError, ValueError):
            print("Error: --delay requires a number (seconds)")
            sys.exit(1)

    bot = DiscordArchiver(
        archive_path=archive_path,
        update_interval_hours=update_interval,
        include_bots=include_bots,
        message_limit=message_limit,
        channel_filter=channel_filter if channel_filter else None,
        download_attachments=download_attachments,
        api_delay=api_delay
    )
    bot.run(token)


if __name__ == '__main__':
    main()
