// Snippets for putting a chat link on another website (Chat link dialog → Embed on a website).
// Everything is plain HTML / CSS / JS the site owner pastes in: no script is loaded from Pipesets.
// examples/chat-embed/index.html is a full sample page built from the same snippets.

const escapeHtml = (s: string) =>
  s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

/** The chat page in embed mode: no background, card or margins (frontend/src/chat/main.tsx). */
export const embedUrl = (chatUrl: string) => `${chatUrl}${chatUrl.includes('?') ? '&' : '?'}embed=1`

/** The chat inline, in a box on the page. */
export function iframeSnippet(chatUrl: string, title: string): string {
  return `<iframe
  src="${escapeHtml(embedUrl(chatUrl))}"
  title="${escapeHtml(title)}"
  style="width: 100%; max-width: 440px; height: 620px; border: 1px solid #e2e8f0; border-radius: 16px;"
  allow="clipboard-write"
></iframe>`
}

/** A round chat button in the bottom-right corner that opens the chat in a panel (and turns into a
 *  close button). The iframe loads on the first click, so visitors who never open it don't start a
 *  chat session. */
export function bubbleSnippet(chatUrl: string, title: string): string {
  return `<!-- Pipesets chat button: paste before </body> -->
<div id="pipesets-chat">
  <div id="pipesets-chat-panel" role="dialog" aria-label="${escapeHtml(title)}" hidden>
    <iframe id="pipesets-chat-frame" title="${escapeHtml(title)}" allow="clipboard-write"
            data-src="${escapeHtml(embedUrl(chatUrl))}"></iframe>
  </div>
  <button type="button" id="pipesets-chat-toggle" aria-label="Open chat: ${escapeHtml(title)}" aria-expanded="false">
    <svg class="pc-icon-open" width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
    </svg>
    <svg class="pc-icon-close" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         stroke-width="2.4" stroke-linecap="round" aria-hidden="true">
      <path d="M18 6 6 18M6 6l12 12"/>
    </svg>
  </button>
</div>
<style>
  #pipesets-chat-toggle {
    position: fixed; right: 20px; bottom: 20px; z-index: 2147483000;
    width: 60px; height: 60px; border: none; border-radius: 50%; cursor: pointer;
    background: linear-gradient(135deg, #4f46e5, #7c3aed); color: #fff;
    box-shadow: 0 10px 30px rgba(79, 70, 229, 0.35);
    display: flex; align-items: center; justify-content: center;
  }
  #pipesets-chat-toggle .pc-icon-close { display: none; }
  #pipesets-chat[data-open] .pc-icon-open { display: none; }
  #pipesets-chat[data-open] .pc-icon-close { display: block; }
  #pipesets-chat-panel {
    position: fixed; right: 20px; bottom: 92px; z-index: 2147483000;
    width: 400px; height: min(640px, calc(100vh - 120px));
    border-radius: 18px; overflow: hidden; background: #fff;
    box-shadow: 0 24px 60px rgba(15, 23, 42, 0.25);
  }
  #pipesets-chat-panel[hidden] { display: none; }
  #pipesets-chat-frame { width: 100%; height: 100%; border: none; }
  @media (max-width: 520px) {
    #pipesets-chat-panel { top: 0; right: 0; bottom: 92px; width: 100vw; height: auto; border-radius: 0 0 18px 18px; }
  }
</style>
<script>
  (function () {
    var root = document.getElementById('pipesets-chat');
    var panel = document.getElementById('pipesets-chat-panel');
    var frame = document.getElementById('pipesets-chat-frame');
    var toggle = document.getElementById('pipesets-chat-toggle');
    var label = toggle.getAttribute('aria-label');
    function setOpen(open) {
      if (open && !frame.src) frame.src = frame.getAttribute('data-src');
      panel.hidden = !open;
      toggle.setAttribute('aria-expanded', String(open));
      toggle.setAttribute('aria-label', open ? 'Close chat' : label);
      if (open) root.setAttribute('data-open', ''); else root.removeAttribute('data-open');
    }
    toggle.addEventListener('click', function () { setOpen(panel.hidden); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') setOpen(false); });
  })();
</script>`
}

/** A whole page to try both snippets: open it in a browser (or serve it) to see the chat embedded. */
export function samplePage(chatUrl: string, title: string): string {
  const t = escapeHtml(title)
  const indent = (s: string, n: number) => s.split('\n').map((l) => ' '.repeat(n) + l).join('\n')
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>${t} — embedded chat example</title>
  <style>
    body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
           color: #0f172a; background: #f8fafc; line-height: 1.6; }
    header { padding: 20px 24px; background: #0f172a; color: #fff; }
    header h1 { margin: 0; font-size: 1.2rem; }
    main { max-width: 1040px; margin: 0 auto; padding: 32px 24px 120px;
           display: grid; grid-template-columns: 1fr 440px; gap: 40px; align-items: start; }
    @media (max-width: 900px) { main { grid-template-columns: 1fr; } }
    code { background: #e2e8f0; padding: 1px 6px; border-radius: 4px; }
  </style>
</head>
<body>
  <header><h1>Your website</h1></header>
  <main>
    <section>
      <h2>Chat with ${t}</h2>
      <p>This page shows two ways to put the chat on a website:</p>
      <ol>
        <li><strong>Inline</strong> — the chat in a box on the page (right).</li>
        <li><strong>Chat button</strong> — the round button in the bottom-right corner opens the chat in a panel.</li>
      </ol>
      <p>Copy the part you need from this file's source into your own pages. Each visitor gets their own
         conversation; nothing else is shared with Pipesets.</p>
    </section>
    <aside>
${indent(iframeSnippet(chatUrl, title), 6)}
    </aside>
  </main>

${indent(bubbleSnippet(chatUrl, title), 2)}
</body>
</html>
`
}
