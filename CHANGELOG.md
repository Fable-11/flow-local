# Changelog

Every release has a version number (shown in the app under the logo and by `python -m flow --version`)
and a git tag, so you can go back to any of them. See "Going back to an earlier version" in the README.

## 0.7.1 (not released yet)

- Fixed: two dictations in the same text ran together ("friendHello"). Two causes. When the app
  could not read what was before the cursor, it forgot that the first dictation had just put text
  there and added no space. And a dictation in Arabic next to English text (or the other way round)
  skipped the space altogether. A space is now added in both cases. The memory of the last dictation
  in a window also lasts 5 minutes instead of 2.

## 0.7.0

- **The AI cleanup says what state it is in.** Home shows one line: ready, resting, switched off in
  Settings, Ollama not running, or the model not installed, each with what to do. Before, an Ollama
  that was not running meant plain-rules cleanup with no sign of it. If Ollama is installed but not
  running there is a **Start Ollama** button. Nothing starts Ollama by itself: it uses graphics
  memory, so it only starts when you press the button.
- **Recovery tools in the tray menu.** *Copy last dictation* (for when it was pasted somewhere
  unexpected or not at all) and *Restore other sounds now*. A new command
  `python -m flow restore-sounds` does the second one from outside the app, and the Stop Flow Local
  shortcut runs it, so force-stopping the app during a recording cannot leave programs muted.
- **`python -m flow selftest`**: a silent check that the microphone, data folder, clipboard,
  cleanup rules, volume mixer, Ollama and the speech model all work. The test voice goes to a file
  (nothing is played aloud), your clipboard is put back, and the report contains no user name,
  device names or dictations, so it is safe to paste into a bug report. `--hardware` adds the
  speech model and device.

## 0.6.0

- **Other sounds go quiet while you dictate.** Music, videos and calls keep playing but are muted
  (or lowered) while you speak, so they are not mixed into what you say, and they come back the
  moment you stop. Settings > Microphone > Other sounds: mute, lower, or leave them alone. It works
  per program through the Windows volume mixer, never touches Flow Local's own sounds or anything
  you had already muted, and does not override a change you make in the mixer meanwhile. A small
  record on disk means that even after a crash the next start puts everything back. A quick tap, or
  the shortcut turning into hands-free mode, never makes anything flicker.
- **No more 8-second waits.** When the AI model was not in memory, the first cleanup waited for it
  to load, gave up after 8 seconds and used the plain rules anyway: a long wait for nothing. Now a
  model that is not loaded is skipped at once (0.04 s instead of 8 s, measured), the plain rules
  clean the text, and the model loads in the background for the next dictation. The AI model is also
  woken by asking Ollama whether it is really loaded, instead of guessing from a timer, and the
  wait for a loaded model is 5 seconds at most.
- **The text goes where you are when it is ready.** If you move to another window or screen while
  the dictation is processed (a search box, a chat), it is pasted there, with the paste method and
  spacing of that window. (0.4.0 copied it to the clipboard instead, which was in the way.)
- The log line of each dictation now shows where the time went (speech, cleanup, insert).

## 0.5.0

Preparation for a public release.

- Settings > Cleanup > Ollama port, for people whose own Ollama listens elsewhere. Only the port
  can change: the address stays on this computer.
- Defaults that fit other computers: a graphics card with under 3.5 GB gets the smaller speech
  model, one under 5 GB gets the lighter cleanup model. Only a card that was actually read counts,
  an unreadable one changes nothing.
- The lighter cleanup model (qwen2.5:3b) is marked as non-commercial wherever it is recommended.
- `python -m flow doctor` shortens your home folder to `~`, so the report can be pasted without
  your Windows user name.
- `scripts/setup.ps1` asks before downloading the speech model (with its size) and carries on if
  the download fails. `-NoModel` skips it.
- `scripts/stop_flow.ps1` only stops this project's own processes, and the interpreter they start.
- README: supported languages stated plainly, a with/without Ollama table, hardware table that
  matches the code, no claims that nothing checks. New SECURITY.md, CONTRIBUTING.md, issue and pull
  request templates, a manual CI workflow. Corrected licence notices.
- Test sentences are all invented, none are taken from real dictations.

## 0.4.0

- About 1.2 GB less video memory. On graphics cards with 8 GB or less (where the speech model and
  the AI model share the card) the speech model now runs in a smaller form: measured 1.1 GB instead
  of 2.3 GB, as fast or slightly faster, same text on the test clips. Bigger cards keep the most
  exact form. Settings > Memory > Speech model precision lets you choose either one yourself.
- Safer cursor reading: if an app is slow to answer, a selection could be left behind and the
  paste would replace your own text. The probe now looks twice and gives up if the window changes.
- If the keyboard focus moves to a different program while a dictation is processed, the text is
  copied (press Ctrl+V) instead of being pasted into an app you did not dictate into.
- If the microphone was unplugged or changed, recording reopens it once by itself.
- Clearer messages: "Clipboard busy", "Out of memory", "Took too long" instead of "Something went
  wrong".
- The language shown in the history now follows the text that was written, so English text is no
  longer labelled Arabic.
- The Hub window loads when it is first opened, which makes start-up lighter.

## 0.3.3

- Self-corrections are resolved by rules that work without the AI model: "send it to Ahmed, no no,
  I mean Omar" becomes "send it to Omar", "the red one, actually no, the blue one" keeps the blue
  one, "so I think we should, no no, what I want to say is..." drops the abandoned beginning, and
  "how to start, how to start, I mean" collapses. Names, days, Arabic words ("لا لا قصدي", "أقصد",
  "لا بل") and phrases that repeat the opening words are handled; numbers keep their own rules.
  Before this, a correction only worked for numbers or when the AI model answered in time, so long
  dictations often kept both versions.
- Careful by design: nothing is deleted when the phrase is part of the sentence ("I mean business",
  "no problem", "sorry for the delay"), when you are talking about the feature itself ("say no no I
  mean this"), inside quotes, or when the new part points back at earlier words ("send it to
  Omar"). Then both versions stay, or the AI model decides.
- "Scratch that" no longer deletes when it is only mentioned, and never erases a whole unpunctuated
  dictation (at most the last 12 words).
- The AI model is told to drop the abandoned words only when the speaker clearly takes them back,
  and to keep everything when unsure.

## 0.3.2

- Fixed English and Arabic in one dictation. The language is now taken from the audio, part by part
  (the recording is cut at pauses), instead of being fixed by the setting or by one guess for the
  whole recording. A language fixed in advance made the speech model invent text when the speech
  was in the other language: with the setting on Arabic, "use skill superpowers" came out as
  "subscribe to the channel" in Arabic, and the English at the end of a dictation turned into Arabic
  nonsense.
- The language setting is now "English and Arabic (automatic)", "English first" or "Arabic first":
  both languages are understood in every case and the choice only decides close calls.
- When the audio is unclear the app also tries the other language and keeps the more confident
  result. Stock invented phrases ("subscribe to the channel") are dropped instead of inserted.
- A recording that is all one language is still decoded in one pass, so its context is kept.

## 0.3.1

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
