from pydantic import (
    BaseModel,
    ConfigDict, 
    Field
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class AiModelConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix='sca_agent_',
        env_file='.env',
        env_file_encoding='utf-8'
    )
    
    model_credentials: str = Field(..., description = 'Ключ для доступа к ИИ модели', )
    model_scope: str = Field('GIGACHAT_API_PERS', description = 'Скоуп для работы с моделью')
    verify_ssl_certs: bool = False