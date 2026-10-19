"""The automatic matching must never rewrite ordinary sentences, whatever is in the dictionary."""

from __future__ import annotations

import pytest

from flow.store.db import Database
from flow.store.dictionary import DictionaryStore

WORDS = [
    "Kubernetes", "Pygame", "GitHub", "faster-whisper", "Anthropic", "Postgres", "Terraform",
    "Cloudflare", "Docker", "TypeScript", "JavaScript", "Tailwind", "Notion", "Figma", "Obsidian",
    "Whisper", "Ollama", "Nginx", "Grafana", "Jenkins", "Supabase", "Vercel", "Linear",
    "Stripe", "Twilio", "Mongoose", "Express", "Django", "Flask", "Laravel", "Webpack",
]

SENTENCES = [
    "I will send you the report after lunch and we can talk about the plan",
    "She wrote a long letter to her mother about the new house near the river",
    "Can you open the page and tell me what the title says at the top",
    "The weather was cold so we stayed inside and played a game of cards",
    "He drove his truck across the bridge and parked next to the old church",
    "We need to deploy the update before the end of the week or the client will complain",
    "My brother lives in a small town where everyone knows each other",
    "The doctor said I should drink more water and sleep at least eight hours",
    "Please remind me to call the bank tomorrow morning about the card",
    "They built a new road through the forest last summer despite the protests",
    "Could you check the numbers again because something looks wrong in the totals",
    "The teacher asked the students to read the chapter and write a short summary",
    "I lost my keys somewhere between the car and the front door",
    "We watched a movie about a whale that swam across the entire ocean",
    "Let us meet at the station at nine and take the early train to the coast",
    "The software engineer fixed the bug and wrote a test to prevent it again",
    "Express your thoughts clearly and the meeting will be much shorter",
    "The flask of coffee stayed warm all day on the long journey",
    "A linear model fits the data well but the nonlinear one is better",
    "Whisper the answer so nobody else can hear it in the library",
    "He ordered a stripe pattern shirt and a plain tie for the interview",
    "The mongoose is a quick animal that hunts snakes in the grass",
    "Notion of time changes when you travel across many time zones",
    "The tailwind helped the plane land twenty minutes ahead of schedule",
    "Our jenkins family reunion is next month at the lake house",
    "The supervisor approved the vacation request without any questions",
    "Doctors recommend regular exercise and a balanced diet for a healthy heart",
    "The company announced that it will open three new offices in Europe next year",
    "Please cloud the details less and give me the simple version",
    "I think the docker is full of boxes ready to ship tomorrow",
    "The postman delivered a package to the wrong address again today",
    "Grammar and spelling matter when you write a formal email to a client",
    "The figure in the painting looked almost real under the soft light",
    "Obstacles are part of every project and teams learn to overcome them together",
    "Hello, how are you doing today? I hope everything is going well with your work",
    "Assalamu alaikum, I wanted to ask about the schedule for next week",
    "Thanks for the quick reply; I will review the document tonight and answer soon",
    "Whatever you decide I will support the decision and help with the next steps",
    "The kitchen smelled of fresh bread and coffee when we came downstairs",
]


@pytest.fixture(scope="module")
def d():
    store = DictionaryStore(Database())
    for w in WORDS:
        store.add(w)
    return store


@pytest.mark.parametrize("sentence", SENTENCES)
def test_ordinary_sentence_is_not_rewritten(d, sentence):
    out, hits = d.apply_replacements(sentence)
    # only capitalisation of dictionary words themselves may change; no other word may be swapped
    assert out.lower() == sentence.lower(), (sentence, out, hits)


def test_a_blocked_pair_is_never_replaced_again_and_can_be_allowed_again(d):
    heard = "we use cuber nettys here"
    assert d.apply_replacements(heard)[0] == "we use Kubernetes here"
    log = d.replacement_log()
    assert [(r.heard, r.written, r.blocked) for r in log] == [("cuber nettys", "Kubernetes", False)]
    d.set_replacement_blocked("cuber nettys", "Kubernetes", True)
    assert d.apply_replacements(heard)[0] == heard
    assert d.apply_replacements("kubernetes works")[0] == "Kubernetes works"  # casing still fixed
    d.set_replacement_blocked("cuber nettys", "Kubernetes", False)
    assert d.apply_replacements(heard)[0] == "we use Kubernetes here"


def test_learned_words_never_cause_sound_replacements():
    store = DictionaryStore(Database())
    store.add("Kubernetes", auto=True)
    assert store.apply_replacements("on cuber nettys")[0] == "on cuber nettys"
    assert store.apply_replacements("on kubernetes")[0] == "on Kubernetes"
