# 03 — Multi-turn Chat and Conversation History (P2)

## Codex role and objective
Act as a senior Python and Streamlit engineer. Continue from tasks 01 and 02. Add a useful local conversation experience to Streamlit while preserving grounded document retrieval, source filters, citations, and verification.

## Read before editing
Inspect `streamlit_app.py`, the structured Q&A service created in task 02, `mdr_rag/pipeline.py`, `mdr_rag/search.py`, tests, and index-status service from task 01. Avoid storing full raw legal/device chunks redundantly unless needed to display citations.

## Functional requirements
### A. Chat UI
1. Use `st.chat_message('user')`, `st.chat_message('assistant')`, and `st.chat_input` where sensible.
2. Show turns in chronological order with the assistant's answer, verification status, limitations, and expandable **per-turn supporting source excerpts**.
3. Provide **New conversation** and **Clear current conversation** actions (with understandable effect). New conversation should start fresh and not erase unrelated conversations.
4. Show a conversation selector/list in the sidebar for previously created chats during this session. Optionally persist local chats between app restarts if straightforward and safe; the MVP minimum is `st.session_state` history. Label session-only storage clearly if used.
5. Keep a separate `conversation_id`, `created_at`, `messages` and `selected_sources` for each conversation. Do not leak or mix turns between conversations.
6. Store actual source IDs, filenames, locations, and excerpts per assistant turn so users can inspect what supported earlier answers.
7. Do not store sensitive chats in a public database, browser query params, or git; if adding disk persistence, use a local ignored path and validate loaded JSON. Document local privacy limitations.

### B. Genuine follow-up questions
8. Follow-up queries such as "What does that mean?" or "Does the same requirement apply to software?" should use conversational context. **Do not simply concatenate all chat history into every retrieval query.**
9. Introduce a small, bounded question contextualization step (using local Ollama or a deterministic fallback) which rewrites an ambiguous follow-up into a standalone retrieval query using recent user/assistant turns. Preserve the user's original question separately.
10. Treat earlier assistant responses as potentially inaccurate. The rewritten question is only used for retrieval. **Every new response must retrieve fresh evidence and pass the same citation/claim verification from task 02**; never assume earlier cited chunks support a new claim.
11. For a small local model, cap history passed to contextualization (e.g., last 4-6 turns or configurable character budget); use explicit instructions to avoid adding facts not present in user context. Handle contextualization failures by falling back to the user's original question and marking the fallback for debug logs.
12. Preserve the per-chat document filters in context. Changing selected documents updates retrieval scope for subsequent questions only; previously answered turns retain their original sources and show what document selection was used.
13. If an indexed source is added/removed/modified and the index becomes stale, block new questions until reindexing, but keep previous chat history visible with a **may refer to an earlier index version** warning. Never present old citations as verified against new index content.
14. A new conversation should not import hidden context from another conversation.

### C. Robust Streamlit behavior
15. Streamlit reruns must not duplicate a user turn or launch repeated LLM calls. Use stable conversation/session IDs and only append a turn when the user submits it.
16. Render previous turns from session state without repeatedly querying Chroma or Ollama.
17. Show helpful errors when Ollama is unavailable. A failed response should not create a misleading assistant success turn; offer a retry path or a clearly marked error entry.
18. Keep chat history lightweight: do not persist embeddings, passwords, API keys or entire document files in chat records.
19. Do not introduce LangChain/LangGraph, authentication, cloud sync, or multi-user hosting for this MVP.

## Suggested data model (adapt to existing result types)
```python
{
  "id": "conversation-uuid",
  "title": "MDR Annex I questions",
  "created_at": "ISO timestamp",
  "selected_sources": ["legal/MDR_2017.pdf"],
  "messages": [
    {"role": "user", "content": "What does Annex I require?"},
    {
      "role": "assistant",
      "content": "...",
      "status": "supported",
      "retrieval_query": "What does Annex I require?",
      "index_version": "manifest digest or timestamp",
      "sources": [
        {"id": "L-example", "source": "legal/MDR_2017.pdf", "page": 12,
         "block": 1, "excerpt": "Exact retrieved text..."}
      ],
      "limitations": []
    }
  ]
}
```

## Tests Codex must add
- Messages persist across ordinary Streamlit reruns and display in order.
- Switching between two chats never mixes content.
- New conversation has no old contextualization history.
- A follow-up contextualization request includes bounded recent turns.
- Every follow-up runs fresh filtered retrieval and verification.
- Filters modified mid-conversation apply only to new answers; old source displays remain accurate.
- Stale index blocks new answers but still shows old chat turns with warning.
- A failed request cannot generate duplicate user/assistant turns after a rerun.
- If using persistent history, corrupted JSON is handled gracefully and files remain gitignored.

## Acceptance scenario
Upload and index a readable MDR PDF from Streamlit. Start a conversation and ask "What are the general safety and performance requirements?" Read the grounded result with citations. Then ask "Which annex mentions them?" Receive a second answer using the follow-up context but with **newly retrieved and validated sources**. Create a new conversation and ask an unrelated question; no context from the first chat should be used. Switch back to the first conversation and see both turns plus their source excerpts. Reindex a changed document: existing conversation stays visible with a stale-source warning.

## Deliverables
Update code, tests and README. Run `python -m pytest -q` and manual end-to-end scenarios. In final Codex response include files changed, feature summary, explicit test results, known limitations (especially whether history persists across browser/server restarts), and exact Streamlit launch command.
