# Model Providers

The Quiver SDK supports every major LLM provider out of the box via the built-in LLM gateway.

## Supported Providers

| Provider ID | Models | Install |
|-------------|--------|---------|
| `"anthropic"` | Claude Opus 4.7, Sonnet 4.6, Haiku 4.5 | `pip install anthropic` |
| `"openai"` | GPT-4o, GPT-4o-mini, o1, o3 | `pip install openai` |
| `"openai-compatible"` | vLLM, Together, Fireworks, Groq, Ollama, LiteLLM | `pip install openai` |
| `"gemini"` | Gemini 2.0 Flash, Gemini 1.5 Pro | `pip install google-generativeai` |
| `"bedrock"` | Claude, Llama, Titan via AWS | `pip install boto3` |
| `"mistral"` | Mistral Large, Codestral | `pip install mistralai` |
| `"openrouter"` | 200+ models via OpenRouter | `pip install openai` |
| `"quiver"` | Quiver-managed Anthropic models | `pip install anthropic` |

## Basic Configuration

Pass `provider_id` and `model_id` to `Agent` or `QuiverCore.create()`:

```python
from src import Agent

agent = Agent(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    api_key="sk-ant-...",       # or set ANTHROPIC_API_KEY env var
    system_prompt="You are a helpful assistant.",
)
```

## Provider-Specific Examples

### Anthropic

```python
agent = Agent(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    api_key="sk-ant-...",          # or ANTHROPIC_API_KEY env var
)
```

Available models: `claude-opus-4-7`, `claude-sonnet-4-6`, `claude-haiku-4-5`, `claude-3-5-sonnet-20241022`, `claude-3-5-haiku-20241022`

**Extended Thinking (Claude 3.7+):**

```python
agent = Agent(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    model_options={
        "reasoning": {"enabled": True, "budgetTokens": 8000}
    },
)
```

### OpenAI

```python
agent = Agent(
    provider_id="openai",
    model_id="gpt-4o",
    api_key="sk-...",              # or OPENAI_API_KEY env var
)
```

Available models: `gpt-4o`, `gpt-4o-mini`, `o1`, `o1-mini`, `o3`, `o3-mini`, `gpt-4-turbo`

### Google Gemini

```python
agent = Agent(
    provider_id="gemini",
    model_id="gemini-2.0-flash",
    api_key="AIza...",             # or GOOGLE_API_KEY env var
)
```

### AWS Bedrock

Uses the AWS credential chain (env vars, `~/.aws/credentials`, IAM roles):

```python
agent = Agent(
    provider_id="bedrock",
    model_id="anthropic.claude-3-5-sonnet-20241022-v2:0",
    # No api_key — uses AWS credential chain
)
```

Set region via `AWS_DEFAULT_REGION` or `AWS_REGION` env var.

### Mistral

```python
agent = Agent(
    provider_id="mistral",
    model_id="mistral-large-latest",
    api_key="...",                 # or MISTRAL_API_KEY env var
)
```

### OpenAI-Compatible (vLLM, Together, Groq, Ollama, LiteLLM)

```python
# Together AI
agent = Agent(
    provider_id="openai-compatible",
    model_id="meta-llama/Llama-3-70b-chat-hf",
    api_key="...",
    base_url="https://api.together.xyz/v1",
)

# Groq
agent = Agent(
    provider_id="openai-compatible",
    model_id="llama3-70b-8192",
    api_key="gsk_...",
    base_url="https://api.groq.com/openai/v1",
)

# Local Ollama
agent = Agent(
    provider_id="openai-compatible",
    model_id="llama3",
    api_key="ollama",               # Ollama ignores the key
    base_url="http://localhost:11434/v1",
)

# LiteLLM proxy
agent = Agent(
    provider_id="openai-compatible",
    model_id="gpt-4o",
    api_key="sk-...",
    base_url="http://localhost:4000",
)
```

### OpenRouter

```python
agent = Agent(
    provider_id="openrouter",
    model_id="anthropic/claude-3.5-sonnet",
    api_key="sk-or-...",           # or OPENROUTER_API_KEY env var
)
```

## Advanced Gateway

For multi-provider setups or runtime provider switching:

```python
from src import create_gateway, GatewayProviderConfig

gateway = create_gateway(
    provider_configs=[
        GatewayProviderConfig(provider_id="anthropic", api_key="sk-ant-..."),
        GatewayProviderConfig(provider_id="openai", api_key="sk-..."),
        GatewayProviderConfig(provider_id="gemini", api_key="AIza..."),
    ]
)

# List all available models across all providers
for model in gateway.list_models():
    print(f"{model.provider_id}/{model.id} — {model.name}")

# Create a model adapter
model = gateway.create_agent_model("anthropic", "claude-sonnet-4-6")

agent = Agent(
    model=model,
    system_prompt="You are a helpful assistant.",
)
```

## Model Options

Pass provider-specific options via `model_options`:

```python
agent = Agent(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    model_options={
        "max_tokens": 4096,         # max output tokens
        "temperature": 0.7,         # 0.0–1.0
        "reasoning": {              # extended thinking (Anthropic)
            "enabled": True,
            "budgetTokens": 8000,
        },
    },
)
```

## Environment Variables

The SDK reads API keys from environment automatically:

| Provider | Environment Variable |
|---|---|
| Anthropic | `ANTHROPIC_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |
| Google | `GOOGLE_API_KEY` |
| Mistral | `MISTRAL_API_KEY` |
| OpenRouter | `OPENROUTER_API_KEY` |
| AWS Bedrock | `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` + `AWS_DEFAULT_REGION` |

## Custom Base URL and Headers

```python
agent = Agent(
    provider_id="anthropic",
    model_id="claude-sonnet-4-6",
    base_url="https://my-proxy.example.com",
    headers={
        "X-Custom-Header": "my-value",
        "X-Org-ID": "org-123",
    },
)
```
