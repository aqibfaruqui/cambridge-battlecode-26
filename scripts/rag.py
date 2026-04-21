#!/usr/bin/env python3
"""RAG tool for BattleCode docs: index with VoyageAI embeddings, answer with Claude."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import anthropic
import numpy as np
import voyageai
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs"
INDEX_DIR = ROOT / ".rag_index"

EMBEDDING_MODEL = "voyage-3-lite"
CLAUDE_MODEL = "claude-sonnet-4-6"
TOP_K = 5


# --- Chunking ---


def chunk_markdown(path: Path) -> list[dict]:
    """Split a markdown file into chunks by h2/h3 headings."""
    text = path.read_text()
    # Strip the Mintlify JSX/HTML noise that isn't useful for retrieval
    text = re.sub(r"<img [^>]+>", "", text)
    text = re.sub(r"export const \w+ = .*\n", "", text)

    lines = text.split("\n")
    chunks: list[dict] = []
    current_h1 = path.stem
    current_heading = ""
    current_lines: list[str] = []

    def flush():
        body = "\n".join(current_lines).strip()
        if body:
            heading_path = f"{current_h1} > {current_heading}" if current_heading else current_h1
            chunks.append(
                {
                    "source": path.name,
                    "heading": heading_path,
                    "text": body,
                }
            )

    for line in lines:
        if line.startswith("# ") and not line.startswith("## "):
            current_h1 = line.lstrip("# ").strip()
            continue
        if re.match(r"^#{2,3} ", line):
            flush()
            current_heading = line.lstrip("# ").strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    flush()
    return chunks


def load_all_chunks() -> list[dict]:
    chunks = []
    for path in sorted(DOCS_DIR.glob("*.md")):
        chunks.extend(chunk_markdown(path))
    return chunks


# --- Indexing ---


def build_index():
    """Embed all doc chunks and save to disk."""
    load_dotenv(ROOT / ".env")
    vo = voyageai.Client()

    chunks = load_all_chunks()
    if not chunks:
        print("No docs found in", DOCS_DIR)
        sys.exit(1)

    print(f"Chunked {len(chunks)} sections from {len(list(DOCS_DIR.glob('*.md')))} files")

    texts = [f"{c['heading']}\n\n{c['text']}" for c in chunks]

    # VoyageAI batch embed with retry on rate limit
    all_embeddings = []
    batch_size = 30
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        for attempt in range(6):
            try:
                result = vo.embed(batch, model=EMBEDDING_MODEL, input_type="document")
                all_embeddings.extend(result.embeddings)
                break
            except voyageai.error.RateLimitError:
                wait = 25 * (attempt + 1)
                print(f"  Rate limited, waiting {wait}s (attempt {attempt + 1}/6)...")
                time.sleep(wait)
        else:
            print("  Failed after 6 retries, aborting.")
            sys.exit(1)
        print(f"  Embedded {min(i + batch_size, len(texts))}/{len(texts)}")

    INDEX_DIR.mkdir(exist_ok=True)
    np.save(INDEX_DIR / "embeddings.npy", np.array(all_embeddings, dtype=np.float32))
    with open(INDEX_DIR / "chunks.json", "w") as f:
        json.dump(chunks, f)

    print(f"Index saved to {INDEX_DIR} ({len(chunks)} chunks)")


# --- Querying ---


def query_index(question: str, top_k: int = TOP_K) -> list[dict]:
    """Return the top-k most relevant chunks for a question."""
    load_dotenv(ROOT / ".env")
    vo = voyageai.Client()

    embeddings = np.load(INDEX_DIR / "embeddings.npy")
    with open(INDEX_DIR / "chunks.json") as f:
        chunks = json.load(f)

    q_emb = np.array(
        vo.embed([question], model=EMBEDDING_MODEL, input_type="query").embeddings[0],
        dtype=np.float32,
    )

    # Cosine similarity
    norms = np.linalg.norm(embeddings, axis=1)
    similarities = embeddings @ q_emb / (norms * np.linalg.norm(q_emb))
    top_indices = np.argsort(similarities)[-top_k:][::-1]

    results = []
    for idx in top_indices:
        chunk = chunks[idx].copy()
        chunk["score"] = float(similarities[idx])
        results.append(chunk)
    return results


def ask(question: str, top_k: int = TOP_K):
    """Retrieve relevant docs and answer the question with Claude."""
    load_dotenv(ROOT / ".env")

    results = query_index(question, top_k)

    context_parts = []
    for r in results:
        context_parts.append(f"### {r['heading']} (from {r['source']}, score={r['score']:.3f})\n\n{r['text']}")
    context = "\n\n---\n\n".join(context_parts)

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2048,
        system=(
            "You are an expert on Cambridge BattleCode. "
            "Answer the user's question using ONLY the provided documentation excerpts. "
            "If the answer isn't in the excerpts, say so. "
            "Be concise and cite specific API methods or game constants when relevant."
            "Your output format should not contain prose. List relevant API methods and constraints in bullet points."
        ),
        messages=[
            {
                "role": "user",
                "content": f"## Documentation excerpts\n\n{context}\n\n## Question\n\n{question}",
            }
        ],
    )
    print(response.content[0].text)


# --- CLI ---


def main():
    parser = argparse.ArgumentParser(description="RAG tool for BattleCode docs")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("index", help="Build the embedding index from docs/")

    ask_parser = sub.add_parser("ask", help="Ask a question about the docs")
    ask_parser.add_argument("question", nargs="+", help="Your question")
    ask_parser.add_argument("-k", "--top-k", type=int, default=TOP_K, help="Number of chunks to retrieve")

    args = parser.parse_args()

    if args.command == "index":
        build_index()
    elif args.command == "ask":
        question = " ".join(args.question)
        ask(question, top_k=args.top_k)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
