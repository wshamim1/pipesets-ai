// Entry for chat.html: the page a public chat link (/c/<token>) opens. Separate from the builder's
// bundle so a phone loads only the chat.
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './chat-page.css'
import { ChatPage } from './ChatPage'
import { tokenFromPath } from './chatApi'

const token = tokenFromPath(window.location.pathname)

// ?embed=1: inside another website's iframe (Chat link → Embed on a website). The chat fills the
// frame: no page background, card or margins.
if (new URLSearchParams(window.location.search).has('embed')) document.documentElement.classList.add('cp-embed')

createRoot(document.getElementById('chat-root')!).render(
  <StrictMode>
    {token
      ? <ChatPage token={token} />
      : <div className="cp-page"><div className="cp-shell"><div className="cp-center">
          <p className="cp-center-title">Chat unavailable</p>
          <p>This link is incomplete — check that you copied all of it.</p></div></div></div>}
  </StrictMode>,
)
