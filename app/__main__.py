"""Run with `python -m app` from the project directory."""
import uvicorn

from app.config import PROJECT_ROOT, config


def main():
    uvicorn.run("app.main:app", host=config.fastapi_host, port=config.fastapi_port,
                app_dir=str(PROJECT_ROOT), reload=False)


if __name__ == "__main__":
    main()
