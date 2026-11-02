"""Attach wrappers in memory; no decorators or imports are added to app/ files."""
import importlib

from kb_observability import tracing

_installed = False


def install():
    global _installed
    if _installed:
        return
    # Patch providers before consumers bind their imported parsing functions.
    parser = importlib.import_module("app.services.document_parser")
    parser.load_documents = tracing.observe(parser.load_documents, "document_parse")
    parser.load_chunks = tracing.observe(parser.load_chunks, "document_split")
    embeddings = importlib.import_module("app.services.embeddings").RagTextEmbeddings
    from app.config import config
    embeddings.__init__ = tracing.observe(embeddings.__init__, "load_embedding_model")
    for name in ("embed_query", "embed_documents"):
        setattr(embeddings, name, tracing.observe(getattr(embeddings, name), name,
            kind="embedding", model=config.text_embeddings_model_path))

    from langchain_milvus import Milvus
    from langchain_openai import ChatOpenAI
    for name in ("similarity_search_with_score", "add_texts"):
        setattr(Milvus, name, tracing.observe(getattr(Milvus, name), "milvus_" + name))
    ChatOpenAI.stream = tracing.observe(ChatOpenAI.stream, "DeepSeek-generation", kind="generation",
        generation=True, model=config.llm_model_name)

    repository = importlib.import_module("app.repositories.workspace")
    for name in ("add_document", "remove_document", "save_message"):
        setattr(repository, name, tracing.observe(getattr(repository, name), "sqlite_" + name))
    for name in ("documents", "document", "history"):
        setattr(repository, name, tracing.observe(getattr(repository, name), "sqlite_" + name, nested_only=True))

    rag = importlib.import_module("app.services.rag")
    original_retrieve = rag.retrieve

    def retrieve(question):
        before = rag._retrieve_cached.cache_info()
        result = original_retrieve(question)
        observation = tracing.current.get()
        if observation:
            observation.metadata["cache_hit"] = rag._retrieve_cached.cache_info().hits > before.hits
            observation.metadata["source_count"] = len(result[0])
        return result

    rag.retrieve = tracing.observe(retrieve, "milvus_retrieval")
    for name in ("get_store", "get_llm", "add_chunks", "delete_chunks", "clear", "warmup", "stream_answer"):
        setattr(rag, name, tracing.observe(getattr(rag, name), "rag_" + name))

    documents = importlib.import_module("app.services.documents")
    # Existing imports may already be bound when installed from a test or notebook.
    documents.load_chunks, documents.load_documents = parser.load_chunks, parser.load_documents
    for name in ("create", "remove", "clear", "original"):
        setattr(documents, name, tracing.observe(getattr(documents, name), "document_" + name))
    chat = importlib.import_module("app.services.chat")
    chat._retrieve = tracing.observe(chat._retrieve, "retrieve_documents")
    chat._save = tracing.observe(chat._save, "persist_answer")
    chat.ask = tracing.observe(chat.ask, "rag_chat")
    chat.stream = tracing.observe(chat.stream, "rag_chat_stream")
    _installed = True
