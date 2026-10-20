# Changelog

Every release has a version number (shown in the app under the logo and by `python -m flow --version`)
and a git tag, so you can go back to any of them. See "Going back to an earlier version" in the README.

## 0.3.1 (not released yet)

- Symbols said aloud are written as the symbol: "underscore" becomes _, "at sign" (also heard as
  "add sign" or "at the rate") becomes @, "hashtag", "dollar sign", "percent sign", "ampersand",
  "plus sign", "equals sign", brackets and "back slash" likewise. "dot" becomes a dot where that is
  clearly meant ("index dot js", "three dot five"), and "slash" in pairs like "yes slash no".
- "at gmail dot com" (also yahoo, outlook, hotmail, icloud and similar) becomes @gmail.com, so
  "john underscore smith at sign gmail dot com" gives john_smith@gmail.com.
- Results such as user_name, #flow, index.js or a/b are protected from the cleanup step, so they
  keep their exact spelling and are not capitalised.
- Ordinary sentences are left alone: "she put a dot on the map", "the at sign is on my keyboard".
  Controlled by Settings > Cleanup > Spoken commands.

## 0.3.0

- Dictionary words are now replaced automatically when the speech model writes something that
  sounds like them ("cuber nettys" becomes the word you added), without typing a spoken form.
  It is strict on purpose: only words you added yourself, one word must be a near-typo, and
  several words must have the same consonant sounds. Every replacement is listed on the Dictionary
  page under Automatic replacements, where "Stop this replacement" ends a wrong one for good.
- Learned words only change capitalisation. They no longer steer the speech model until they have
  been used twice, so a wrongly learned word cannot make correct speech come out wrong.
- Links and email addresses said aloud are written as typed: "github dot com slash flow" becomes
  github.com/flow, "sara at gmail dot com" becomes sara@gmail.com. They are no longer capitalised
  or given a full stop.
- Dictating in the middle of text: the first letter, the spaces and the final full stop now fit the
  text around the cursor (no stray capital or dot in the middle of a sentence). It reads the
  characters next to the cursor in browsers, Word, Outlook, Slack, Discord, Teams, WhatsApp and a
  few other apps, never when text is selected, and puts the cursor and clipboard back. Switch off
  in Settings > Cleanup > Fit to the text around the cursor.

## 0.2.0

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
