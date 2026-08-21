from typing import Optional, List, Tuple
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from llm.vendors.openrouter import ChatOpenRouter
from llm.prompt.base_text_templates import TEXT_PROMPT_TEMPLATE_V1
from backend.constants import OPENROUTER_LLM_ENDPOINT, OPENAI_LLM_ENDPOINT, TEMPERATURE

_ = load_dotenv('.env')

def llm_OpenRouter_memory_chain(
        user_input: str,
        memory: Optional[List[Tuple[str, str]]],
        ) -> str:

    # Model
    model = ChatOpenRouter(
        model_name = OPENROUTER_LLM_ENDPOINT,
        temperature= TEMPERATURE,
    )

    # Prompt
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", TEXT_PROMPT_TEMPLATE_V1),
            MessagesPlaceholder(variable_name="history"),
            ("human", "{user_input}"),
        ]
    )

    # Chain
    chain = (
        prompt
        | model
        | StrOutputParser()
    )
    
    return chain.invoke({
        "user_input": user_input,
        "history": memory
    })

def llm_OpenAI_memory_chain(
        user_input: str,
        memory: Optional[List[Tuple[str, str]]],
        ) -> str:

    # Model
    model = ChatOpenAI(
        model=OPENAI_LLM_ENDPOINT,
        temperature= TEMPERATURE,
    )

    # Prompt
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", TEXT_PROMPT_TEMPLATE_V1),
            MessagesPlaceholder(variable_name="history"),
            ("human", "{user_input}"),
        ]
    )

    # Chain
    chain = (
        prompt
        | model
        | StrOutputParser()
    )

    return chain.invoke({
        "user_input": user_input,
        "history": memory
    })

async def llm_OpenAI_memory_chain_async(
        user_input: str,
        memory: Optional[List[Tuple[str, str]]],
        ) -> str:

    # Model
    model = ChatOpenAI(
        model=OPENAI_LLM_ENDPOINT,
        temperature= TEMPERATURE,
    )

    # Prompt
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", TEXT_PROMPT_TEMPLATE_V1),
            MessagesPlaceholder(variable_name="history"),
            ("human", "{user_input}"),
        ]
    )

    # Chain
    chain = (
        prompt
        | model
        | StrOutputParser()
    )

    return await chain.ainvoke({
        "user_input": user_input,
        "history": memory
    })