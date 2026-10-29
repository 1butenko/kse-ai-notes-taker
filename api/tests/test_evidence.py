"""Evidence for a topic: a short reading goes whole, so the topic's language can't lose it."""

import asyncio
import json

import httpx2

from app.notes import Chunk, Inputs, PlannedSection, PlannedTopic, Source
from app.worker.models import ModelSpec
from app.worker.openrouter import OpenRouterClient
from app.worker.sources import Retriever
from app.worker.topics import TOPIC_CANDIDATES, candidates_for, select_evidence

EIGEN = [
    "An eigenvalue of an operator T is a number lambda such that T v = lambda v.",
    "A vector v is an eigenvector of T corresponding to lambda when T v = lambda v.",
    "Eigenvectors corresponding to distinct eigenvalues are linearly independent.",
    "A subspace U is invariant under T if T u is in U for every u in U.",
]


def inputs(own: list[str], other: list[str] | None = None) -> Inputs:
    """Source 0 is the topic's reading, one chunk per page from PDF page 10; source 1 another."""
    chunks = [
        Chunk(
            id=f"b-p{10 + i}-0", source=0, file="book", pdf_page=10 + i, printed_page=None, text=t
        )
        for i, t in enumerate(own)
    ] + [
        Chunk(id=f"o-{i}", source=1, file="other", pdf_page=None, printed_page=None, text=t)
        for i, t in enumerate(other or [])
    ]

    def source(id: int, file: str) -> Source:
        ids = [c.id for c in chunks if c.source == id]
        return Source(
            id=id,
            file=file,
            title=file,
            label=None,
            pdf_start=None,
            pdf_end=None,
            sessions=[0],
            outline=[],
            chunk_ids=ids,
        )

    return Inputs(sources=[source(0, "book"), source(1, "other")], chunks=chunks, skipped=[])


def ukrainian_topic(key_terms: list[str] | None = None) -> PlannedTopic:
    return PlannedTopic(
        id="T1",
        title="Власні значення та власні вектори",
        sessions=[0],
        objectives=[
            "Означити власне значення оператора",
            "Довести, що власні вектори з різними власними значеннями лінійно незалежні",
        ],
        success_criteria=[],
        prerequisites=[],
        sources=[0],
        key_terms=key_terms or ["власне значення", "власний вектор", "інваріантний підпростір"],
    )


def query(topic: PlannedTopic) -> str:
    return " ".join([topic.title, *topic.key_terms, *topic.objectives])


def test_a_ukrainian_topic_gets_its_short_english_reading() -> None:
    data, topic = inputs(EIGEN), ukrainian_topic()
    retriever = Retriever(data.chunks)
    # Word search alone finds nothing: the topic and the book share no words.
    assert retriever.search(query(topic), TOPIC_CANDIDATES) == []

    found = candidates_for(topic, data, retriever)

    assert [c.id for c in found] == [f"b-p{10 + i}-0" for i in range(len(EIGEN))]


def test_a_long_reading_is_searched_and_needs_terms_in_its_language() -> None:
    filler = [f"Unrelated page {i} about polynomials and their degree." for i in range(40)]
    data = inputs(filler[:20] + EIGEN + filler[20:])
    retriever = Retriever(data.chunks)

    assert candidates_for(ukrainian_topic(), data, retriever) == []
    found = candidates_for(ukrainian_topic(["власне значення", "eigenvalue"]), data, retriever)
    assert 0 < len(found) <= TOPIC_CANDIDATES
    assert "b-p30-0" in {c.id for c in found}


def select(data: Inputs, topic: PlannedTopic, answer: dict, keep_reading: bool = True):
    seen: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        seen.append(body["messages"][-1]["content"])
        reply = {"choices": [{"message": {"content": json.dumps(answer)}}], "model": "m"}
        return httpx2.Response(200, json=reply)

    async def run():
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http:
            client = OpenRouterClient("https://openrouter.test/api/v1", "key", "m", http)
            section = PlannedSection(title="S", topics=[topic])
            return await select_evidence(
                client, ModelSpec("m"), section, topic, data, Retriever(data.chunks), keep_reading
            )

    evidence, gaps = asyncio.run(run())
    return evidence, gaps, seen


def choice(candidate: int, role: str, relevance: int = 5) -> dict:
    return {"candidate": candidate, "role": role, "relevance": relevance, "reason": "Why."}


def test_the_selector_only_tags_a_whole_reading() -> None:
    data = inputs(EIGEN, ["Eigenvalue examples: lambda for a diagonal operator T."])
    answer = {"selected": [choice(2, "theorem"), choice(4, "example", 4)], "gaps": []}

    evidence, _, [message] = select(data, ukrainian_topic(["eigenvalue"]), answer)

    assert "C0-C3 are the topic's whole reading and are all kept" in str(message)
    assert [e.chunk_id for e in evidence] == [
        "b-p10-0",
        "b-p11-0",
        "b-p12-0",
        "b-p13-0",
        "o-0",
    ]
    assert [e.role for e in evidence] == [
        "background",
        "background",
        "theorem",
        "background",
        "example",
    ]
    assert evidence[0].reason == "Part of the topic's assigned reading."


def test_without_keep_reading_the_selector_picks() -> None:
    answer = {"selected": [choice(2, "theorem")], "gaps": ["No example."]}

    evidence, gaps, [message] = select(inputs(EIGEN), ukrainian_topic(), answer, False)

    assert "whole reading" not in str(message)
    assert [e.chunk_id for e in evidence] == ["b-p12-0"] and gaps == ["No example."]
