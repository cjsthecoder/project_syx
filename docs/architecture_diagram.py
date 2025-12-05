"""
Copyright (c) 2025 Christopher Shuler. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
from diagrams import Diagram, Cluster, Edge
from diagrams.onprem.client import User
from diagrams.onprem.compute import Server
from diagrams.onprem.database import PostgreSQL
from diagrams.onprem.network import Nginx
from diagrams.generic.storage import Storage

# Generate docs/morpheus_architecture.png
with Diagram(
    "Morpheus Architecture",
    filename="docs/morpheus_architecture",
    show=False,
    outformat="png",
    direction="RL",  # Right-to-left layout: Core (left) -> Persistence (middle) -> User (right)
):
    # Core first (left)
    with Cluster("Core"):
        #settings = Server("core.config.Settings\n(.env, LOG_LEVEL, models, RAG)")
        llm_provider = Server("core.llm\nLangChain ChatOpenAI")
        query_builder = Server("core.query_builder\nBuilder + Router")
        rag_mgr = Server("core.rag_manager\nChunking + FAISS + Merge")
        memory_mgr = Server("core.memory\nConversations + context tokens")

    # Persistence & Storage (middle)
    with Cluster("Persistence & Storage"):
        sql_db = PostgreSQL("SQLModel/SQLite\nbackend/app/data/morpheus.db")
        uploads = Storage("Uploads\nmemory/{project}/uploads")
        faiss_idx = Storage("Main FAISS Index\nmemory/{project}/faiss")
        daily_faiss = Storage("Daily FAISS\nmemory/{project}/daily_faiss")
        daily_meta = Storage("Daily Metadata\nmemory/{project}/daily.json")
        sidecars = Storage("Sidecars (topics/namespaces)\nmemory/{project}/faiss/meta_*.json")

    # Backend Routers (to the right of core/persistence)
    with Cluster("Backend (FastAPI) Routers"):
        chat_api = Server("/chat")
        rag_api = Server("/query_rag")
        proj_api = Server("/projects …")
        files_api = Server("/projects/{id}/files")
        models_api = Server("/models")
        #logging_cfg = Server("utils.logging\n(console + file)")

    # Frontend & User (rightmost)
    with Cluster("Frontend (React/Vite + Shadcn)"):
        spa = Server("SPA /static (Vite build)")
    user = User("User (Browser)")

    # External services (off to the side)
    with Cluster("External Services"):
        openai_chat = Server("OpenAI Chat API")
        openai_embed = Server("OpenAI Embeddings")

    # Flows (arrows will render right-to-left due to RL layout)
    user >> Edge(label="SPA") >> spa
    user >> Edge(label="Chat") >> chat_api
    user >> Edge(label="Projects") >> proj_api
    user >> Edge(label="Files") >> files_api
    user >> Edge(label="Models") >> models_api
    user >> Edge(label="RAG (debug)") >> rag_api

    # Routers to core
    chat_api >> Edge(color="blue", label="summarize history + build route/queries") >> query_builder
    chat_api >> Edge(color="gray", label="working memory") >> memory_mgr
    # Builder decides routing and rewritten queries
    query_builder >> Edge(color="orange", label="topics + namespace + queries") >> rag_mgr
    query_builder >> Edge(color="green", label="direct/no-RAG or final chat") >> llm_provider

    rag_api >> rag_mgr
    proj_api >> sql_db
    files_api >> uploads
    files_api >> rag_mgr
    #models_api >> settings

    # Core to persistence and external
    rag_mgr >> Edge(color="purple", label="persist/retrieve") >> faiss_idx
    rag_mgr >> Edge(color="purple", style="dashed", label="daily roll-off") >> daily_faiss
    rag_mgr >> Edge(color="purple", style="dotted", label="metadata") >> daily_meta
    rag_mgr >> Edge(color="purple", style="dotted", label="sidecars read") >> sidecars
    rag_mgr >> Edge(color="teal", label="embed") >> openai_embed
    llm_provider >> Edge(color="green", label="completions") >> openai_chat

    # Core uses settings; backend configured by logging (kept commented per request)
    #settings >> llm_provider
    #settings >> rag_mgr
    #settings >> models_api
    #logging_cfg >> chat_api
    #logging_cfg >> proj_api
    #logging_cfg >> files_api
    #logging_cfg >> rag_api
    #logging_cfg >> models_api
