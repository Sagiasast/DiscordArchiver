#!/usr/bin/env python3
"""
Discord Archive Search Tool
Search through archived messages with filters
"""

import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
import re


class ArchiveSearcher:
    def __init__(self, archive_path: str = "./discord_archive"):
        self.archive_path = Path(archive_path)
    
    def search(self, 
               query: str = "",
               author: str = "",
               channel: str = "",
               date_from: Optional[str] = None,
               date_to: Optional[str] = None,
               case_sensitive: bool = False,
               regex: bool = False) -> List[Dict]:
        """
        Search archived messages with multiple filters
        
        Args:
            query: Text to search for (supports wildcards: * and ?)
            author: Filter by author name
            channel: Filter by channel name or ID
            date_from: Start date (YYYY-MM-DD)
            date_to: End date (YYYY-MM-DD)
            case_sensitive: Case-sensitive search
            regex: Treat query as regex pattern
        
        Returns:
            List of matching messages with metadata
        """
        results = []
        
        # Convert wildcards to regex if not already regex
        if query and not regex:
            query = self._wildcard_to_regex(query)
            regex = True
        
        # Compile regex pattern
        if query and regex:
            flags = 0 if case_sensitive else re.IGNORECASE
            try:
                pattern = re.compile(query, flags)
            except re.error as e:
                print(f"Invalid regex pattern: {e}")
                return []
        else:
            pattern = None
        
        # Parse date filters
        date_from_dt = datetime.fromisoformat(date_from) if date_from else None
        date_to_dt = datetime.fromisoformat(date_to + "T23:59:59") if date_to else None
        
        # Search through all servers
        for server_dir in self.archive_path.glob("server_*"):
            if not server_dir.is_dir():
                continue
            
            # Load server info
            server_info_file = server_dir / 'server_info.json'
            if server_info_file.exists():
                with open(server_info_file, 'r', encoding='utf-8') as f:
                    server_info = json.load(f)
            else:
                server_info = {'name': 'Unknown Server'}
            
            # Search through channels
            for channel_dir in server_dir.glob("channel_*"):
                if not channel_dir.is_dir():
                    continue
                
                # Check if channel matches filter
                channel_id = channel_dir.name.replace("channel_", "")
                
                messages_file = channel_dir / 'messages.json'
                if not messages_file.exists():
                    continue
                
                # Load messages
                with open(messages_file, 'r', encoding='utf-8') as f:
                    messages = json.load(f)
                
                # Get channel name from first message or metadata
                channel_name = "unknown"
                if messages:
                    # Channel info should be in parent directory
                    pass
                
                # Filter messages
                for msg in messages:
                    # Author filter
                    if author:
                        author_name = msg['author']['name'].lower()
                        author_display = msg['author']['display_name'].lower()
                        if author.lower() not in author_name and author.lower() not in author_display:
                            continue
                    
                    # Channel filter
                    if channel:
                        if channel.lower() not in channel_id.lower():
                            continue
                    
                    # Date filter
                    if date_from_dt or date_to_dt:
                        msg_time = datetime.fromisoformat(msg['timestamp'].replace('Z', '+00:00'))
                        if date_from_dt and msg_time < date_from_dt:
                            continue
                        if date_to_dt and msg_time > date_to_dt:
                            continue
                    
                    # Text search
                    if pattern:
                        content = msg['content']
                        if not pattern.search(content):
                            continue
                    
                    # Add to results
                    results.append({
                        'server': server_info['name'],
                        'server_id': server_info['id'],
                        'channel_id': channel_id,
                        'message': msg
                    })
        
        return results
    
    def search_and_export(self, output_file: str, **search_kwargs):
        """Search and export results to a file"""
        results = self.search(**search_kwargs)
        
        # Export to JSON
        if output_file.endswith('.json'):
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
        
        # Export to TXT
        elif output_file.endswith('.txt'):
            with open(output_file, 'w', encoding='utf-8') as f:
                for result in results:
                    msg = result['message']
                    f.write(f"Server: {result['server']}\n")
                    f.write(f"Channel ID: {result['channel_id']}\n")
                    f.write(f"Timestamp: {msg['timestamp']}\n")
                    f.write(f"Author: {msg['author']['display_name']} ({msg['author']['name']})\n")
                    f.write(f"Content: {msg['content']}\n")
                    f.write("-" * 80 + "\n")
        
        # Export to CSV
        elif output_file.endswith('.csv'):
            import csv
            with open(output_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['Server', 'Channel ID', 'Timestamp', 'Author', 'Content'])
                for result in results:
                    msg = result['message']
                    writer.writerow([
                        result['server'],
                        result['channel_id'],
                        msg['timestamp'],
                        msg['author']['display_name'],
                        msg['content']
                    ])
        
        print(f"Exported {len(results)} results to {output_file}")
    
    def generate_search_index(self, output_file: str = "search_index.json"):
        """Generate a search index for faster searching"""
        index = {
            'servers': {},
            'channels': {},
            'authors': set(),
            'total_messages': 0
        }
        
        for server_dir in self.archive_path.glob("server_*"):
            if not server_dir.is_dir():
                continue
            
            server_id = server_dir.name.replace("server_", "")
            
            # Load server info
            server_info_file = server_dir / 'server_info.json'
            if server_info_file.exists():
                with open(server_info_file, 'r', encoding='utf-8') as f:
                    server_info = json.load(f)
                    index['servers'][server_id] = {
                        'name': server_info['name'],
                        'channels': []
                    }
            
            # Index channels
            for channel_dir in server_dir.glob("channel_*"):
                if not channel_dir.is_dir():
                    continue
                
                channel_id = channel_dir.name.replace("channel_", "")
                messages_file = channel_dir / 'messages.json'
                
                if not messages_file.exists():
                    continue
                
                with open(messages_file, 'r', encoding='utf-8') as f:
                    messages = json.load(f)
                
                # Get unique authors
                for msg in messages:
                    index['authors'].add(msg['author']['name'])
                
                channel_info = {
                    'id': channel_id,
                    'message_count': len(messages),
                    'date_range': {
                        'start': messages[0]['timestamp'] if messages else None,
                        'end': messages[-1]['timestamp'] if messages else None
                    }
                }
                
                index['channels'][channel_id] = channel_info
                index['servers'][server_id]['channels'].append(channel_id)
                index['total_messages'] += len(messages)
        
        # Convert set to list for JSON serialization
        index['authors'] = sorted(list(index['authors']))
        
        # Save index
        output_path = self.archive_path / output_file
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(index, f, indent=2)
        
        print(f"Search index generated: {output_path}")
        print(f"Total messages indexed: {index['total_messages']}")
        print(f"Total authors: {len(index['authors'])}")
        print(f"Total channels: {len(index['channels'])}")
    
    @staticmethod
    def _wildcard_to_regex(pattern: str) -> str:
        """Convert wildcard pattern to regex"""
        # Escape special regex characters except * and ?
        pattern = re.escape(pattern)
        # Replace escaped wildcards with regex equivalents
        pattern = pattern.replace(r'\*', '.*')
        pattern = pattern.replace(r'\?', '.')
        return pattern


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Search Discord archive')
    parser.add_argument('--archive', default='./discord_archive', 
                       help='Path to archive directory')
    parser.add_argument('--query', '-q', default='', 
                       help='Search query (supports wildcards: * and ?)')
    parser.add_argument('--author', '-a', default='', 
                       help='Filter by author name')
    parser.add_argument('--channel', '-c', default='', 
                       help='Filter by channel name or ID')
    parser.add_argument('--date-from', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--date-to', help='End date (YYYY-MM-DD)')
    parser.add_argument('--case-sensitive', action='store_true', 
                       help='Case-sensitive search')
    parser.add_argument('--regex', action='store_true', 
                       help='Treat query as regex pattern')
    parser.add_argument('--output', '-o', 
                       help='Export results to file (.json, .txt, or .csv)')
    parser.add_argument('--index', action='store_true', 
                       help='Generate search index')
    parser.add_argument('--limit', type=int, default=100, 
                       help='Maximum number of results to display (default: 100)')
    
    args = parser.parse_args()
    
    searcher = ArchiveSearcher(args.archive)
    
    if args.index:
        searcher.generate_search_index()
        return
    
    # Perform search
    results = searcher.search(
        query=args.query,
        author=args.author,
        channel=args.channel,
        date_from=args.date_from,
        date_to=args.date_to,
        case_sensitive=args.case_sensitive,
        regex=args.regex
    )
    
    # Export or display results
    if args.output:
        searcher.search_and_export(
            args.output,
            query=args.query,
            author=args.author,
            channel=args.channel,
            date_from=args.date_from,
            date_to=args.date_to,
            case_sensitive=args.case_sensitive,
            regex=args.regex
        )
    else:
        # Display results
        print(f"\n{'='*80}")
        print(f"Search Results: {len(results)} messages found")
        print(f"{'='*80}\n")
        
        for i, result in enumerate(results[:args.limit], 1):
            msg = result['message']
            print(f"[{i}] Server: {result['server']}")
            print(f"    Channel ID: {result['channel_id']}")
            print(f"    Time: {msg['timestamp']}")
            print(f"    Author: {msg['author']['display_name']} (@{msg['author']['name']})")
            print(f"    Message: {msg['content'][:200]}{'...' if len(msg['content']) > 200 else ''}")
            print()
        
        if len(results) > args.limit:
            print(f"... and {len(results) - args.limit} more results")
            print(f"Use --limit to see more results or --output to export all")


if __name__ == '__main__':
    main()
