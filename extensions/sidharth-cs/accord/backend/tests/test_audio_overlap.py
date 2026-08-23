"""Chunk-overlap dedupe.

Each audio chunk replays the previous chunk's last 1.5s so a word straddling
the boundary is heard whole at least once — live, "October 30th" split across
two independent Whisper calls came back as "October 3rd." then "30th.", and
"existing domain" became "existing products." The replay makes the first few
words of every transcript a repeat, which is removed here.
"""

from app.api.routes_audio import _dedupe_overlap


class _Session:
    pass


def _feed(lines):
    session = _Session()
    return [_dedupe_overlap(session, line) for line in lines]


def test_repeated_head_is_removed():
    out = _feed([
        "We need a modern responsive website",
        "responsive website where customers can browse products.",
    ])
    assert out[1] == "where customers can browse products."


def test_first_chunk_is_never_touched():
    out = _feed(["Hi, I'd like to discuss a website development project."])
    assert out[0] == "Hi, I'd like to discuss a website development project."


def test_no_overlap_leaves_text_intact():
    out = _feed([
        "Our total budget is $45,000.",
        "The deliverables include payment integration.",
    ])
    assert out[1] == "The deliverables include payment integration."


def test_casing_and_punctuation_of_the_remainder_survive():
    out = _feed([
        "and access to our existing",
        "existing domain. We expect weekly progress updates.",
    ])
    assert out[1] == "domain. We expect weekly progress updates."


def test_overlap_only_chunk_yields_nothing_new():
    out = _feed(["the website payment integration", "the website payment integration"])
    assert out[1] == ""


def test_a_long_genuine_repeat_is_not_swallowed_wholesale():
    # Bounded by _MAX_OVERLAP_WORDS so a speaker repeating themselves at
    # length still reaches the document.
    long_line = " ".join(f"word{i}" for i in range(40))
    out = _feed([long_line, long_line])
    assert out[1] != ""


def test_fuzzy_overlap_from_the_live_correction_run():
    """Whisper transcribes the SAME replayed audio differently on either
    side of a boundary, so exact word matching saw no overlap and the phrase
    was written into the document twice. These pairs are verbatim from a
    live run."""
    out = _feed([
        "The project should start on September 15th, and the final",
        "15, and the final website should be delivered by October 30.",
    ])
    assert out[1].startswith("website should be delivered")
    assert "and the final" not in out[1]

    out = _feed([
        "ongoing marketing, SEO, or content creation,",
        "EO or content creation after launch. We want a kick-off meeting.",
    ])
    assert out[1].startswith("after launch")


def test_fuzzy_matching_does_not_eat_unrelated_speech():
    out = _feed([
        "Our total budget is $45,000.",
        "The deliverables include payment integration.",
    ])
    assert out[1] == "The deliverables include payment integration."


# --- a pause inside a chunk has to be visible to the batcher ---------------
#
# The batcher closes a batch on a 7s silence gap. On the audio path a chunk
# arrives every 6s no matter what is in it, so that gap can never open: a
# speaker pausing between topics produces no signal at all, and batches close
# on the 15s ceiling instead — cutting wherever the clock lands.
#
# The Swift capture already skips chunks that are ENTIRELY silent, but a 2.5s
# pause inside a 6s chunk is not entirely silent, so nothing is skipped.
# Detecting a silent TAIL is what makes a real pause close a batch.

def test_a_silent_tail_is_detected():
    from app.api.routes_audio import ends_with_silence
    speech = [3000, -3000] * 48000          # 2s of loud audio at 48k
    quiet = [0] * 120000                    # 2.5s of silence — a topic pause
    assert ends_with_silence(speech + quiet, 48000)


def test_a_sentence_gap_is_not_a_topic_pause():
    """1.2s caught ordinary gaps between phrases. A live run fragmented into
    one-clause batches because of it — the budget correction was split across
    two batches and never applied."""
    from app.api.routes_audio import ends_with_silence
    speech = [3000, -3000] * 48000
    gap = [0] * 57600                       # 1.2s
    assert not ends_with_silence(speech + gap, 48000)


def test_continuous_speech_is_not_a_pause():
    from app.api.routes_audio import ends_with_silence
    assert not ends_with_silence([3000, -3000] * 48000, 48000)


def test_a_brief_gap_between_words_is_not_a_pause():
    """Word gaps are ~200ms. Treating those as topic boundaries would flush
    on every breath and put one sentence in each batch."""
    from app.api.routes_audio import ends_with_silence
    speech = [3000, -3000] * 24000
    tiny = [0] * 9600                       # 200ms
    assert not ends_with_silence(speech + tiny, 48000)


def test_an_all_silent_chunk_is_not_treated_as_a_pause():
    """Those are dropped upstream; treating them as boundaries would flush
    repeatedly on a muted mic."""
    from app.api.routes_audio import ends_with_silence
    assert not ends_with_silence([0] * 288000, 48000)
