import pickle
from pathlib import Path

from langchain import (
    LLMMathChain,
    OpenAI,
    SerpAPIWrapper,
    SQLDatabase,
    SQLDatabaseChain,
)
from langchain.agents import initialize_agent, Tool
from langchain.agents import AgentType

import streamlit as st

from capturing_callback_handler import CapturingCallbackHandler
from streamlit_callback_handler import StreamlitCallbackHandler

DB_PATH = (Path(__file__).parent / "Chinook.db").absolute()

llm = OpenAI(temperature=0, openai_api_key=st.secrets["openai_api_key"])
search = SerpAPIWrapper(serpapi_api_key=st.secrets["serpapi_api_key"])
llm_math_chain = LLMMathChain(llm=llm, verbose=True)
db = SQLDatabase.from_uri(f"sqlite:///{DB_PATH}")
db_chain = SQLDatabaseChain.from_llm(llm, db, verbose=True)
tools = [
    Tool(
        name="Search",
        func=search.run,
        description="useful for when you need to answer questions about current events. You should ask targeted questions",
    ),
    Tool(
        name="Calculator",
        func=llm_math_chain.run,
        description="useful for when you need to answer questions about math",
    ),
    Tool(
        name="FooBar DB",
        func=db_chain.run,
        description="useful for when you need to answer questions about FooBar. Input should be in the form of a question containing full context",
    ),
]

mrkl = initialize_agent(
    tools, llm, agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION, verbose=True
)

# Streamlit starts here
streamlit_handler = StreamlitCallbackHandler(st.container())
capturing_handler = CapturingCallbackHandler()

mrkl.run(
    "What is the full name of the artist who recently released an album called 'The Storm Before the Calm' and are they in the FooBar database? If so, what albums of theirs are in the FooBar database?",
    callbacks=[streamlit_handler, capturing_handler],
)

with open("runs/alanis.pickle", "wb") as file:
    pickle.dump(capturing_handler.records, file)