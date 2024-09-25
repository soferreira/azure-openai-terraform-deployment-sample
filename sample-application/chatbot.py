"""
Streamlit application for chatbot using Azure OpenAI and Llama_index.
The application allows you to upload a document and chat with the chatbot using the document as context.

In order to run the application, you need to
create a ".env" file with the following:
    OPENAI_API_TYPE = azure
    OPENAI_API_VERSION = 2023-05-15
    OPENAI_API_BASE = 'https://eastus.api.cognitive.microsoft.com/' # Replace with the URL of an Azure OpenAI
    OPENAI_API_KEY = '' # Replace with the corresponding API key
    CHAT_MODEL_NAME = gpt-4o

To run the application, use the following command:
streamlit run chatbot.py
"""

import os
import sys
import logging
from langchain.chat_models import AzureChatOpenAI
from langchain.embeddings import AzureOpenAIEmbeddings
from azure.identity import ManagedIdentityCredential
from traceloop.sdk import Traceloop

import streamlit as st
from llama_index.core import (
    SimpleDirectoryReader,
    GPTVectorStoreIndex,
    PromptHelper,
    ServiceContext,
    StorageContext,
    load_index_from_storage,
    Settings

)

from llama_index.llms.langchain import LangChainLLM
from llama_index.embeddings.langchain import LangchainEmbedding


from dotenv import load_dotenv, dotenv_values


logging.basicConfig(stream=sys.stdout, level=logging.INFO)
logging.getLogger("llama_index").setLevel(logging.DEBUG)

Traceloop.init(api_key="", app_name="chatbot", api_endpoint="http://tempo-distributor.default.svc.cluster.local:4318")

index = None
doc_path = "./data/"
index_file = "index.json"

if "config" not in st.session_state:
    # Read the environment variables
    load_dotenv()
    config = dotenv_values(".env")
    # Check if AZURE_CLIENT_ID env variable is set
    if "AZURE_CLIENT_ID" in os.environ:
       credential = ManagedIdentityCredential(client_id=os.environ["AZURE_CLIENT_ID"])
       config["OPENAI_API_KEY"]= credential.get_token("https://cognitiveservices.azure.com/.default").token
    else:
        logging.info("AZURE_CLIENT_ID not set, using OPENAI_API_KEY from .env file")
    st.session_state.config = config

if "response" not in st.session_state:
    st.session_state.response = ""

# save current file name to avoid reprocessing document
if "current_file" not in st.session_state:
    st.session_state.current_file = None

def send_click():
    query_engine = index.as_query_engine()
    # answer = query_engine.query(st.session_state.prompt)
    # st.session_state.response = answer.get_formatted_sources()
    st.session_state.response = query_engine.query(st.session_state.prompt)

st.title("Azure OpenAI Doc Chatbot")

sidebar_placeholder = st.sidebar.container()

uploaded_file = st.file_uploader("Choose a file")

# set context window
Settings.context_window = 4096
# Create the chat llm
Settings.llm = AzureChatOpenAI(
    deployment_name=st.session_state.config["CHAT_MODEL_NAME"],
    openai_api_key=st.session_state.config["OPENAI_API_KEY"],
    openai_api_base=st.session_state.config["OPENAI_API_BASE"],
    openai_api_type=st.session_state.config["OPENAI_API_TYPE"],
    openai_api_version=st.session_state.config["OPENAI_API_VERSION"],
)

# Create the embedding llm
embedding_llm = LangchainEmbedding(
    AzureOpenAIEmbeddings(
        model="text-embedding-ada-002",
        azure_deployment="text-embedding-ada-002",
        openai_api_key=st.session_state.config["OPENAI_API_KEY"],
        openai_api_base=st.session_state.config["OPENAI_API_BASE"],
        openai_api_type=st.session_state.config["OPENAI_API_TYPE"],
        openai_api_version=st.session_state.config["OPENAI_API_VERSION"],
    ),
    embed_batch_size=1,
)

# Create llama_index LLMPredictor
llm_predictor = LangChainLLM(Settings.llm)
max_input_size = 4096
num_output = 256
max_chunk_overlap = 0.5
prompt_helper = PromptHelper(max_input_size, num_output, max_chunk_overlap)


# Create llama_index ServiceContext
service_context = ServiceContext.from_defaults(
    llm_predictor=llm_predictor,
    prompt_helper=prompt_helper,
    embed_model=embedding_llm,
    chunk_size_limit=1000,
)

if uploaded_file and uploaded_file.name != st.session_state.current_file:
    # Ingest the document and create the index
    with st.spinner('Ingesting the file..'):
        doc_files = os.listdir(doc_path)
        for doc_file in doc_files:
            os.remove(doc_path + doc_file)

        bytes_data = uploaded_file.read()
        with open(f"{doc_path}{uploaded_file.name}", "wb") as f:
            f.write(bytes_data)

        loader = SimpleDirectoryReader(doc_path, recursive=True, exclude_hidden=True)
        documents = loader.load_data()
        sidebar_placeholder.header("Current Processing Document:")
        sidebar_placeholder.subheader(uploaded_file.name)
        sidebar_placeholder.write(documents[0].get_text()[:500] + "...")

        index = GPTVectorStoreIndex.from_documents(
            documents, service_context=service_context
        )

        index.set_index_id("vector_index")
        index.storage_context.persist(index_file)
        st.session_state.current_file = uploaded_file.name
        st.session_state.response = ""  # clean up the response when new file is uploaded
    st.success('Done!')

elif os.path.exists(index_file):
    # Read from storage context
    storage_context = StorageContext.from_defaults(persist_dir=index_file)
    index = load_index_from_storage(
        storage_context, index_id="vector_index", service_context=service_context
    )

    loader = SimpleDirectoryReader(doc_path, recursive=True, exclude_hidden=True)
    documents = loader.load_data()
    doc_filename = os.listdir(doc_path)[0]
    sidebar_placeholder.header("Current Processing Document:")
    sidebar_placeholder.subheader(doc_filename)
    sidebar_placeholder.write(documents[0].get_text()[:500] + "...")

if index:
    st.text_input("Ask something: ", key="prompt", on_change=send_click)
    st.button("Send", on_click=send_click)
    if st.session_state.response:
        st.subheader("Response: ")
        st.success(st.session_state.response, icon="🤖")
