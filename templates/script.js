// Discord Archive Scripts - Enhanced Search

// ============================================
// Search State & Cache
// ============================================
const SearchEngine = {
  manifest: null,
  loadedChunks: new Map(), // chunk_num -> data
  isLoading: false,
  currentResults: [],
  
  // Initialize search engine
  async init() {
    try {
      const response = await fetch('search_manifest.json');
      if (!response.ok) throw new Error('Manifest not found');
      this.manifest = await response.json();
      console.log(`Search index loaded: ${this.manifest.totalMessages} messages in ${this.manifest.totalChunks} chunks`);
      this.populateAuthorSuggestions();
      this.populateChannelFilter();
      return true;
    } catch (err) {
      console.warn('Search index not available:', err.message);
      return false;
    }
  },

  // Load a specific chunk
  async loadChunk(chunkNum) {
    if (this.loadedChunks.has(chunkNum)) {
      return this.loadedChunks.get(chunkNum);
    }

    try {
      const response = await fetch(`search_index_${chunkNum}.json`);
      if (!response.ok) throw new Error(`Chunk ${chunkNum} not found`);
      const data = await response.json();
      this.loadedChunks.set(chunkNum, data);
      return data;
    } catch (err) {
      console.error(`Failed to load chunk ${chunkNum}:`, err);
      return [];
    }
  },

  // Load all chunks (for full search)
  async loadAllChunks(progressCallback) {
    const chunks = [];
    for (let i = 0; i < this.manifest.totalChunks; i++) {
      const chunk = await this.loadChunk(i);
      chunks.push(...chunk);
      if (progressCallback) {
        progressCallback(i + 1, this.manifest.totalChunks);
      }
    }
    return chunks;
  },

  // Perform search across all messages
  async search(query, filters = {}, progressCallback) {
    if (!this.manifest) {
      await this.init();
    }
    if (!this.manifest) {
      return [];
    }

    this.isLoading = true;
    const results = [];
    const queryLower = query.toLowerCase().trim();
    const authorFilter = (filters.author || '').toLowerCase().trim();
    const channelFilter = filters.channel || '';
    const dateFrom = filters.dateFrom || '';
    const dateTo = filters.dateTo || '';

    // Load and search through all chunks
    for (let i = 0; i < this.manifest.totalChunks; i++) {
      const chunk = await this.loadChunk(i);
      
      for (const msg of chunk) {
        // Apply filters
        if (authorFilter && !msg.a.toLowerCase().includes(authorFilter)) {
          continue;
        }
        if (channelFilter && msg.c !== channelFilter) {
          continue;
        }
        if (dateFrom && msg.t < dateFrom) {
          continue;
        }
        if (dateTo && msg.t > dateTo) {
          continue;
        }
        if (queryLower && !msg.x.toLowerCase().includes(queryLower)) {
          continue;
        }

        // Add channel info to result
        const channelInfo = this.manifest.channels[msg.c] || { name: 'unknown', category: '' };
        results.push({
          ...msg,
          channelName: channelInfo.name,
          channelCategory: channelInfo.category
        });

        // Limit results for performance
        if (results.length >= 500) {
          break;
        }
      }

      if (progressCallback) {
        progressCallback(i + 1, this.manifest.totalChunks);
      }

      if (results.length >= 500) {
        break;
      }
    }

    this.isLoading = false;
    this.currentResults = results;
    return results;
  },

  // Populate author suggestions datalist
  populateAuthorSuggestions() {
    const datalist = document.getElementById('author-suggestions');
    if (!datalist || !this.manifest) return;

    datalist.innerHTML = '';
    for (const author of this.manifest.authors.slice(0, 100)) {
      const option = document.createElement('option');
      option.value = author;
      datalist.appendChild(option);
    }
  },

  // Populate channel filter dropdown
  populateChannelFilter() {
    const select = document.getElementById('search-channel');
    if (!select || !this.manifest) return;

    select.innerHTML = '<option value="">All Channels</option>';
    
    // Group by category
    const categories = {};
    for (const [id, info] of Object.entries(this.manifest.channels)) {
      const cat = info.category || 'Uncategorized';
      if (!categories[cat]) categories[cat] = [];
      categories[cat].push({ id, name: info.name });
    }

    for (const [category, channels] of Object.entries(categories).sort()) {
      const optgroup = document.createElement('optgroup');
      optgroup.label = category;
      
      for (const ch of channels.sort((a, b) => a.name.localeCompare(b.name))) {
        const option = document.createElement('option');
        option.value = ch.id;
        option.textContent = `#${ch.name}`;
        optgroup.appendChild(option);
      }
      
      select.appendChild(optgroup);
    }
  },

  // Get link to specific message
  getMessageLink(msg) {
    return `channel_${msg.c}_p${msg.p}.html#msg-${msg.i}`;
  }
};

// ============================================
// Search Modal Functions
// ============================================
function showSearchModal() {
  const modal = document.getElementById('searchModal');
  if (modal) {
    modal.style.display = 'block';
    document.getElementById('search-text')?.focus();
    
    // Initialize search engine if not already done
    if (!SearchEngine.manifest) {
      SearchEngine.init();
    }
  }
}

function hideSearchModal() {
  const modal = document.getElementById('searchModal');
  if (modal) {
    modal.style.display = 'none';
  }
}

// Close modal when clicking outside
window.onclick = function(event) {
  const modal = document.getElementById('searchModal');
  if (event.target === modal) {
    modal.style.display = 'none';
  }
};

// ============================================
// Advanced Search Function
// ============================================
async function performSearch() {
  const searchText = document.getElementById('search-text')?.value || '';
  const searchAuthor = document.getElementById('search-author')?.value || '';
  const searchChannel = document.getElementById('search-channel')?.value || '';
  const dateFrom = document.getElementById('search-date-from')?.value || '';
  const dateTo = document.getElementById('search-date-to')?.value || '';

  const resultsDiv = document.getElementById('search-results');
  if (!resultsDiv) return;

  // Show loading state
  resultsDiv.innerHTML = `
    <div class="search-loading">
      <div class="search-spinner"></div>
      <p>Searching...</p>
      <p class="search-progress">Loading index...</p>
    </div>
  `;

  try {
    const results = await SearchEngine.search(
      searchText,
      {
        author: searchAuthor,
        channel: searchChannel,
        dateFrom: dateFrom,
        dateTo: dateTo
      },
      (loaded, total) => {
        const progressEl = resultsDiv.querySelector('.search-progress');
        if (progressEl) {
          progressEl.textContent = `Searching chunk ${loaded}/${total}...`;
        }
      }
    );

    displaySearchResults(results, searchText);
  } catch (err) {
    resultsDiv.innerHTML = `
      <p class="search-error">Search failed: ${err.message}</p>
    `;
  }
}

function displaySearchResults(results, query) {
  const resultsDiv = document.getElementById('search-results');
  if (!resultsDiv) return;

  if (results.length === 0) {
    resultsDiv.innerHTML = `
      <p class="search-no-results">No messages found matching your search criteria.</p>
    `;
    return;
  }

  const queryLower = query.toLowerCase();
  
  let html = `<p class="search-count">Found ${results.length}${results.length >= 500 ? '+' : ''} messages</p>`;
  
  for (const msg of results.slice(0, 100)) {
    const link = SearchEngine.getMessageLink(msg);
    let content = escapeHtml(msg.x);
    
    // Highlight search term
    if (query) {
      const regex = new RegExp(`(${escapeRegExp(query)})`, 'gi');
      content = content.replace(regex, '<span class="search-result-highlight">$1</span>');
    }
    
    // Truncate long content
    if (content.length > 200) {
      // Try to show context around the match
      const matchIndex = content.toLowerCase().indexOf(queryLower);
      if (matchIndex > 100) {
        content = '...' + content.substring(matchIndex - 50);
      }
      if (content.length > 200) {
        content = content.substring(0, 200) + '...';
      }
    }

    html += `
      <a href="${link}" class="search-result" onclick="hideSearchModal()">
        <div class="search-result-header">
          <span class="search-result-author">${escapeHtml(msg.a)}</span>
          <span class="search-result-meta">
            <span class="search-result-channel">#${escapeHtml(msg.channelName)}</span>
            <span class="search-result-date">${msg.t}</span>
          </span>
        </div>
        <div class="search-result-content">${content}</div>
      </a>
    `;
  }

  if (results.length > 100) {
    html += `<p class="search-more">Showing first 100 results. Refine your search for more specific results.</p>`;
  }

  resultsDiv.innerHTML = html;
}

// ============================================
// Quick Search (Current Page)
// ============================================
document.addEventListener('DOMContentLoaded', function() {
  const searchInput = document.getElementById('search-input');
  if (searchInput) {
    let debounceTimer;
    
    searchInput.addEventListener('input', function(e) {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        const query = e.target.value.toLowerCase().trim();
        quickSearchPage(query);
      }, 150);
    });
  }

  // Initialize search engine in background
  SearchEngine.init();
  
  // Scroll to message if hash present
  if (window.location.hash) {
    setTimeout(() => {
      const target = document.querySelector(window.location.hash);
      if (target) {
        target.scrollIntoView({ behavior: 'smooth', block: 'center' });
        target.classList.add('message-highlighted');
        setTimeout(() => target.classList.remove('message-highlighted'), 3000);
      }
    }, 100);
  }
});

function quickSearchPage(query) {
  const messages = document.querySelectorAll('.message');
  let matchCount = 0;

  messages.forEach(msg => {
    const textEl = msg.querySelector('.message-text');
    if (!textEl) return;

    // Reset previous highlights
    const originalText = textEl.dataset.original || textEl.innerHTML;
    textEl.dataset.original = originalText;

    if (query.length < 2) {
      msg.style.display = 'flex';
      textEl.innerHTML = originalText;
      return;
    }

    const text = textEl.textContent.toLowerCase();
    if (text.includes(query)) {
      msg.style.display = 'flex';
      matchCount++;
      
      // Highlight matches
      const regex = new RegExp(`(${escapeRegExp(query)})`, 'gi');
      textEl.innerHTML = originalText.replace(regex, '<span class="search-result-highlight">$1</span>');
    } else {
      msg.style.display = 'none';
    }
  });

  // Update search box placeholder with count
  const searchInput = document.getElementById('search-input');
  if (searchInput && query.length >= 2) {
    searchInput.placeholder = `${matchCount} matches found`;
  } else if (searchInput) {
    searchInput.placeholder = 'Search messages...';
  }
}

// ============================================
// Utility Functions
// ============================================
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function escapeRegExp(string) {
  return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// ============================================
// Keyboard Shortcuts
// ============================================
document.addEventListener('keydown', function(e) {
  // Ctrl/Cmd + K to focus search
  if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
    e.preventDefault();
    const searchInput = document.getElementById('search-input');
    if (searchInput) searchInput.focus();
  }

  // Ctrl/Cmd + F for advanced search
  if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
    e.preventDefault();
    showSearchModal();
  }

  // Escape to close modal
  if (e.key === 'Escape') {
    hideSearchModal();
  }
  
  // Enter in search modal triggers search
  if (e.key === 'Enter') {
    const modal = document.getElementById('searchModal');
    if (modal && modal.style.display === 'block') {
      e.preventDefault();
      performSearch();
    }
  }
});

// ============================================
// Auto-reload (Optional)
// ============================================
let autoReloadEnabled = false;
let reloadInterval = null;

function enableAutoReload(intervalMinutes = 5) {
  if (autoReloadEnabled) return;

  autoReloadEnabled = true;
  reloadInterval = setInterval(() => {
    fetch(window.location.href)
      .then(response => response.text())
      .then(html => {
        if (html.length !== document.documentElement.outerHTML.length) {
          console.log('Page updated, reloading...');
          window.location.reload();
        }
      })
      .catch(err => console.error('Auto-reload check failed:', err));
  }, intervalMinutes * 60 * 1000);

  console.log(`Auto-reload enabled: every ${intervalMinutes} minutes`);
}

function disableAutoReload() {
  if (!autoReloadEnabled) return;
  clearInterval(reloadInterval);
  autoReloadEnabled = false;
  console.log('Auto-reload disabled');
}

// ============================================
// Console Info
// ============================================
console.log('Discord Archive Viewer loaded');
console.log('Keyboard shortcuts:');
console.log('  Ctrl/Cmd + K: Focus quick search');
console.log('  Ctrl/Cmd + F: Advanced search modal');
console.log('  Escape: Close modal');
console.log('  Enter: Submit search (in modal)');