from diagrams import Diagram, Cluster
from diagrams.onprem.client import User
from diagrams.onprem.compute import Server
from diagrams.onprem.database import PostgreSQL
from diagrams.onprem.network import Nginx

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
        rag_mgr = Server("core.rag_manager\nChunking + FAISS")
        memory_mgr = Server("core.memory\nConversations + context tokens")

    # Persistence & Storage (middle)
    with Cluster("Persistence & Storage"):
        sql_db = PostgreSQL("SQLModel/SQLite\nbackend/app/data/morpheus.db")
        uploads = Server("Uploads\nmemory/{project}/uploads")
        faiss_idx = Server("FAISS Index\nmemory/{project}/faiss")

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
    user >> spa
    user >> chat_api
    user >> proj_api
    user >> files_api
    user >> models_api
    user >> rag_api

    # Routers to core
    chat_api >> llm_provider
    chat_api >> memory_mgr
    chat_api >> rag_mgr

    rag_api >> rag_mgr
    proj_api >> sql_db
    files_api >> uploads
    files_api >> rag_mgr
    #models_api >> settings

    # Core to persistence and external
    rag_mgr >> faiss_idx
    rag_mgr >> openai_embed
    llm_provider >> openai_chat

    # Core uses settings; backend configured by logging (kept commented per request)
    #settings >> llm_provider
    #settings >> rag_mgr
    #settings >> models_api
    #logging_cfg >> chat_api
    #logging_cfg >> proj_api
    #logging_cfg >> files_api
    #logging_cfg >> rag_api
    #logging_cfg >> models_api
