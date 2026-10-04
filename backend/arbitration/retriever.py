"""Historical Candidate Retriever for Vortex Terminal.

Retrieves candidate answers from previous conversations, tasks, verified procedures,
and experiences stored in the workspace database.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from typing import Any

from .types import Provenance


_STOP_WORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "aren't", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can", "can't", "cannot", "could",
    "couldn't", "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down",
    "during", "each", "few", "for", "from", "further", "had", "hadn't", "has",
    "hasn't", "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her",
    "here", "here's", "hers", "herself", "him", "himself", "his", "how", "how's",
    "i", "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it",
    "it's", "its", "itself", "let's", "me", "more", "most", "mustn't", "my",
    "myself", "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other",
    "ought", "our", "ours", "ourselves", "out", "over", "own", "same", "shan't",
    "she", "she'd", "she'll", "she's", "should", "shouldn't", "so", "some", "such",
    "than", "that", "that's", "the", "their", "theirs", "them", "themselves",
    "then", "there", "there's", "these", "they", "they'd", "they'll", "they're",
    "they've", "this", "those", "through", "to", "too", "under", "until", "up",
    "very", "was", "wasn't", "we", "we'd", "we'll", "we're", "we've", "were",
    "weren't", "what", "what's", "when", "when's", "where", "where's", "which",
    "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would",
    "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours",
    "yourself", "yourselves", "please", "can", "help",
}


def _tokenize(text: str) -> list[str]:
    """Tokenize text into lower-cased alphanumeric words and technical terms."""
    if not text:
        return []
    tokens = re.findall(r"[a-z0-9][a-z0-9_.:\-/#]*[a-z0-9]|[a-z0-9]", text.lower())
    return [t for t in tokens if len(t) > 1 and t not in _STOP_WORDS]


def _ngrams(tokens: list[str], n: int = 2) -> set[str]:
    """Generate token n-grams for semantic phrase matching."""
    if len(tokens) < n:
        return set()
    return {" ".join(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def _extract_technical_entities(text: str) -> set[str]:
    """Extract key technical entities like tool names, paths, configs, and model identifiers."""
    entities = set()
    # Model IDs like qwen2.5:3b, gemma3:4b, llama3.2:3b
    models = re.findall(r"\b[a-z0-9_.-]+:[0-9]+[a-z0-9_.-]*\b", text.lower())
    entities.update(models)
    # File paths and system endpoints
    paths = re.findall(r"(?:/[\w.-]+)+|~/(?:[\w.-]+/)*[\w.-]+", text)
    entities.update([p.lower() for p in paths])
    # Port patterns e.g. 11434, 8080, 5432
    ports = re.findall(r"\b(?:port\s+)?(\d{2,5})\b", text.lower())
    entities.update(ports)
    # Technical keywords
    tech_terms = re.findall(
        r"\b(ollama|qwen|gemini|groq|systemd|systemctl|journalctl|docker|podman|apt|dpkg|"
        r"cgroups|vram|ram|cpu|memory|swap|nvidia|nim|modelscope|cloudflare|api_key|"
        r"bearer|token|loopback|localhost|127\.0\.0\.1|tls|ssl|vortex|guardian)\b",
        text.lower()
    )
    entities.update(tech_terms)
    return entities


def compute_lexical_similarity(query: str, target: str) -> float:
    """Compute BM25-like token & entity overlap between query and historical target."""
    q_tokens = _tokenize(query)
    t_tokens = _tokenize(target)
    if not q_tokens or not t_tokens:
        return 0.0

    q_set = set(q_tokens)
    t_set = set(t_tokens)
    overlap = len(q_set & t_set)

    # Sub-token / stem overlap (e.g. 'optimiz' in 'optimize', 'start' in 'starting')
    soft_overlap = 0
    for q in q_set:
        if q not in t_set and any(q in t or t in q for t in t_set if len(q) >= 4 and len(t) >= 4):
            soft_overlap += 1

    total_overlap = overlap + (soft_overlap * 0.5)
    if total_overlap == 0:
        return 0.0

    # Token overlap ratio (Jaccard + Dice hybrid)
    token_sim = (2.0 * total_overlap) / (len(q_set) + len(t_set))

    # Entity overlap bonus
    q_entities = _extract_technical_entities(query)
    t_entities = _extract_technical_entities(target)
    entity_sim = 0.0
    if q_entities:
        e_overlap = len(q_entities & t_entities)
        entity_sim = e_overlap / len(q_entities)

    # N-gram phrase overlap bonus
    q_bi = _ngrams(q_tokens, 2)
    t_bi = _ngrams(t_tokens, 2)
    ngram_sim = 0.0
    if q_bi and t_bi:
        ngram_sim = len(q_bi & t_bi) / len(q_bi)

    # Weighted composite similarity
    score = (token_sim * 0.45) + (entity_sim * 0.40) + (ngram_sim * 0.15)
    return min(1.0, max(0.0, score))


class HistoricalCandidateRetriever:
    """Searches workspace database for previous answers and validated execution solutions."""

    def __init__(self, workspace: Any = None, store: Any = None):
        self.workspace = workspace
        self.store = store or (workspace.store if workspace else None)

    def retrieve(
        self,
        request: str,
        *,
        conversation_id: str | None = None,
        limit: int = 5,
        min_relevance: float = 0.20,
    ) -> list[dict[str, Any]]:
        """Retrieve top historical candidates relevant to the user request."""
        if not request or not request.strip():
            return []

        raw_candidates: list[dict[str, Any]] = []

        # 1. Search messages & previous turns from Workspace/Store
        raw_candidates.extend(self._retrieve_from_messages(request, conversation_id))

        # 2. Search tasks & completed operations
        raw_candidates.extend(self._retrieve_from_tasks(request))

        # 3. Search validated experiences & procedures
        raw_candidates.extend(self._retrieve_from_procedures(request))

        # 4. Search reports & memories
        raw_candidates.extend(self._retrieve_from_memories(request))

        # Filter, score relevance, and deduplicate
        scored: list[dict[str, Any]] = []
        for candidate in raw_candidates:
            ans_text = candidate.get("answer", "")
            orig_req = candidate.get("original_request", "")
            combined_target = f"{orig_req}\n{ans_text}"

            relevance = compute_lexical_similarity(request, combined_target)
            # Thread proximity bonus if from the same conversation
            if conversation_id and candidate.get("provenance", {}).get("conversation_id") == conversation_id:
                relevance = min(1.0, relevance * 1.15)

            if relevance >= min_relevance:
                candidate["relevance"] = relevance
                scored.append(candidate)

        # De-duplicate similar answers (grouping duplicates while retaining best verified version)
        deduped = self._deduplicate_candidates(scored)

        # Sort by relevance descending, prioritizing verified execution
        deduped.sort(
            key=lambda c: (
                c.get("relevance", 0.0) * 0.70 +
                (1.0 if c.get("provenance", {}).get("verified") else 0.0) * 0.20 +
                (0.10 if c.get("provenance", {}).get("exit_code") == 0 else 0.0)
            ),
            reverse=True,
        )

        return deduped[:limit]

    def _retrieve_from_messages(self, request: str, current_conv_id: str | None) -> list[dict[str, Any]]:
        candidates = []
        if not self.workspace or not hasattr(self.workspace, "store"):
            return candidates

        try:
            with self.workspace.store.connect() as db:
                rows = db.execute(
                    "SELECT id, conversation_id, created_at, role, content, meta_json "
                    "FROM messages ORDER BY created_at DESC LIMIT 300"
                ).fetchall()

            # Group messages by conversation to pair user questions with vortex answers
            conv_messages: dict[str, list[dict[str, Any]]] = {}
            for r in rows:
                c_id = r["conversation_id"]
                conv_messages.setdefault(c_id, []).append(dict(r))

            for c_id, msgs in conv_messages.items():
                # Sort chronologically
                msgs.sort(key=lambda m: m["created_at"])
                for i in range(len(msgs)):
                    m = msgs[i]
                    if m["role"] in {"vortex", "assistant"}:
                        content = str(m["content"] or "").strip()
                        if not content or len(content) < 15:
                            continue
                        if "All configured free AI providers are currently unavailable" in content and len(content) < 120:
                            continue

                        meta = {}
                        try:
                            meta = json.loads(m["meta_json"]) if m.get("meta_json") else {}
                        except (ValueError, TypeError):
                            pass

                        # Determine original prompt
                        orig_req = ""
                        if i > 0 and msgs[i - 1]["role"] == "user":
                            orig_req = str(msgs[i - 1]["content"] or "").strip()

                        # Check if task/operation was attached
                        task_id = meta.get("task_id")
                        op_id = meta.get("operation_id")
                        ai_info = meta.get("ai") or {}

                        prov = Provenance(
                            conversation_id=c_id,
                            message_id=m["id"],
                            task_id=task_id,
                            operation_id=op_id,
                            timestamp=m["created_at"],
                            provider=ai_info.get("provider") or meta.get("provider"),
                            model=ai_info.get("model") or meta.get("model"),
                            title=orig_req[:80] if orig_req else None,
                        )

                        candidates.append({
                            "candidate_id": f"hist-msg-{m['id'][:12]}",
                            "source_type": "historical",
                            "answer": content,
                            "original_request": orig_req,
                            "timestamp": m["created_at"],
                            "provenance": prov.to_dict(),
                            "meta": meta,
                        })
        except Exception:
            pass
        return candidates

    def _retrieve_from_tasks(self, request: str) -> list[dict[str, Any]]:
        candidates = []
        if not self.workspace or not hasattr(self.workspace, "store"):
            return candidates

        try:
            with self.workspace.store.connect() as db:
                rows = db.execute(
                    "SELECT id, created_at, conversation_id, request, state, plan_id, operation_id, risk, result_json "
                    "FROM tasks WHERE state IN ('COMPLETED', 'VALIDATING') ORDER BY created_at DESC LIMIT 100"
                ).fetchall()

            for r in rows:
                result = {}
                try:
                    result = json.loads(r["result_json"]) if r["result_json"] else {}
                except (ValueError, TypeError):
                    pass

                explanation = str(result.get("explanation") or "").strip()
                commands = result.get("commands") or []
                objective = result.get("objective") or {}
                episode = result.get("episode") or {}

                answer_text = explanation
                if not answer_text and commands:
                    answer_text = f"Executed verified command(s): {', '.join(commands)}"

                if not answer_text:
                    continue

                exit_codes = episode.get("observation", {}).get("last_exit_codes") or []
                success = (r["state"] == "COMPLETED" and
                           (all(code == 0 for code in exit_codes) if exit_codes else True))

                prov = Provenance(
                    conversation_id=r["conversation_id"],
                    task_id=r["id"],
                    operation_id=r["operation_id"],
                    plan_id=r["plan_id"],
                    timestamp=r["created_at"],
                    exit_code=exit_codes[0] if exit_codes else (0 if success else None),
                    verified=success,
                    reward=(episode.get("evaluation") or {}).get("reward") or (1.0 if success else 0.0),
                    title=str(r["request"])[:80],
                )

                candidates.append({
                    "candidate_id": f"hist-task-{r['id']}",
                    "source_type": "historical",
                    "answer": answer_text,
                    "original_request": r["request"],
                    "timestamp": r["created_at"],
                    "provenance": prov.to_dict(),
                    "commands": commands,
                })
        except Exception:
            pass
        return candidates

    def _retrieve_from_procedures(self, request: str) -> list[dict[str, Any]]:
        candidates = []
        if not self.workspace or not hasattr(self.workspace, "list_procedures"):
            return candidates

        try:
            procedures = self.workspace.list_procedures()
            for p in procedures:
                steps = p.get("steps") or []
                name = p.get("name") or "Procedure"
                steps_display = " -> ".join(steps) if steps else "Verified procedural steps"
                answer = f"Verified procedure '{name}' ({p.get('uses', 1)} execution(s)): {steps_display}"

                prov = Provenance(
                    task_id=p.get("source_task"),
                    timestamp=p.get("created_at") or now_iso(),
                    verified=True,
                    reward=1.0,
                    title=name,
                )

                candidates.append({
                    "candidate_id": f"hist-proc-{p['id']}",
                    "source_type": "historical",
                    "answer": answer,
                    "original_request": name,
                    "timestamp": p.get("created_at") or now_iso(),
                    "provenance": prov.to_dict(),
                    "steps": steps,
                })
        except Exception:
            pass
        return candidates

    def _retrieve_from_memories(self, request: str) -> list[dict[str, Any]]:
        candidates = []
        if not self.workspace or not hasattr(self.workspace, "list_memories"):
            return candidates

        try:
            memories = self.workspace.list_memories()
            for m in memories:
                title = m.get("title") or ""
                body = m.get("body") or ""
                if not body:
                    continue

                prov = Provenance(
                    timestamp=m.get("created_at") or now_iso(),
                    title=title,
                )

                candidates.append({
                    "candidate_id": f"hist-mem-{m['id']}",
                    "source_type": "historical",
                    "answer": f"{title}: {body}" if title else body,
                    "original_request": title,
                    "timestamp": m.get("created_at") or now_iso(),
                    "provenance": prov.to_dict(),
                })
        except Exception:
            pass
        return candidates

    def _deduplicate_candidates(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Group identical/near-identical candidate answers, preserving the best provenance."""
        groups: list[dict[str, Any]] = []

        for cand in candidates:
            ans_clean = re.sub(r"\s+", " ", cand.get("answer", "").strip().lower())
            if not ans_clean:
                continue

            matched = False
            for group in groups:
                existing_clean = re.sub(r"\s+", " ", group.get("answer", "").strip().lower())
                # Exact or high similarity duplicate detection
                sim = compute_lexical_similarity(ans_clean, existing_clean)
                if sim > 0.85 or ans_clean == existing_clean or (len(ans_clean) > 30 and ans_clean in existing_clean):
                    matched = True
                    # If the new one has better verification, update the group's answer/provenance
                    if cand.get("provenance", {}).get("verified") and not group.get("provenance", {}).get("verified"):
                        group["answer"] = cand["answer"]
                        group["provenance"] = cand["provenance"]
                    group["relevance"] = max(group.get("relevance", 0.0), cand.get("relevance", 0.0))
                    break

            if not matched:
                groups.append(cand)

        return groups
