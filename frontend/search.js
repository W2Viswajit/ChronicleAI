/* Keep cooldown feedback visible without rerendering the user's input each second. */
(() => {
  const previousRender = render, previousAdd = addInput;
  let until = Number(sessionStorage.getItem('newsCooldownUntil')) || 0;
  let range = 'Past 7 days', limit = 'Up to 10 articles', lastSearch = null;
  const remaining = () => Math.max(0, Math.ceil((until - Date.now()) / 1000));

  function updateCooldown() {
    if (page !== 'input' || mode !== 'topic' || busy) return;
    const seconds = remaining();
    const button = document.querySelector('.footer button.primary');
    if (button) {
      button.disabled = seconds > 0;
      button.innerHTML = seconds ? `Search ready in ${seconds}s` : 'Find articles' + ic('arrow');
    }
    const status = document.getElementById('news-cooldown');
    if (status) {
      status.hidden = !seconds;
      status.textContent = seconds ? `News provider is taking a short break. Search unlocks in ${seconds}s. You can use article URLs or text meanwhile.` : '';
    }
  }

  render = function () {
    range = document.getElementById('range')?.value || range;
    limit = document.getElementById('limit')?.value || limit;
    previousRender();
    if (page !== 'input') return;
    if (document.getElementById('range')) document.getElementById('range').value = range;
    if (document.getElementById('limit')) document.getElementById('limit').value = limit;
    const section = document.querySelector('.sectiontitle');
    if (mode === 'topic') section.insertAdjacentHTML('beforebegin', '<p id="news-cooldown" class="callout" role="status" hidden></p>');
    if (lastSearch) {
      section.insertAdjacentHTML('beforebegin', `<div class="callout" role="status"><span>${esc(lastSearch.summary)}</span></div>`);
      if (lastSearch.issues.length) section.insertAdjacentHTML('beforebegin', `<details class="notice"><summary>${lastSearch.issues.length} retrieval notices</summary>${lastSearch.issues.map(s => `<p>${esc(s)}</p>`).join('')}</details>`);
    }
    updateCooldown();
  };

  addInput = async function () {
    if (busy) return;
    if (mode !== 'topic') return previousAdd();
    if (remaining()) { updateCooldown(); return; }
    if (!topic.trim()) { toast('Enter a news topic first.'); return; }
    range = document.getElementById('range').value;
    limit = document.getElementById('limit').value;
    const body = {topic: topic.trim(), days: range.includes('30') ? 30 : range.includes('24') ? 1 : 7,
      limit: parseInt(limit.match(/\d+/)[0])};
    busy = true;
    lastSearch = null;
    progressText = 'Finding and extracting articles. Requests are paced automatically; a provider retry may take a minute.';
    render();
    try {
      const data = await api('/articles/search', body);
      let added = 0;
      for (const article of data.articles) {
        if (articles.length >= 10) break;
        if (!articles.some(a => a.text === article.text)) { articles.push({...article, selected:true}); added++; }
      }
      until = Date.now() + Math.max(0, data.retry_after_seconds || 0) * 1000;
      sessionStorage.setItem('newsCooldownUntil', String(until));
      const complete = data.search_status === 'ok';
      lastSearch = {
        summary: complete ? `${body.topic}: ${data.articles.length} readable articles found, ${added} added via ${data.search_provider || 'news search'}${data.search_cached ? ' (cached search)' : ''}.` : `${body.topic}: search temporarily unavailable. ${remaining() ? 'The countdown shows when you can retry.' : 'Please try again later.'}`,
        issues: [...(data.warnings || []), ...(data.skipped || []).map(s => `${s.url}: ${s.reason}`)]
      };
      demo = false; result = null; serverResult = null;
      toast(lastSearch.summary);
    } catch (error) {
      lastSearch = {summary: 'Search could not complete. Check that the local backend is running.', issues:[error.message]};
      toast(lastSearch.summary);
    } finally { busy = false; render(); }
  };
  setInterval(updateCooldown, 1000);
  render();
})();
