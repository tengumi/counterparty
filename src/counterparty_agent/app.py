"""FastAPI and AG-UI application boundary.

TODO:
- создать FastAPI lifespan и composition root;
- один раз собрать settings, sources, model, graph и checkpointer;
- добавить health endpoint и AG-UI/SSE endpoint;
- связать thread_id с доверенным user/session context;
- очищать истёкшие checkpoints по session TTL;
- закрывать HTTP client и persistence resources при остановке.
"""
