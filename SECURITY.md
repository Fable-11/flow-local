# Security

Flow Local listens to the keyboard and microphone, reads and writes the clipboard, and sends
keystrokes to other programs, so it is worth reading how it behaves.

## What it does and does not do

- **No network use** except two things you start yourself: the one-time speech model download
  (Hugging Face) and the connection to your own Ollama server on `127.0.0.1`. The Ollama address
  is refused if it is not a local address.
- **Audio is never written to disk.** It is kept in memory while you speak and dropped after it is
  turned into text.
- **Your text stays on your PC** in `%LOCALAPPDATA%\FlowLocal` (settings, dictionary, history).
  History can be switched off or cleared in the app.
- **The keyboard hook** only watches for the shortcut you chose. It does not record what you type.
- **The clipboard** is saved before a paste and restored after. A copy of it is journalled on
  disk for a moment so a crash cannot lose it.
- **Reading text near the cursor** (to fit capitals and full stops) sends Shift+Arrow and Ctrl+C
  to a short list of well-behaved programs, never to terminals or code editors, and never when text
  is selected. It can be switched off in Settings.

## Reporting a problem

Please use GitHub's private vulnerability reporting (the **Security** tab of this repository,
"Report a vulnerability") and do not include recordings or private text. If that is not available,
open an issue that describes the problem without exploit details and ask for a private channel.

There is no bug bounty. Fixes are made on a best-effort basis.
