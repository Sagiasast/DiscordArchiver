#!/usr/bin/env python3
"""
Discord Server Archiver Bot
Archives Discord server messages with incremental updates
"""

import discord
from discord.ext import commands, tasks
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import asyncio
from typing import Optional, Dict, List
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('discord_archiver')


class DiscordArchiver(commands.Bot):
    def __init__(self, archive_path: str = "./discord_archive", 
                 update_interval_hours: int = 24):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.members = True
        
        super().__init__(command_prefix='!archive_', intents=intents)
        
        self.archive_path = Path(archive_path)
        self.archive_path.mkdir(parents=True, exist_ok=True)
        self.update_interval_hours = update_interval_hours
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
    
    async def on_ready(self):
        """Bot ready event"""
        logger.info(f'Logged in as {self.user.name} ({self.user.id})')
        logger.info(f'Archive path: {self.archive_path.absolute()}')
        
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
    
    async def archive_server(self, guild: discord.Guild, incremental: bool = False):
        """Archive entire server or update incrementally"""
        logger.info(f'Archiving server: {guild.name} (ID: {guild.id})')
        
        # Create server directory
        server_path = self.archive_path / f"server_{guild.id}"
        server_path.mkdir(exist_ok=True)
        
        # Save server info
        server_info = {
            'id': guild.id,
            'name': guild.name,
            'description': guild.description,
            'member_count': guild.member_count,
            'created_at': guild.created_at.isoformat(),
            'archived_at': datetime.now(timezone.utc).isoformat(),
            'icon_url': str(guild.icon.url) if guild.icon else None
        }
        
        with open(server_path / 'server_info.json', 'w', encoding='utf-8') as f:
            json.dump(server_info, f, indent=2)
        
        # Archive channels
        channels_data = []
        for channel in guild.text_channels:
            try:
                channel_data = await self.archive_channel(
                    channel, server_path, incremental
                )
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
    
    async def archive_channel(self, channel: discord.TextChannel, 
                            server_path: Path, incremental: bool = False) -> Dict:
        """Archive a single channel"""
        channel_id = str(channel.id)
        logger.info(f'Archiving channel: #{channel.name}')
        
        # Get last archived message timestamp
        after_time = None
        if incremental and channel_id in self.metadata['channels']:
            last_msg_id = self.metadata['channels'][channel_id].get('last_message_id')
            if last_msg_id:
                after_time = discord.Object(id=int(last_msg_id))
        
        # Create channel directory
        channel_path = server_path / f"channel_{channel.id}"
        channel_path.mkdir(exist_ok=True)
        
        # Archive messages
        messages = []
        last_message_id = None
        message_count = 0
        
        try:
            async for message in channel.history(
                limit=None, 
                after=after_time,
                oldest_first=True
            ):
                msg_data = await self.serialize_message(message)
                messages.append(msg_data)
                last_message_id = message.id
                message_count += 1
                
                if message_count % 100 == 0:
                    logger.info(f'  Archived {message_count} messages from #{channel.name}')
        
        except discord.Forbidden:
            logger.warning(f'No permission to read channel: #{channel.name}')
        except Exception as e:
            logger.error(f'Error reading messages from #{channel.name}: {e}')
        
        # Save messages to JSON file
        messages_file = channel_path / 'messages.json'
        
        if incremental and messages_file.exists():
            # Append to existing messages
            with open(messages_file, 'r', encoding='utf-8') as f:
                existing_messages = json.load(f)
            existing_messages.extend(messages)
            messages = existing_messages
        
        with open(messages_file, 'w', encoding='utf-8') as f:
            json.dump(messages, f, indent=2, ensure_ascii=False)
        
        # Create searchable text file
        text_file = channel_path / 'messages.txt'
        mode = 'a' if (incremental and text_file.exists()) else 'w'
        with open(text_file, mode, encoding='utf-8') as f:
            for msg in messages:
                timestamp = msg['timestamp']
                author = msg['author']['name']
                content = msg['content']
                f.write(f"[{timestamp}] {author}: {content}\n")
        
        # Channel metadata
        channel_data = {
            'id': channel.id,
            'name': channel.name,
            'topic': channel.topic,
            'position': channel.position,
            'category': channel.category.name if channel.category else None,
            'message_count': len(messages),
            'last_message_id': last_message_id
        }
        
        # Update metadata
        self.metadata['channels'][channel_id] = channel_data
        self.save_metadata()
        
        logger.info(f'Channel archived: #{channel.name} ({message_count} new messages)')
        return channel_data
    
    async def serialize_message(self, message: discord.Message) -> Dict:
        """Convert Discord message to JSON-serializable dict"""
        attachments = []
        for att in message.attachments:
            attachments.append({
                'filename': att.filename,
                'url': att.url,
                'size': att.size,
                'content_type': att.content_type
            })
        
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
        await ctx.send('✅ Full archive completed!')
    
    @commands.command(name='update')
    async def archive_update(self, ctx):
        """Update archive with new messages"""
        await ctx.send('Starting incremental archive update...')
        await self.archive_server(ctx.guild, incremental=True)
        await ctx.send('✅ Archive updated!')
    
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
        
        await ctx.send(embed=embed)


def main():
    """Main entry point"""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python discord_archiver.py <BOT_TOKEN> [update_interval_hours] [archive_path]")
        print("  BOT_TOKEN: Your Discord bot token")
        print("  update_interval_hours: Auto-update interval (default: 24, 0 to disable)")
        print("  archive_path: Path to store archives (default: ./discord_archive)")
        sys.exit(1)
    
    token = sys.argv[1]
    update_interval = int(sys.argv[2]) if len(sys.argv) > 2 else 24
    archive_path = sys.argv[3] if len(sys.argv) > 3 else "./discord_archive"
    
    bot = DiscordArchiver(archive_path=archive_path, update_interval_hours=update_interval)
    bot.run(token)


if __name__ == '__main__':
    main()
