from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    database_path: str = str(ROOT / "freya.sqlite3")
    demo_week_start: str = "2026-11-16"
    demo_mode: bool = True
    backend_api_key: str = ""
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    livekit_agent_name: str = "freya-delivery"
    eleven_api_key: str = ""
    eleven_voice_id: str = ""
    eleven_stt_model: str = "scribe_v2_realtime"
    eleven_tts_model: str = "eleven_flash_v2_5"
    google_api_key: str = ""
    google_model: str = "gemini-3.1-flash-lite"

settings = Settings()
