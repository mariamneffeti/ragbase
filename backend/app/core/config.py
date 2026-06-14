from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr, field_validator, model_validator

class Settings(BaseSettings):
    DEBUG: bool = False
    ENV: str = "development"
    DISABLE_AUTH: bool = False

    ALLOWED_ORIGINS: list[str] = [
        "http://localhost:3000",
        "https://ragbase-ten.vercel.app",
    ]

    PINECONE_API_KEY: SecretStr
    GROQ_API_KEY: SecretStr
    REDIS_URL: SecretStr
    SUPABASE_URL: SecretStr

    @model_validator(mode="after")
    def check_production_safety(self):
        if self.ENV == "production" and self.DISABLE_AUTH:
            raise ValueError("DISABLE_AUTH cannot be enabled in production")
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()