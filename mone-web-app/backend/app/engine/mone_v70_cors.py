from fastapi.middleware.cors import CORSMiddleware

def register_mone_v70_cors(app):
    try:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[
                "http://localhost:3200",
                "http://127.0.0.1:3200",
                "http://localhost:3000",
                "http://127.0.0.1:3000",
            ],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    except Exception as exc:
        print("[MONE v7.0] CORS middleware registration skipped:", exc)
