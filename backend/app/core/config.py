from pydantic_settings import BaseSettings,SettingsConfigDict

class Settings(BaseSettings):
    PINECONE_API_KEY: str
    GROQ_API_KEY: str
    REDIS_URL: str
    SUPABASE_URL: str
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8",
        extra="ignore"
    )
settings = Settings()