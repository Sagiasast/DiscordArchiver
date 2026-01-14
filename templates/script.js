// Discord Archive Scripts

// Search modal
function showSearchModal() {
  document.getElementById('searchModal').style.display = 'block';
}

function hideSearchModal() {
  document.getElementById('searchModal').style.display = 'none';
}

// Close modal when clicking outside
window.onclick = function (event) {
  const modal = document.getElementById('searchModal');
  if (event.target === modal) {
    modal.style.display = 'none';
  }
};

// Simple search in current page
document.addEventListener('DOMContentLoaded', function () {
  const searchInput = document.getElementById('search-input');
  if (searchInput) {
    searchInput.addEventListener('input', function (e) {
      const query = e.target.value.toLowerCase();
      if (query.length < 2) return;

      const messages = document.querySelectorAll('.message-text');
      messages.forEach((msg) => {
        const text = msg.textContent.toLowerCase();
        const messageDiv = msg.closest('.message');

        if (text.includes(query)) {
          messageDiv.style.display = 'flex';
          // Highlight
          const regex = new RegExp(`(${query})`, 'gi');
          const highlighted = msg.innerHTML.replace(
            regex,
            '<span class="search-result-highlight">$1</span>'
          );
          msg.innerHTML = highlighted;
        } else {
          messageDiv.style.display = 'none';
        }
      });
    });
  }
});

// Advanced search function
async function performSearch() {
  const searchText = document.getElementById('search-text').value.toLowerCase();
  const searchAuthor = document.getElementById('search-author').value.toLowerCase();
  const dateFrom = document.getElementById('search-date-from').value;
  const dateTo = document.getElementById('search-date-to').value;

  const resultsDiv = document.getElementById('search-results');
  resultsDiv.innerHTML =
    '<p style="color: #72767d; text-align: center; padding: 20px;">Searching across all text files...</p>';

  // In a real implementation, this would search through message.txt files
  // For now, show a placeholder message
  setTimeout(() => {
    resultsDiv.innerHTML = `
      <p style="color: #72767d; text-align: center; padding: 20px;">
        Advanced search functionality requires server-side processing.<br>
        Use the quick search box to search within the current page,<br>
        or use your OS file search to search through messages.txt files.
      </p>
    `;
  }, 500);
}

// Auto-reload functionality (for live updates)
let autoReloadEnabled = false;
let reloadInterval = null;

function enableAutoReload(intervalMinutes = 5) {
  if (autoReloadEnabled) return;

  autoReloadEnabled = true;
  reloadInterval = setInterval(() => {
    // Check if page has been updated
    fetch(window.location.href)
      .then((response) => response.text())
      .then((pageHtml) => {
        // Simple check: compare content length
        if (pageHtml.length !== document.documentElement.outerHTML.length) {
          console.log('Page updated, reloading...');
          window.location.reload();
        }
      })
      .catch((err) => console.error('Auto-reload check failed:', err));
  }, intervalMinutes * 60 * 1000);

  console.log(`Auto-reload enabled: checking every ${intervalMinutes} minutes`);
}

function disableAutoReload() {
  if (!autoReloadEnabled) return;

  clearInterval(reloadInterval);
  autoReloadEnabled = false;
  console.log('Auto-reload disabled');
}

// Image lazy loading optimization
document.addEventListener('DOMContentLoaded', function () {
  const images = document.querySelectorAll('img[loading="lazy"]');

  if ('IntersectionObserver' in window) {
    const imageObserver = new IntersectionObserver((entries, observer) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          const img = entry.target;
          img.src = img.dataset.src || img.src;
          observer.unobserve(img);
        }
      });
    });

    images.forEach((img) => imageObserver.observe(img));
  }
});

// Keyboard shortcuts
document.addEventListener('keydown', function (e) {
  // Ctrl/Cmd + F to focus search
  if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
    e.preventDefault();
    const searchInput = document.getElementById('search-input');
    if (searchInput) searchInput.focus();
  }

  // Ctrl/Cmd + K for advanced search
  if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
    e.preventDefault();
    showSearchModal();
  }

  // Escape to close modal
  if (e.key === 'Escape') {
    hideSearchModal();
  }
});

console.log('Discord Archive Viewer loaded');
console.log('Keyboard shortcuts:');
console.log('  Ctrl/Cmd + F: Focus search');
console.log('  Ctrl/Cmd + K: Advanced search');
console.log('  Escape: Close modal');
