#!/usr/bin/python3
"""
Fetch blog data from jasonacox.com and embed into vector database. This uses
a local Llama-2 for the embedding calculations.

Author: Jason A. Cox
8 October 2023
https://github.com/jasonacox/TinyLLM/

Credits:
    * Jacob Marks - How I Turned My Company’s Docs into a Searchable Database with OpenAI
      https://towardsdatascience.com/how-i-turned-my-companys-docs-into-a-searchable-database-with-openai-4f2d34bd8736
    * Jason Fan - How to connect Llama 2 to your own data, privately
      https://jfan001.medium.com/how-to-connect-llama-2-to-your-own-data-privately-3e14a73e82a2

"""
import os
import re
import string
import uuid
from html import unescape

import httpx
import openai
import qdrant_client as qc
import qdrant_client.http.models as qmodels

# Configuration Settings - Showing local LLM and Qdrant
openai.api_key = os.environ.get("OPENAI_API_KEY", "DEFAULT_API_KEY")            # Required, use bogus string for Llama.cpp
openai.api_base = os.environ.get("OPENAI_API_BASE", "http://localhost:8000/v1") # Use API endpoint or comment out for OpenAI
agentname = os.environ.get("AGENT_NAME", "Jarvis")                              # Set the name of your bot
MODEL = os.environ.get("MY_MODEL", "models/7B/gguf-model.bin")                  # Pick model to use e.g. gpt-3.5-turbo for OpenAI
DEBUG = os.environ.get("DEBUG", "False") == "True"
COLLECTION_NAME = os.environ.get("COLLECTION_NAME", "mylibrary") 
QDRANT_HOST = os.environ.get("QDRANT_HOST", "localhost")

# Qdrant Setup
client = qc.QdrantClient(url=QDRANT_HOST)
METRIC = qmodels.Distance.DOT
DIMENSION = 4096

# Create embeddings for text
def embed_text(text):
    response = openai.Embedding.create(
        input=text,
        model=MODEL
    )
    embeddings = response['data'][0]['embedding']
    return embeddings

# Initialize qdrant collection (will erase!)
def create_index():
    client.recreate_collection(
    collection_name=COLLECTION_NAME,
    vectors_config = qmodels.VectorParams(
            size=DIMENSION,
            distance=METRIC,
        )
    )

# Creates vector for content with attributes
def create_vector(content, title, page_url, doc_type="text"):
    vector = embed_text(content)
    uid = str(uuid.uuid1().int)[:32]
    # Document attributes
    payload = {
        "text": content,
        "title": title,
        "url": page_url,
        "doc_type": doc_type
    }
    return uid, vector, payload

# Adds document vector to qdrant database
def add_doc_to_index(text, title, url, doc_type="text"):
    ids = []
    vectors = []
    payloads = []
    uid, vector, payload = create_vector(text,title,url, doc_type)
    ids.append(uid)
    vectors.append(vector)
    payloads.append(payload)
    ## Add vectors to collection
    client.upsert(
        collection_name=COLLECTION_NAME,
        points=qmodels.Batch(
            ids = ids,
            vectors=vectors,
            payloads=payloads
        ),
    )

# Find document closely related to query
def query_index(query, top_k=5):
    vector = embed_text(query)
    results = client.search(
        collection_name=COLLECTION_NAME,
        query_vector=vector,
        limit=top_k,
        with_payload=True,
    )
    found=[]
    for res in results:
        found.append({"title": res.payload["title"],
                        "text": res.payload["text"],
                        "url": res.payload["url"],
                        "score": res.score})
    return found

#
# Main - Index Blog Articles
#
tag_re = re.compile('<.*?>') # regex to remove html tags

# blog address - rss feed in json format
feed = "https://www.jasonacox.com/wordpress/feed/json"

# pull blog content
print(f"Pulling blog json feed content from {feed}...")
data = httpx.get(feed).json()

# First time - create index and import data
create_index()

# Loop to read in all articles - ignore any errors
n = 1
for item in data["items"]:
    title = item["title"]
    url = item["url"]
    body = tag_re.sub('', item["content_html"])
    body = unescape(body)
    body = ''.join(char for char in body if char in string.printable)
    try:
        print(f"Adding: {n} : {title} [size={len(body)}]")
        add_doc_to_index(body, title, url, doc_type="text")
    except:
        print(" - ERROR: Ignoring")
    n = n + 1

# Done

