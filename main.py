from langchain_community.llms.gigachat import GigaChat
from src.sca_agent.fetch.repo_fetcher import fetch_repo
def main() -> None:
    fetch_repo(
        'test-repo',
        'git@github.com:michasks/opentelemetry-java.git',
        '/Users/viktormikhaylov/Development/tmp/otel',
        'main'
    )
    # modelConfig = AiModelConfig()
    # giga = GigaChat(
    # credentials=modelConfig.model_credentials,
    # scope=modelConfig.model_scope,
    # verify_ssl_certs=modelConfig.verify_ssl_certs)

    # models = giga.get_models()

    print("models")

if __name__ == '__main__': 
    main()