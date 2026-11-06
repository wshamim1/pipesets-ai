# Chat link on a website

`index.html` is a sample website with a Pipesets chat link embedded two ways:

- **Inline** — the chat in a box on the page (`<iframe>`).
- **Chat button** — a round button in the bottom-right corner that opens the chat in a panel. The
  chat loads on the first click, so visitors who never open it don't start a session.

Both are plain HTML, CSS and a few lines of JavaScript; nothing is loaded from Pipesets except the
chat page itself.

## Try it

1. In Pipesets, open a published pipeline → **Chat link** → create a link →
   **Embed on a website** → **Download sample page**. That file is this page with your link filled
   in. Or edit `index.html` here and replace `https://YOUR-PUBLIC-HOST/c/pc_YOUR_LINK_TOKEN` (it
   appears twice) with your link.
2. Open the file in a browser, or serve the folder: `python3 -m http.server 8080` and go to
   <http://localhost:8080>.

A link made on `localhost` only works in a browser on the same computer. For a real website, use a
link from a deployed server (see DEPLOYMENT.md, "Exposing it"); behind the edge proxy chat links
are served on the public host.

The embedded chat behaves like the link: same limits, each visitor's own conversation, and turning
the link off stops it on every site. `index.html` is generated from
`frontend/src/utils/chatEmbed.ts` (a frontend test checks they match); regenerate it after changing
the snippets:

```bash
node --input-type=module -e "
import { samplePage } from './frontend/src/utils/chatEmbed.ts';
import { writeFileSync } from 'node:fs';
writeFileSync('examples/chat-embed/index.html', samplePage('https://YOUR-PUBLIC-HOST/c/pc_YOUR_LINK_TOKEN', 'Support assistant'));
"
```
