##

* To-do List:
```
1. Integrate horizonal scale to multiple Chatbot.
```

## Project Structure

```
Discord-Bot/
├── backend/                      # Backend directory for the FastAPI application
│   ├── fastapi/                  # Main application directory
│   │   ├── __init__.py           # Initialization file for the app package
│   │   ├── api/                  # Directory for API related code
│   │   │   ├── __init__.py       # Initialization file for the API package
│   │   │   ├── v1/               # Version 1 of the API
│   │   │   │   ├── __init__.py   # Initialization file for the v1 API package
│   │   │   │   ├── endpoints/    # Directory for API endpoint definitions
│   │   │   │   │   ├── __init__.py          # Initialization file for endpoints package
│   │   │   │   │   ├── text_generation.py   # Endpoints for text generation
│   │   │   │   │   ├── llm_management.py    # Endpoints for LLM model management
│   │   │   │   │   ├── message.py           # Endpoints for message management
│   │   │   │   │   ├── user.py              # Endpoints for user management
│   │   │   │   │   ├── session.py           # Endpoints for session management
│   │   │   │   │   ├── command.py           # Endpoints for command management
│   │   ├── dependencies/         # Directory for dependency management
│   │   │   ├── __init__.py       # Initialization file for dependencies package
│   │   │   ├── database.py       # Database connection and session management
│   │   │   ├── rate_limiter.py   # Rate limiting logic
│   │   ├── request_handler/      # Directory for HTTP request handling utilities
│   │   │   ├── __init__.py
│   │   │   ├── api_requests.py    
│   │   ├── core/                 # Core application logic
│   │   │   ├── __init__.py       # Initialization file for core package
│   │   │   ├── constant.py       # Constant settings
│   │   │   ├── config.py         # Configuration settings
│   │   │   ├── init_setting.py   # Init settings with user's input
│   │   ├── models/               # Directory for SQLAlchemy models
│   │   │   ├── __init__.py       # Initialization file for models package
│   │   │   ├── user.py           # User model
│   │   │   ├── message.py        # Message model
│   │   │   ├── session.py        # Session model
│   │   │   ├── command.py        # Command model
│   │   │   ├── command_log.py    # CommandLog model
│   │   │   ├── conversation.py   # Conversation model
│   │   │   ├── llm.py            # LLM model
│   │   │   ├── llm_usage.py      # LLM usage model
│   │   ├── schemas/              # Directory for Pydantic schemas
│   │   │   ├── __init__.py       # Initialization file for schemas package
│   │   │   ├── user.py           # Schemas for user data
│   │   │   ├── session.py        # Schemas for session data
│   │   │   ├── message.py        # Schemas for message data
│   │   │   ├── command.py        # Schemas for command data
│   │   │   ├── command_log.py    # Schemas for command log data
│   │   │   ├── conversation.py   # Schemas for conversation data
│   │   │   ├── llm.py            # Schemas for LLM data
│   │   │   ├── llm_usage.py      # Schemas for LLM usage data
│   │   ├── crud/                 # Directory for CRUD operations
│   │   │   ├── __init__.py       # Initialization file for crud package
│   │   │   ├── user.py           # CRUD for user management
│   │   │   ├── session.py        # CRUD for session management
│   │   │   ├── message.py        # CRUD for message management
│   │   │   ├── command.py        # CRUD for command management
│   │   │   ├── command_log.py    # CRUD for command log management
│   │   │   ├── conversation.py   # CRUD for conversation management
│   │   │   ├── llm.py            # CRUD for LLM management
│   │   │   ├── llm_usage.py      # CRUD for LLM usage management
│   │   ├── main.py               # Main FastAPI application file
│   ├── discord/                  # Discord bot integration
│   │   ├── __init__.py           # Initialization file for Discord package
│   │   ├── operations/           # Directory for Low-level operation in Discord Bot
│   │   │   ├── __init__.py       # Initialization file for the API package
│   │   ├── bot.py                # Main bot architecture
│   │   ├── register.py           # Command Register
│   │   ├── run.py                # High-level Operations
│   ├── meilisearch/              # Meilisearch integration
│   │   ├── __init__.py           # Initialization file for Meilisearch package
│   │   ├── search.py             # Search logic
│   ├── data/                     # Directory for data when initiating DB
│   │   ├── __init__.py           # Initialization file for data package
│   │   ├── llm_models.py         # LLM models information
│   ├── security/                 # Directory for authentication and authorization
│   │   ├── __init__.py           # Initialization file for security package
│   │   ├── authentication.py     # Authentication logic
│   │   ├── authorization.py      # Authorization logic
│   ├── tests/                    # Directory for test files
│   │   ├── __init__.py           # Initialization file for tests package
│   │   ├── test_user.py          # Test cases for user management
│   │   ├── test_message.py       # Test cases for message management
│   │   ├── test_session.py       # Test cases for session management
│   │   ├── test_command.py       # Test cases for command management
│   │   ├── test_llm.py           # Test cases for LLM model management
│   │   ├── test_llm_usage.py     # Test cases for LLM usage management
├── llm/
│   ├── __init__.py               # Initialization file for LLM package
│   ├── chain/                    # Folder for prompt handling
│   │   ├── __init__.py           # Initialization file for chain package
│   │   ├── llm_text_chain.py     # Module for LLM text generation integration
│   ├── prompt/                   # Folder for prompt handling
│   │   ├── __init__.py           # Initialization file for prompt package
│   │   ├── base_text_templates.py# Stores base prompt templates for text generation
│   │   ├── examples/             # Directory for few-shot examples used by the chain
│   │   ├── deprecated/           # Directory for deprecated prompts
│   ├── memory/                   # Folder for Memory Management
│   │   ├── __init__.py           # Initialization file for memory package
│   │   ├── memory_management.py  # Module for LLM memory management
│   ├── search/                   # Folder for Search Integration
│   │   ├── __init__.py           # Initialization file for search package
│   │   ├── memory_management.py  # Module for LLM search management
│   ├── vendors/                  # Directory for vendor-specific LLM configurations
│   │   ├── __init__.py           # Initialization file for vendors package
│   │   ├── openrouter.py         # Configurations and usage for OpenRouter as LLM provider
├── .env                          # Environment variables file
```