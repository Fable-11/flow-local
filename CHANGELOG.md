# Changelog

Every release has a version number (shown in the app under the logo and by `python -m flow --version`)
and a git tag, so you can go back to any of them. See "Going back to an earlier version" in the README.

## 0.2.0 (not released yet)

- The dictionary can suggest words on the Flow Bar. A small prompt with Add and a close button
  lasts 10 seconds. It is rare on purpose: at most 3 a day, 10 minutes apart, and it backs off if
  ignored. A dismissed word is never offered again.
- Settings > Cleanup > Learn new words: add automatically, ask first, only list suggestions on the
  Dictionary page, or off.
- Look-alike words are fixed from context: "my I" becomes "my eye", "the Q" becomes "the queue",
  while "press the Q key", "Q and A" and "I think" are left alone.
- Settings > Display and sound > Show the Flow Bar on: new choice "Main screen only", and every
  connected monitor listed by its name (for example "Acme ...") to pin the bar to that one.
- Mixed English and Arabic: when pauses split a dictation into English and Arabic parts, each part
  is now written in its own script. Common phrases such as Assalamu alaikum and inshallah are
  written in Arabic even inside English text (Settings > Cleanup > Arabic phrases in Arabic script).
- Fixed: a short word said right as you press the shortcut lost its first syllable.
- Fixed: words said before pressing the shortcut could end up in the text.

## 0.1.1

- The dictionary learns recurring names and terms by itself.
- Names such as Claude, ChatGPT and GitHub are corrected from context.

## 0.1.0

- First release: offline dictation with hotkeys, Flow Bar, Hub, dictionary, snippets, Command Mode,
  history and insights.
